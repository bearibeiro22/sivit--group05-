import os
import random
import time


class LatenciaArtificialMiddleware:
    """Atrasa cada pedido LATENCIA_MS milissegundos (0 = desligado). Serve para experiencias."""

    def __init__(self, get_response):                 # uma vez, quando o worker arranca
        self.get_response = get_response
        self.atraso = float(os.environ.get("LATENCIA_MS", "0")) / 1000

    def __call__(self, request):                      # em cada pedido
        if self.atraso and not request.path.startswith("/static/"):
            time.sleep(self.atraso)
        return self.get_response(request)             # passa o pedido ao resto da cadeia


class PerdaRespostaMiddleware:
    """Simula a resposta perdida na rede: o pedido E processado (e gravado), mas o cliente
    recebe um erro em vez da resposta. Probabilidade em PERDA_RESPOSTA (0 = desligado).
    So afeta POST a /api/."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)         # o trabalho ja foi feito
        prob = float(os.environ.get("PERDA_RESPOSTA", "0"))
        if prob and request.method == "POST" and request.path.startswith("/api/") \
                and random.random() < prob:
            raise ConnectionAbortedError("reply lost")  # o cliente recebe 500, nao a resposta
        return response
