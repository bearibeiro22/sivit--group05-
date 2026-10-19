import asyncio
import os
import random
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator

DATABASE_URL = os.environ["DATABASE_URL"]
PORTAL = os.environ.get("PORTAL", "http://portal:8000")
PORTAL_TOKEN = os.environ.get("PORTAL_TOKEN", "")
MODO = os.environ.get("MODO_VALIDACAO", "off")

ORDEM = ["off", "sincrona", "timeout", "retry", "disjuntor", "cache"]
NIVEL = ORDEM.index(MODO)
USA_TIMEOUT = NIVEL >= 2
USA_RETRY = NIVEL >= 3
USA_DISJUNTOR = NIVEL >= 4
USA_CACHE = NIVEL >= 5

TIMEOUT_S = float(os.environ.get("TIMEOUT_S", "0.5"))
TENTATIVAS = int(os.environ.get("TENTATIVAS", "3"))
BACKOFF_BASE = float(os.environ.get("BACKOFF_BASE", "0.1"))
LIMIAR = int(os.environ.get("LIMIAR_DISJUNTOR", "5"))
ESPERA = float(os.environ.get("ESPERA_DISJUNTOR", "10"))
CACHE_TTL = float(os.environ.get("CACHE_TTL", "60"))

INSERIR = """
INSERT INTO vigilancia_leitura (dispositivo_id, instante, parametro, valor, unidade)
SELECT d.id, $2::timestamptz, $3::text, $4::float8, $5::text
FROM vigilancia_dispositivo d
WHERE d.numero_serie = $1
ON CONFLICT (dispositivo_id, instante, parametro) DO NOTHING
"""

CRIAR_RECONCILIAR = """
CREATE TABLE IF NOT EXISTS ingestao_reconciliar (
    dispositivo text PRIMARY KEY,
    desde timestamptz NOT NULL DEFAULT now()
)
"""

RECONCILIAR = "INSERT INTO ingestao_reconciliar (dispositivo) VALUES ($1) ON CONFLICT DO NOTHING"

ESTADO = {
    "validacoes": 0,
    "falhas_validacao": 0,
    "retries": 0,
    "nao_validadas": 0,
    "rejeitadas_disjuntor": 0,
    "cache_hits": 0,
    "rejeitadas": 0,
    "pedidos_502": 0,
}
CACHE = {}
SINALIZADOS = set()


class FalhaPortal(Exception):
    pass


class Disjuntor:
    def __init__(self, limiar, espera):
        self.limiar = limiar
        self.espera = espera
        self.falhas = 0
        self.aberto_ate = 0.0
        self.a_testar = False

    def permite(self):
        if self.falhas < self.limiar:
            return True
        if time.monotonic() < self.aberto_ate or self.a_testar:
            return False
        self.a_testar = True
        return True

    def sucesso(self):
        self.falhas = 0
        self.a_testar = False

    def falha(self):
        self.falhas += 1
        self.a_testar = False
        if self.falhas >= self.limiar:
            self.aberto_ate = time.monotonic() + self.espera

    @property
    def estado(self):
        if self.falhas < self.limiar:
            return "fechado"
        return "aberto" if time.monotonic() < self.aberto_ate else "meio-aberto"


DISJUNTOR = Disjuntor(LIMIAR, ESPERA)


class Leitura(BaseModel):
    dispositivo: str
    instante: datetime
    parametro: str
    valor: float
    unidade: str

    @field_validator("instante")
    @classmethod
    def com_fuso(cls, v):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    for _ in range(30):
        try:
            app.state.pool = await asyncpg.create_pool(
                DATABASE_URL, min_size=5, max_size=20)
            break
        except Exception:
            await asyncio.sleep(1)
    else:
        raise RuntimeError("base de dados indisponivel")
    async with app.state.pool.acquire() as c:
        await c.execute(CRIAR_RECONCILIAR)
    app.state.http = httpx.AsyncClient(
        base_url=PORTAL,
        headers={"Authorization": f"Token {PORTAL_TOKEN}"},
        timeout=httpx.Timeout(TIMEOUT_S) if USA_TIMEOUT else None,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=20),
    )
    yield
    await app.state.http.aclose()
    await app.state.pool.close()


app = FastAPI(title="SIVIT ingestao", lifespan=lifespan)


async def consultar(serie):
    r = await app.state.http.get(f"/api/v1/devices/{serie}/")
    if r.status_code == 200:
        try:
            corpo = r.json()
        except ValueError:
            raise FalhaPortal("resposta invalida")
        return corpo.get("internamento") is not None
    if r.status_code == 404:
        return False
    raise FalhaPortal(f"HTTP {r.status_code}")


async def chamar(serie):
    tentativas = TENTATIVAS if USA_RETRY else 1
    for n in range(tentativas):
        if USA_DISJUNTOR and not DISJUNTOR.permite():
            ESTADO["rejeitadas_disjuntor"] += 1
            return None
        try:
            resultado = await consultar(serie)
        except (httpx.HTTPError, FalhaPortal):
            ESTADO["falhas_validacao"] += 1
            if USA_DISJUNTOR:
                DISJUNTOR.falha()
            if n == tentativas - 1:
                raise
            ESTADO["retries"] += 1
            await asyncio.sleep(random.uniform(0, BACKOFF_BASE * 2 ** n))
        else:
            if USA_DISJUNTOR:
                DISJUNTOR.sucesso()
            return resultado


async def validar(serie):
    if MODO == "off":
        return True
    ESTADO["validacoes"] += 1
    if USA_CACHE:
        entrada = CACHE.get(serie)
        if entrada and entrada[1] > time.monotonic():
            ESTADO["cache_hits"] += 1
            return entrada[0]
    try:
        resultado = await chamar(serie)
    except (httpx.HTTPError, FalhaPortal):
        if not USA_TIMEOUT:
            raise
        resultado = None
    if resultado is None:
        ESTADO["nao_validadas"] += 1
        return None
    if USA_CACHE:
        CACHE[serie] = (resultado, time.monotonic() + CACHE_TTL)
    return resultado


@app.post("/v1/leituras", status_code=202)
async def ingerir(lote: list[Leitura]):
    unicos = list({l.dispositivo for l in lote})
    try:
        resultados = await asyncio.gather(*(validar(s) for s in unicos))
    except (httpx.HTTPError, FalhaPortal):
        ESTADO["pedidos_502"] += 1
        raise HTTPException(status_code=502, detail="validacao indisponivel")
    veredito = dict(zip(unicos, resultados))
    aceites = [l for l in lote if veredito[l.dispositivo] is not False]
    novos = [s for s, v in veredito.items() if v is None and s not in SINALIZADOS]
    ESTADO["rejeitadas"] += len(lote) - len(aceites)
    linhas = [(l.dispositivo, l.instante, l.parametro, l.valor, l.unidade)
              for l in aceites]
    async with app.state.pool.acquire() as c:
        if linhas:
            await c.executemany(INSERIR, linhas)
        if novos:
            await c.executemany(RECONCILIAR, [(s,) for s in novos])
    SINALIZADOS.update(novos)
    return {
        "recebidas": len(lote),
        "rejeitadas": len(lote) - len(aceites),
        "nao_validadas": sum(1 for l in aceites if veredito[l.dispositivo] is None),
    }


@app.get("/estado")
async def estado():
    return {
        "modo": MODO,
        "disjuntor": DISJUNTOR.estado if USA_DISJUNTOR else None,
        "cache_entradas": len(CACHE),
        "sinalizados": len(SINALIZADOS),
        **ESTADO,
    }


@app.get("/saude/viva")
async def viva():
    return {"estado": "viva"}


@app.get("/saude/pronto")
async def pronto():
    try:
        async with app.state.pool.acquire(timeout=1) as c:
            await c.fetchval("SELECT 1", timeout=1)
    except Exception:
        raise HTTPException(status_code=503, detail="base de dados indisponivel")
    return {"estado": "pronto"}


@app.get("/teste/bloqueante")
async def bloqueante():
    time.sleep(0.2)
    return {"ok": True}


@app.get("/teste/assincrono")
async def assincrono():
    await asyncio.sleep(0.2)
    return {"ok": True}


@app.get("/teste/thread")
def em_thread():
    time.sleep(0.2)
    return {"ok": True}

@app.get("/health/live")
async def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready():
    try:
        async with app.state.pool.acquire(timeout=1) as c:
            await c.fetchval("SELECT 1", timeout=1)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Base de dados indisponivel"
        )
    return {"status": "ready"}
