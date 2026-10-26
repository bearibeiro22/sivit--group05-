import logging
import math
import uuid
from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Alarme, Dispositivo

logger = logging.getLogger("sivit.portal")


class AlarmeInvalido(ValueError):
    pass


class DispositivoDesconhecido(Exception):
    pass


def _como_data(valor):
    if isinstance(valor, str):
        valor = parse_datetime(valor)
    if not isinstance(valor, datetime):
        raise AlarmeInvalido("criado_em invalido")
    if timezone.is_naive(valor):
        raise AlarmeInvalido("criado_em sem fuso horario")
    return valor


def registar_alarme(evento_id, dispositivo, parametro, valor, regra, criado_em):
    try:
        evento_id = uuid.UUID(str(evento_id))
    except ValueError:
        raise AlarmeInvalido("evento_id invalido")

    try:
        valor = float(valor)
    except (TypeError, ValueError):
        raise AlarmeInvalido("valor invalido")
    if not math.isfinite(valor):
        raise AlarmeInvalido("valor nao finito")

    parametro = str(parametro or "").strip()
    regra = str(regra or "").strip()
    if not parametro or len(parametro) > 10:
        raise AlarmeInvalido("parametro invalido")
    if not regra or len(regra) > 80:
        raise AlarmeInvalido("regra invalida")

    criado_em = _como_data(criado_em)

    try:
        disp = Dispositivo.objects.get(codigo=dispositivo)
    except Dispositivo.DoesNotExist:
        raise DispositivoDesconhecido(dispositivo)

    alarme, criado = Alarme.objects.get_or_create(
        evento_id=evento_id,
        defaults={
            "dispositivo": disp,
            "parametro": parametro,
            "valor": valor,
            "regra": regra,
            "criado_em": criado_em,
        },
    )
    if criado:
        logger.info("alarme_registado")
    else:
        logger.info("alarme_duplicado_ignorado")
    return alarme, criado