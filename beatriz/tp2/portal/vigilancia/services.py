"""Regras do dominio, sem HTTP: a API (TP3) e o consumidor da fila (TP5) reutilizam isto."""
from .models import Internamento


def linhas_ingenuo():
    """Versao ingenua (exercicio 4 vai medi-la e corrigi-la)."""
    linhas = []
    for i in Internamento.objects.filter(alta__isnull=True):        # 1 query
        for d in i.dispositivos.all():                               # +1 por internamento
            u = d.leituras.order_by("-instante").first()             # +1 por dispositivo
            linhas.append({
                "doente": i.doente.nome,                             # +1 por internamento
                "cama": f"{i.enfermaria}/{i.cama}",
                "tipo": d.tipo,
                "valor": u.valor if u else None,
                "unidade": u.unidade if u else "",
                "instante": u.instante if u else None,
            })
    return linhas


MODOS = {"ingenuo": linhas_ingenuo}
