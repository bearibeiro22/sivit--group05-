import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Alarme, Cama, Internamento, RegistoAuditoria
from .services import AlarmeJaReconhecido, AlarmeNaoEncontrado, reconhecer_alarme


def _cid(request):
    return request.headers.get("X-Correlation-ID") or str(uuid.uuid4())


def camas_visiveis(user):
    qs = Cama.objects.select_related("enfermaria", "dispositivo")
    if user.is_superuser or user.groups.filter(name="medico").exists():
        return qs
    perfil = getattr(user, "perfil", None)
    if perfil is None or perfil.enfermaria_id is None:
        return qs.none()
    return qs.filter(enfermaria_id=perfil.enfermaria_id)


@login_required
def painel(request):
    camas = list(camas_visiveis(request.user))
    ids = [c.pk for c in camas]

    internamentos = {
        i.cama_id: i
        for i in Internamento.objects.filter(cama_id__in=ids, data_saida__isnull=True).select_related("doente")
    }
    alarmes = {}
    ativos = Alarme.objects.filter(
        estado=Alarme.Estado.ATIVO, dispositivo__cama_id__in=ids
    ).select_related("dispositivo").order_by("criado_em")
    for a in ativos:
        alarmes.setdefault(a.dispositivo.cama_id, []).append(a)

    linhas = [
        {"cama": c, "internamento": internamentos.get(c.pk), "alarmes": alarmes.get(c.pk, [])}
        for c in camas
    ]

    # Auditoria: um registo por doente cujos dados sao apresentados
    cid = _cid(request)
    RegistoAuditoria.objects.bulk_create([
        RegistoAuditoria(utilizador=request.user, doente=i.doente, acao="ver_painel",
                         caminho=request.path, correlation_id=cid)
        for i in internamentos.values()
    ])

    return render(request, "core/painel.html", {"linhas": linhas, "total_alarmes": len(ativos)})


@login_required
@require_POST
def reconhecer(request, pk):
    try:
        reconhecer_alarme(pk, request.user, correlation_id=_cid(request))
        messages.success(request, "Alarme reconhecido.")
    except AlarmeJaReconhecido as e:
        quando = timezone.localtime(e.em).strftime("%H:%M:%S") if e.em else "?"
        quem = e.por.username if e.por else "?"
        messages.warning(request, f"Este alarme já foi reconhecido por {quem} às {quando}.")
    except AlarmeNaoEncontrado:
        messages.error(request, "Alarme não encontrado.")
    except PermissionDenied as e:
        messages.error(request, f"Sem permissão: {e}")
    return redirect("painel")