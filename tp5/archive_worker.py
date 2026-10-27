import asyncio
import json
import aio_pika

async def main():
    # Ligação robusta ao RabbitMQ a correr no Docker local
    connection = await aio_pika.connect_robust("amqp://guest:guest@localhost/")
    
    async with connection:
        # Criar um canal de comunicação
        channel = await connection.channel()
        
        # Definir o prefetch_count (limita quantas mensagens não confirmadas o worker recebe em simultâneo)
        await channel.set_qos(prefetch_count=10)
        
        # Declarar o topic exchange (deve coincidir com o usado na ingestão)
        exchange = await channel.declare_exchange(
            "readings", aio_pika.ExchangeType.TOPIC, durable=True
        )
        
        # Declarar a fila do arquivo (durable=True para garantir persistência)
        queue = await channel.declare_queue("archive", durable=True)
        
        # Ligar a fila ao exchange usando uma routing key genérica para capturar todas as leituras
        await queue.bind(exchange, routing_key="reading.#")
        
        print(" [*] Archive worker à escuta de leituras. Pressiona CTRL+C para sair.")
        
        # Consumir as mensagens de forma assídua
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                # O bloco 'async with message.process()' faz o ACK automático 
                # se o código correr sem exceções, ou rejeita se houver erro.
                async with message.process():
                    data = json.loads(message.body.decode())

                    await asyncio.sleep(0.05)
                    print(f" [x] Guardado no arquivo -> Dispositivo: {data['device']} | Parâmetro: {data['parameter']} | Valor: {data['value']}")

if __name__ == "__main__":
    asyncio.run(main())