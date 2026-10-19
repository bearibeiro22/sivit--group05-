"""Painel de internamentos ativos, nas quatro versões do exercício 4.

A versão é escolhida por ?modo=..., para que a mesma página possa ser medida
lado a lado:  /painel/?modo=ingenuo  ...  /painel/?modo=subquery
"""
from django.db.models import OuterRef, Prefetch, Subquery
from django.http import JsonResponse
from django.shortcuts import render

from .models import Dispositivo, Internamento, Leitura


def _linhas_ingenuo():
    linhas = []
    for i in Internamento.objects.filter(alta__isnull=True):       # 1 consulta
        for d in i.dispositivos.all():                             # N consultas
            ultima = d.leituras.order_by("-instante").first()      # N×M consultas
            linhas.append((i.doente.nome, d.tipo, ultima))         # + N consultas
    return linhas


def _linhas_select_related():
    consulta = (Internamento.objects
                .filter(alta__isnull=True)
                .select_related("doente"))                  # JOIN, não consulta por linha
    linhas = []
    for i in consulta:
        for d in i.dispositivos.all():
            ultima = d.leituras.order_by("-instante").first()
            linhas.append((i.doente.nome, d.tipo, ultima))
    return linhas


def _linhas_prefetch():
    consulta = (Internamento.objects
                .filter(alta__isnull=True)
                .select_related("doente")
                .prefetch_related("dispositivos"))          # 1 consulta extra, não N
    linhas = []
    for i in consulta:
        for d in i.dispositivos.all():
            ultima = d.leituras.order_by("-instante").first()
            linhas.append((i.doente.nome, d.tipo, ultima))
    return linhas


def _linhas_subquery():
    """Uma consulta agregada em vez de N×M: a última leitura vem anotada."""
    ultima = (Leitura.objects
              .filter(dispositivo=OuterRef("pk"))
              .order_by("-instante"))
    com_ultima = Dispositivo.objects.annotate(
        ultimo_valor=Subquery(ultima.values("valor")[:1]),
        ultimo_instante=Subquery(ultima.values("instante")[:1]),
        ultimo_parametro=Subquery(ultima.values("parametro")[:1]),
    )
    consulta = (Internamento.objects
                .filter(alta__isnull=True)
                .select_related("doente")
                .prefetch_related(Prefetch("dispositivos", queryset=com_ultima)))
    linhas = []
    for i in consulta:
        for d in i.dispositivos.all():
            resumo = (f"{d.ultimo_parametro} {d.ultimo_valor} em {d.ultimo_instante:%H:%M:%S}"
                      if d.ultimo_instante else "sem leituras")
            linhas.append((i.doente.nome, d.tipo, resumo))
    return linhas


MODOS = {
    "ingenuo": _linhas_ingenuo,
    "select": _linhas_select_related,
    "prefetch": _linhas_prefetch,
    "subquery": _linhas_subquery,
}


def painel(request):
    modo = request.GET.get("modo", "subquery")
    linhas = MODOS.get(modo, _linhas_subquery)()
    return render(request, "painel.html", {"linhas": linhas, "modo": modo})


def saude(request):
    """Prontidão: só responde 200 se a base de dados responder."""
    from django.db import connection
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        return JsonResponse({"estado": "pronto"})
    except Exception as e:                                   # noqa: BLE001
        return JsonResponse({"estado": "indisponivel", "erro": str(e)}, status=503)
