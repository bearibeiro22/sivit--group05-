"""Camada de serviço: lógica de domínio sem HTTP.

Exigida no Trabalho 1. As views (TP2), a API (TP3) e os consumidores de fila
(TP5) chamam estas funções, e por isso a regra de negócio existe uma só vez e
é testável sem cliente HTTP.
"""
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Dispositivo, Internamento, Leitura

LIMITES_PLAUSIVEIS = {
    "FC": (20, 250), "SPO2": (50, 100), "TEMP": (30, 45),
    "PAS": (40, 260), "PAD": (20, 160), "FR": (4, 60),
}


class ValorImplausivel(ValueError):
    pass


def registar_leitura(numero_serie, instante, parametro, valor, unidade):
    """Devolve (leitura, criada). Reenviar a mesma leitura não duplica."""
    limites = LIMITES_PLAUSIVEIS.get(parametro)
    if limites and not limites[0] <= valor <= limites[1]:
        raise ValorImplausivel(
            f"valor {valor} fora do intervalo plausível para {parametro}")

    dispositivo = Dispositivo.objects.get(numero_serie=numero_serie)
    try:
        with transaction.atomic():
            leitura = Leitura.objects.create(
                dispositivo=dispositivo, instante=instante,
                parametro=parametro, valor=valor, unidade=unidade)
        return leitura, True
    except IntegrityError:
        # A restrição UNIQUE apanhou um reenvio: resultado idempotente.
        return Leitura.objects.get(dispositivo=dispositivo, instante=instante,
                                   parametro=parametro), False


def abrir_internamento(codigo_doente, enfermaria, cama):
    from .models import Doente
    doente = Doente.objects.get(codigo=codigo_doente)
    return Internamento.objects.create(
        doente=doente, enfermaria=enfermaria, cama=cama,
        admissao=timezone.now())


def dar_alta(internamento_id):
    with transaction.atomic():
        i = Internamento.objects.select_for_update().get(pk=internamento_id)
        i.alta = timezone.now()
        i.versao += 1
        i.save(update_fields=["alta", "versao"])
    return i
