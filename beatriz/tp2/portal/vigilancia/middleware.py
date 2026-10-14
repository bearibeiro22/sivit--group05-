import os
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
