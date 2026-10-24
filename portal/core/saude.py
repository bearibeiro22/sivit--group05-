from django.db import connection
from django.http import JsonResponse


def bd_disponivel():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True
    except Exception:
        return False


def vivo(request):
    """Liveness: o processo responde. Nao depende de mais nada."""
    return JsonResponse({"estado": "vivo"})


def pronto(request):
    """Readiness: o portal consegue servir pedidos (precisa da base de dados)."""
    if bd_disponivel():
        return JsonResponse({"estado": "pronto", "base_de_dados": "ok"})
    return JsonResponse({"estado": "indisponivel", "base_de_dados": "falha"}, status=503)