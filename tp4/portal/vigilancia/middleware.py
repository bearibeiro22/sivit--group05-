import os
import time


class LatenciaArtificialMiddleware:
    """Injeta latência em todas as respostas, para as experiências de TP2-E4
    e para a falha em cascata de TP4.

    Ativa-se por ambiente, sem tocar no código:  LATENCIA_MS=3000
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.atraso = float(os.environ.get("LATENCIA_MS", "0")) / 1000.0

    def __call__(self, request):
        if self.atraso:
            time.sleep(self.atraso)
        return self.get_response(request)


import random


class DropResponseMiddleware:
    """Simula a falha real do TP3-E2: o servidor processa o pedido e grava,
    mas a resposta perde-se. Ativa-se por ambiente: DROP_RATE=0.3"""

    def __init__(self, get_response):
        self.get_response = get_response
        self.taxa = float(os.environ.get("DROP_RATE", "0"))

    def __call__(self, request):
        response = self.get_response(request)
        if self.taxa and request.path.startswith("/api/") and random.random() < self.taxa:
            raise ConnectionAbortedError("reply lost")
        return response
