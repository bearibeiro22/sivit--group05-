from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import Alarme, Internamento, RegistoAuditoria


class AlarmeNaoEncontrado(Exception):
    pass


class AlarmeJaReconhecido(Exception):
    """Outro profissional reconheceu o alarme primeiro."""

    def __init__(self, por, em):
        super().__init__("Alarme ja reconhecido")
        self.por = por
        self.em = em


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
