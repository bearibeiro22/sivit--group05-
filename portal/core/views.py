import hashlib
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import Alarme, Cama, Internamento, RegistoAuditoria
from .services import AlarmeJaReconhecido, AlarmeNaoEncontrado, reconhecer_alarme

# Intervalo entre pedidos de atualizacao do painel (ms). O atraso maximo com que um
# alarme novo aparece e este intervalo mais o tempo de resposta (RNF6: p95 < 3 s).
INTERVALO_MS = 1000


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


def _dados_painel(user):
    """Camas visiveis, internamentos ativos, alarmes ativos por cama, total e versao da ocupacao."""
    camas = list(camas_visiveis(user))
    ids = [c.pk for c in camas]

    internamentos = {
        i.cama_id: i
        for i in Internamento.objects.filter(cama_id__in=ids, data_saida__isnull=True).select_related("doente")
    }
    ativos = list(
        Alarme.objects.filter(estado=Alarme.Estado.ATIVO, dispositivo__cama_id__in=ids)
        .select_related("dispositivo").order_by("criado_em")
    )
    alarmes = {}
    for a in ativos:
        alarmes.setdefault(a.dispositivo.cama_id, []).append(a)

    # muda quando muda o conjunto de camas ou quem esta em cada uma (a pagina recarrega)
    partes = [f"{c.pk}:{internamentos[c.pk].doente_id if c.pk in internamentos else 0}" for c in camas]
    versao = hashlib.sha256("|".join(partes).encode()).hexdigest()[:12]
    return camas, internamentos, alarmes, len(ativos), versao


@login_required
def painel(request):
    camas, internamentos, alarmes, total, versao = _dados_painel(request.user)
    linhas = [
        {"cama": c, "internamento": internamentos.get(c.pk), "alarmes": alarmes.get(c.pk, [])}
        for c in camas
    ]

    # Auditoria: um registo por doente cujos dados sao apresentados (carga completa da pagina)
    cid = _cid(request)
    RegistoAuditoria.objects.bulk_create([
        RegistoAuditoria(utilizador=request.user, doente=i.doente, acao="ver_painel",
                         caminho=request.path, correlation_id=cid)
        for i in internamentos.values()
    ])

    return render(request, "core/painel.html", {
        "linhas": linhas, "total_alarmes": total, "versao": versao, "intervalo_ms": INTERVALO_MS,
    })


@login_required
@never_cache
def painel_estado(request):
    """Estado leve para o polling do painel: so alarmes ativos por cama e a versao da ocupacao.

    Nao inclui dados de doentes (por isso nao gera auditoria a cada pedido).
    """
    _, _, alarmes, total, versao = _dados_painel(request.user)
    return JsonResponse({
        "versao": versao,
        "total": total,
        "alarmes": {
            str(cama_id): [
                {
                    "id": a.pk,
                    "parametro": a.parametro,
                    "valor": a.valor,
                    "regra": a.regra,
                    "hora": timezone.localtime(a.criado_em).strftime("%H:%M:%S"),
                }
                for a in lista
            ]
            for cama_id, lista in alarmes.items()
        },
    })


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