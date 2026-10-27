import asyncio
import httpx
import time

async def send_batch(client):
    # Cria um lote com 10 leituras para simular tráfego intenso
    batch = [
        {
            "device": f"sensor-{i}",
            "instant": "2026-10-22T16:00:00Z",
            "parameter": "HR",
            "value": 75.5
        } for i in range(10)
    ]
    try:
        response = await client.post("http://127.0.0.1:8000/v1/readings", json=batch)
        return response.status_code == 202
    except Exception:
        return False

async def main():
    print("🚀 A iniciar teste de carga (10x load for 60s)...")
    async with httpx.AsyncClient(timeout=10.0) as client:
        start_time = time.time()
        total_batches = 0
        
        # Corre durante 60 segundos
        while time.time() - start_time < 60:
            tasks = [send_batch(client) for _ in range(20)]
            results = await asyncio.gather(*tasks)
            total_batches += sum(1 for r in results if r)
            await asyncio.sleep(0.05)
            
    print(f"✅ Teste concluído! Lotes aceitos (202 Accepted): {total_batches}")

if __name__ == "__main__":
    asyncio.run(main())