import asyncio
import os

from fastapi import FastAPI

app = FastAPI(title="Portal stub")
delay = float(os.environ.get("DELAY", "0"))


@app.get("/api/v1/devices/{serial}/")
async def device(serial: str):
    await asyncio.sleep(delay)
    return {"serial": serial, "admission": {"id": 1, "active": True}}


@app.post("/admin/delay")
async def set_delay(seconds: float):
    global delay
    delay = seconds
    return {"delay": delay}
