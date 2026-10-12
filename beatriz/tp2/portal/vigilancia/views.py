import time

from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.test.utils import CaptureQueriesContext

from .services import MODOS, linhas_ingenuo


def painel(request):
    modo = request.GET.get("modo", "ingenuo")                      # ?modo=...
    funcao = MODOS.get(modo, linhas_ingenuo)
    with CaptureQueriesContext(connection) as q:                    # conta as queries deste pedido
        t0 = time.perf_counter()
        linhas = funcao()                                           # pede os dados a camada de dados
        ms = (time.perf_counter() - t0) * 1000
    return render(request, "painel.html", {                         # entrega ao template
        "linhas": linhas, "modo": modo, "modos": MODOS.keys(),
        "n_queries": len(q), "ms": ms,
    })


def saude(request):
    """Readiness check: 200 so se a base de dados responder."""
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        return JsonResponse({"estado": "pronto"})
    except Exception as e:
        return JsonResponse({"estado": "indisponivel", "erro": str(e)}, status=503)
