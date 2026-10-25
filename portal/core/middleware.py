import logging
import time

from .logs import normalizar, reset_correlation_id, set_correlation_id

logger = logging.getLogger("sivit.portal")


class CorrelationIdMiddleware:
    """Garante um X-Correlation-ID em cada pedido, no contexto de logging e na resposta."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        cid = normalizar(request.META.get("HTTP_X_CORRELATION_ID"))
        # fica em request.headers para o resto do codigo (views, API, auditoria)
        request.META["HTTP_X_CORRELATION_ID"] = cid
        token = set_correlation_id(cid)
        inicio = time.monotonic()
        try:
            response = self.get_response(request)
            response["X-Correlation-ID"] = cid
            utilizador = getattr(request, "user", None)
            nome = utilizador.username if utilizador is not None and utilizador.is_authenticated else "-"
            # os healthchecks (de 10 em 10 s) ficam em DEBUG para nao encher os logs
            nivel = logging.DEBUG if request.path.startswith(("/saude/", "/painel/estado/")) else logging.INFO
            logger.log(nivel, "pedido", extra={
                "metodo": request.method,
                "caminho": request.path,
                "estado": response.status_code,
                "duracao_ms": round((time.monotonic() - inicio) * 1000, 1),
                "utilizador": nome,
            })
            return response
        finally:
            reset_correlation_id(token)