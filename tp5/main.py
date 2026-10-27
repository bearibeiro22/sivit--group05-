import asyncio
import json
from datetime import datetime, timezone
import aio_pika
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

class Reading(BaseModel):
    device: str
    instant: datetime
    parameter: str
    value: float

app = FastAPI()

# Variável global para o exchange (idealmente inicializado no lifespan do FastAPI)
exchange = None
connection = None
channel = None

@app.on_event("startup")
async def startup_event():
    global connection, channel, exchange
    # Ligação ao RabbitMQ a correr localmente
    connection = await aio_pika.connect_robust("amqp://guest:guest@localhost/")
    channel = await connection.channel()
    # Declarar um topic exchange durável
    exchange = await channel.declare_exchange(
        "readings", aio_pika.ExchangeType.TOPIC, durable=True
    )

@app.on_event("shutdown")
async def shutdown_event():
    if connection:
        await connection.close()

async def publish(r: Reading):
    body = r.model_dump(mode="json")
    body["_published_at"] = datetime.now(timezone.utc).isoformat()  # útil para métricas de latência[cite: 8]
    
    await exchange.publish(
        aio_pika.Message(
            body=json.dumps(body).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,  # Mensagem persistente[cite: 8, 9]
            message_id=f"{r.device}|{r.instant.isoformat()}|{r.parameter}"  # Chave de deduplicação[cite: 8, 9]
        ),
        routing_key=f"reading.{r.parameter.lower()}.{r.device}"
    )

@app.post("/v1/readings", status_code=202)
async def ingest(batch: list[Reading]):
    try:
        await asyncio.gather(*(publish(r) for r in batch))  # Envio em paralelo[cite: 8]
    except Exception:
        raise HTTPException(503, "broker unavailable")
        
    return {"received": len(batch)}