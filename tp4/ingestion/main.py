import asyncio
import os
import random
import time
from contextlib import asynccontextmanager
from datetime import datetime

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DATABASE_URL = os.environ["DATABASE_URL"]
PORTAL = os.environ.get("PORTAL_URL", "http://portal:8000")

pool = None

# Configuracao em runtime. Tudo desligado = integracao ingenua.
cfg = {"timeout": None, "retries": 0, "breaker": False, "cache_ttl": 0.0}
cache = {}  # serial -> (valido, expira_em)


class CircuitBreaker:
    """Apos `threshold` falhas seguidas, deixa de chamar durante `reset_after` s."""

    def __init__(self, threshold=5, reset_after=10.0):
        self.threshold = threshold
        self.reset_after = reset_after
        self.failures = 0
        self.opened_at = None

    def is_open(self):
        if self.opened_at is None:
            return False
        # passado o tempo, deixa passar pedidos para testar a recuperacao
        return time.monotonic() - self.opened_at < self.reset_after

    def success(self):
        self.failures = 0
        self.opened_at = None

    def failure(self):
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


breaker = CircuitBreaker()


class Reading(BaseModel):
    device: str
    instant: datetime
    parameter: str
    value: float
    unit: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(
        DATABASE_URL, min_size=2, max_size=10, command_timeout=5
    )
    yield
    await pool.close()


app = FastAPI(title="Ingestion Service", lifespan=lifespan)


def make_client():
    t = cfg["timeout"]
    return httpx.AsyncClient() if t is None else httpx.AsyncClient(timeout=t)


async def validate_device(serial: str):
    """True: admissao ativa. False: sem admissao. None: nao foi possivel validar."""
    # 4. cache local com TTL
    if cfg["cache_ttl"] > 0:
        hit = cache.get(serial)
        if hit and hit[1] > time.monotonic():
            return hit[0]
    # 3. circuit breaker
    if cfg["breaker"] and breaker.is_open():
        return None
    attempts = cfg["retries"] + 1
    for i in range(attempts):
        try:
            async with make_client() as cli:
                r = await cli.get(f"{PORTAL}/api/v1/devices/{serial}/")
            ok = r.status_code == 200 and r.json()["admission"] is not None
            breaker.success()
            if cfg["cache_ttl"] > 0:
                cache[serial] = (ok, time.monotonic() + cfg["cache_ttl"])
            return ok
        except (httpx.HTTPError, ValueError, KeyError):
            breaker.failure()
            if i < attempts - 1:
                # 2. backoff exponencial com jitter
                await asyncio.sleep(random.uniform(0, 0.05 * 2 ** i))
    return None


@app.post("/v1/readings", status_code=202)
async def ingest(batch: list[Reading]):
    unvalidated = set()
    for serial in {r.device for r in batch}:
        valid = await validate_device(serial)
        if valid is False:
            raise HTTPException(status_code=422, detail=f"device {serial} has no active admission")
        if valid is None:
            unvalidated.add(serial)  # fail open: aceita e marca para reconciliacao
    rows = [(r.device, r.instant, r.parameter, r.value, r.unit, r.device in unvalidated) for r in batch]
    async with pool.acquire() as c:
        await c.executemany("""
            INSERT INTO vigilancia_reading
                (device_serial, instant, parameter, value, unit, unvalidated)
            VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (device_serial, instant, parameter) DO NOTHING
        """, rows)
    return {"received": len(batch)}


@app.get("/admin/config")
async def get_config():
    return {**cfg, "breaker_open": breaker.is_open(), "cache_size": len(cache)}


@app.post("/admin/config")
async def set_config(timeout: float | None = None, retries: int | None = None,
                     breaker_on: bool | None = None, cache_ttl: float | None = None):
    if timeout is not None:
        cfg["timeout"] = timeout or None
    if retries is not None:
        cfg["retries"] = retries
    if breaker_on is not None:
        cfg["breaker"] = breaker_on
    if cache_ttl is not None:
        cfg["cache_ttl"] = cache_ttl
    cache.clear()
    breaker.success()
    return await get_config()


@app.post("/admin/reset")
async def reset_config():
    cfg.update(timeout=None, retries=0, breaker=False, cache_ttl=0.0)
    cache.clear()
    breaker.success()
    return await get_config()


@app.get("/health/live")
async def live():
    return {"status": "alive"}


@app.get("/health/ready")
async def ready():
    try:
        async with pool.acquire(timeout=1) as c:
            await c.fetchval("SELECT 1", timeout=1)
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}


@app.get("/test/blocking")
async def blocking():
    time.sleep(0.2)  # WRONG: blocks the event loop
    return {"ok": True}


@app.get("/test/async")
async def asynchronous():
    await asyncio.sleep(0.2)  # yields control
    return {"ok": True}


@app.get("/test/thread")
def in_thread():  # plain def: FastAPI uses a threadpool
    time.sleep(0.2)
    return {"ok": True}
