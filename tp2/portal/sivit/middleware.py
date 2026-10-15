import os
import random


class DropResponseMiddleware:
    """Simula a perda da resposta: o pedido é processado (a escrita na BD
    acontece), mas o cliente nunca recebe a resposta."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.probability = float(os.environ.get("DROP_RESPONSE_PROB", "0"))

    def __call__(self, request):
        response = self.get_response(request)  # a view já correu e gravou
        if request.method == "POST" and random.random() < self.probability:
            raise ConnectionAbortedError("reply lost")
        return response
