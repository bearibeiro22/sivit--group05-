"""Regras do dominio, sem HTTP: a API (TP3) e o consumidor da fila (TP5) reutilizam isto."""
from urllib.parse import urlencode

from django.db import transaction
from django.db.models import OuterRef, Prefetch, Subquery

from .models import Dispositivo, Internamento, Leitura


def _linha(internamento, dispositivo, valor, unidade, instante):
    return {
        "doente": internamento.doente.nome,
        "cama": f"{internamento.enfermaria}/{internamento.cama}",
        "tipo": dispositivo.tipo,
        "valor": valor,
        "unidade": unidade,
        "instante": instante,
    }


def _ultima(dispositivo):
    # 1 query por dispositivo
    u = dispositivo.leituras.order_by("-instante").first()
    return (u.valor, u.unidade, u.instante) if u else (None, None, None)


def linhas_ingenuo():
    linhas = []
    for i in Internamento.objects.filter(alta__isnull=True):        # 1 query
        for d in i.dispositivos.all():                               # +1 por internamento
            linhas.append(_linha(i, d, *_ultima(d)))                 # +1 por dispositivo, +1 doente por internamento
    return linhas


def linhas_select_related():
    linhas = []
    ativos = Internamento.objects.filter(alta__isnull=True).select_related("doente")  # JOIN com doente
    for i in ativos:
        for d in i.dispositivos.all():
            linhas.append(_linha(i, d, *_ultima(d)))
    return linhas


def linhas_prefetch():
    linhas = []
    ativos = (Internamento.objects.filter(alta__isnull=True)
              .select_related("doente")
              .prefetch_related("dispositivos"))                     # +1 query para todos os dispositivos
    for i in ativos:
        for d in i.dispositivos.all():                               # ja em memoria
            linhas.append(_linha(i, d, *_ultima(d)))
    return linhas


def linhas_subquery():
    ultima = Leitura.objects.filter(dispositivo=OuterRef("pk")).order_by("-instante")
    dispositivos = Dispositivo.objects.annotate(            # a ultima leitura vem na mesma query, por SQL
        ultimo_valor=Subquery(ultima.values("valor")[:1]),
        ultima_unidade=Subquery(ultima.values("unidade")[:1]),
        ultimo_instante=Subquery(ultima.values("instante")[:1]),
    )
    ativos = (Internamento.objects.filter(alta__isnull=True)
              .select_related("doente")
              .prefetch_related(Prefetch("dispositivos", queryset=dispositivos)))
    linhas = []
    for i in ativos:
        for d in i.dispositivos.all():
            linhas.append(_linha(i, d, d.ultimo_valor, d.ultima_unidade, d.ultimo_instante))
    return linhas


MODOS = {
    "ingenuo": linhas_ingenuo,
    "select_related": linhas_select_related,
    "prefetch": linhas_prefetch,
    "subquery": linhas_subquery,
}


# ---------------------------------------------------------------- API (TP3)
def ingerir_leituras(dados):
    """Guarda um lote de leituras. Duplicados (mesmo dispositivo, instante e parametro) sao
    ignorados pela base de dados: reenviar o mesmo lote nao muda nada (idempotente)."""
    leituras = [Leitura(**d) for d in dados]
    with transaction.atomic():
        antes = Leitura.objects.count()
        Leitura.objects.bulk_create(leituras, ignore_conflicts=True)   # INSERT ... ON CONFLICT DO NOTHING
        inseridas = Leitura.objects.count() - antes
    return {"received": len(leituras), "inserted": inseridas, "ignored": len(leituras) - inseridas}


def query_cursor(instante, limite):
    """Parametros do proximo pedido na paginacao por cursor."""
    return urlencode({"after": instante.isoformat(), "limit": limite})
