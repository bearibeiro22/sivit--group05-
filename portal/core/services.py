from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Alarme, Dispositivo, Internamento, RegistoAuditoria


class AlarmeNaoEncontrado(Exception):
    pass


class AlarmeJaReconhecido(Exception):
    """Outro profissional reconheceu o alarme primeiro."""

    def __init__(self, por, em):
        super().__init__("Alarme ja reconhecido")
        self.por = por
        self.em = em


class ConflitoNegocio(Exception):
    """Operacao em conflito com o estado atual (traduz-se em HTTP 409)."""


def auditar(utilizador, acao, caminho, correlation_id="", doente=None):
    RegistoAuditoria.objects.create(
        utilizador=utilizador, doente=doente, acao=acao,
        caminho=caminho, correlation_id=correlation_id,
    )


def _enfermaria_do_alarme(alarme):
    cama = alarme.dispositivo.cama
    return cama.enfermaria_id if cama else None


def reconhecer_alarme(alarme_id, utilizador, correlation_id=""):
    """Reconhece um alarme com exclusao mutua.

    O reconhecimento e um UPDATE condicional (estado='ativo'): o PostgreSQL
    serializa as escritas concorrentes na mesma linha e so uma devolve 1 linha
    afetada. As restantes levantam AlarmeJaReconhecido.
    """
    if not utilizador.has_perm("core.change_alarme"):
        raise PermissionDenied("Sem permissao para reconhecer alarmes")

    try:
        alarme = Alarme.objects.select_related("dispositivo__cama").get(pk=alarme_id)
    except Alarme.DoesNotExist:
        raise AlarmeNaoEncontrado(alarme_id)

    # O enfermeiro so atua na sua enfermaria
    if not utilizador.is_superuser:
        perfil = getattr(utilizador, "perfil", None)
        if perfil is None or perfil.enfermaria_id != _enfermaria_do_alarme(alarme):
            raise PermissionDenied("Alarme de outra enfermaria")

    with transaction.atomic():
        agora = timezone.now()
        afetadas = Alarme.objects.filter(
            pk=alarme_id, estado=Alarme.Estado.ATIVO
        ).update(
            estado=Alarme.Estado.RECONHECIDO,
            reconhecido_por=utilizador,
            reconhecido_em=agora,
        )
        if afetadas == 0:
            atual = Alarme.objects.select_related("reconhecido_por").get(pk=alarme_id)
            raise AlarmeJaReconhecido(atual.reconhecido_por, atual.reconhecido_em)

        internamento = Internamento.objects.filter(
            cama=alarme.dispositivo.cama, data_saida__isnull=True
        ).first()
        RegistoAuditoria.objects.create(
            utilizador=utilizador,
            doente=internamento.doente if internamento else None,
            acao="reconhecer_alarme",
            caminho=f"alarme/{alarme_id}",
            correlation_id=correlation_id,
        )

    alarme.refresh_from_db()
    return alarme


def admitir_doente(doente, cama, data_entrada, utilizador, correlation_id=""):
    """Cria um internamento. Uma cama so tem um internamento ativo e um doente tambem.

    A verificacao previa da mensagens claras; a garantia sob concorrencia vem das
    restricoes unicas parciais da BD (IntegrityError -> ConflitoNegocio).
    """
    if Internamento.objects.filter(cama=cama, data_saida__isnull=True).exists():
        raise ConflitoNegocio("A cama já está ocupada.")
    if Internamento.objects.filter(doente=doente, data_saida__isnull=True).exists():
        raise ConflitoNegocio("O doente já tem um internamento ativo.")
    try:
        with transaction.atomic():
            internamento = Internamento.objects.create(
                doente=doente, cama=cama, data_entrada=data_entrada)
            auditar(utilizador, "admitir_doente", f"internamento/{internamento.pk}",
                    correlation_id, doente)
    except IntegrityError:
        raise ConflitoNegocio("Conflito com outra admissão em simultâneo.")
    return internamento


def dar_alta(internamento_id, utilizador, correlation_id=""):
    """Termina um internamento ativo (UPDATE condicional, como no reconhecimento)."""
    with transaction.atomic():
        afetadas = Internamento.objects.filter(
            pk=internamento_id, data_saida__isnull=True
        ).update(data_saida=timezone.now())
        if afetadas == 0:
            raise ConflitoNegocio("O internamento já terminou.")
        internamento = Internamento.objects.select_related("doente").get(pk=internamento_id)
        auditar(utilizador, "dar_alta", f"internamento/{internamento_id}",
                correlation_id, internamento.doente)
    return internamento


def associar_dispositivo(dispositivo, cama, utilizador, correlation_id=""):
    """Associa (ou, com cama=None, desassocia) um dispositivo a uma cama."""
    if cama is not None and Dispositivo.objects.filter(cama=cama).exclude(pk=dispositivo.pk).exists():
        raise ConflitoNegocio("A cama já tem um dispositivo associado.")
    try:
        with transaction.atomic():
            dispositivo.cama = cama
            dispositivo.save(update_fields=["cama"])
            auditar(utilizador, "associar_dispositivo", f"dispositivo/{dispositivo.pk}",
                    correlation_id)
    except IntegrityError:
        raise ConflitoNegocio("Conflito com outra associação em simultâneo.")
    return dispositivo