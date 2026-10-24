from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.utils import timezone

from . import models
from .services import ConflitoNegocio, admitir_doente, associar_dispositivo, auditar, dar_alta

admin.site.site_header = "SIVIT · Gestão"
admin.site.site_title = "SIVIT"
admin.site.index_title = "Gestão de doentes, internamentos e dispositivos"


class SoLeituraMixin:
    """Só consulta: sem criar, alterar nem apagar."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class SemApagarMixin:
    """Um sistema clínico não apaga registos: dá alta."""

    def has_delete_permission(self, request, obj=None):
        return False


class GestaoMixin:
    """Traduz conflitos de negócio em mensagens e audita os acessos a dados de doentes."""

    acao_ver = None
    acao_listar = None

    def doente_ids(self, obj):
        return []

    def _auditar_ids(self, request, acao, ids):
        ids = {i for i in ids if i}
        if not acao or not ids:
            return
        cid = request.headers.get("X-Correlation-ID", "")
        models.RegistoAuditoria.objects.bulk_create([
            models.RegistoAuditoria(utilizador=request.user, doente_id=i, acao=acao,
                                    caminho=request.path, correlation_id=cid)
            for i in ids
        ])

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            resp = super().changeform_view(request, object_id, form_url, extra_context)
        except ConflitoNegocio as e:
            self.message_user(request, str(e), level=messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())
        if request.method == "GET" and object_id:
            adminform = (getattr(resp, "context_data", None) or {}).get("adminform")
            inst = adminform.form.instance if adminform is not None else None
            if inst is not None and inst.pk:
                self._auditar_ids(request, self.acao_ver, self.doente_ids(inst))
        return resp

    def changelist_view(self, request, extra_context=None):
        resp = super().changelist_view(request, extra_context)
        cl = (getattr(resp, "context_data", None) or {}).get("cl")
        if cl is not None:
            ids = []
            for obj in cl.result_list:
                ids += self.doente_ids(obj)
            self._auditar_ids(request, self.acao_listar, ids)
        return resp


@admin.register(models.Enfermaria)
class EnfermariaAdmin(admin.ModelAdmin):
    list_display = ("nome",)


@admin.register(models.Cama)
class CamaAdmin(admin.ModelAdmin):
    list_display = ("enfermaria", "numero")
    list_filter = ("enfermaria",)


@admin.register(models.Dispositivo)
class DispositivoAdmin(GestaoMixin, admin.ModelAdmin):
    list_display = ("codigo", "cama")
    search_fields = ("codigo",)

    def get_readonly_fields(self, request, obj=None):
        return ("codigo",) if obj else ()

    def save_model(self, request, obj, form, change):
        if change:
            associar_dispositivo(obj, obj.cama, request.user)
        else:
            super().save_model(request, obj, form, change)


@admin.register(models.Doente)
class DoenteAdmin(SemApagarMixin, GestaoMixin, admin.ModelAdmin):
    list_display = ("numero_processo", "nome", "data_nascimento")
    search_fields = ("numero_processo", "nome")
    acao_ver = "admin_ver_doente"
    acao_listar = "admin_listar_doentes"

    def doente_ids(self, obj):
        return [obj.pk]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        auditar(request.user, "editar_doente" if change else "criar_doente", request.path, "", obj)


@admin.register(models.Internamento)
class InternamentoAdmin(SemApagarMixin, GestaoMixin, admin.ModelAdmin):
    list_display = ("doente", "cama", "data_entrada", "data_saida")
    list_filter = ("cama__enfermaria",)
    list_select_related = ("doente", "cama__enfermaria")
    actions = ["dar_alta_action"]
    acao_ver = "admin_ver_internamento"
    acao_listar = "admin_listar_internamentos"

    def doente_ids(self, obj):
        return [obj.doente_id]

    def get_changeform_initial_data(self, request):
        return {"data_entrada": timezone.now()}

    def get_fields(self, request, obj=None):
        campos = ["doente", "cama", "data_entrada"]
        return campos + ["data_saida"] if obj else campos

    def has_change_permission(self, request, obj=None):
        # um internamento existente só se consulta; a alta faz-se pela ação
        if obj is not None:
            return False
        return super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        # criar = admitir (regras e auditoria do serviço, as mesmas da API)
        novo = admitir_doente(obj.doente, obj.cama, obj.data_entrada, request.user)
        obj.pk = novo.pk
        obj._state.adding = False
        obj.refresh_from_db()

    @admin.action(description="Dar alta aos internamentos selecionados", permissions=["change"])
    def dar_alta_action(self, request, queryset):
        feitos = 0
        for internamento in queryset.filter(data_saida__isnull=True):
            try:
                dar_alta(internamento.pk, request.user)
                feitos += 1
            except ConflitoNegocio:
                pass
        self.message_user(request, f"Alta registada em {feitos} internamento(s).")


@admin.register(models.Alarme)
class AlarmeAdmin(SoLeituraMixin, admin.ModelAdmin):
    # só se reconhece pelo painel ou pela API (exclusão mútua no serviço)
    list_display = ("criado_em", "dispositivo", "parametro", "valor", "estado", "reconhecido_por")
    list_filter = ("estado", "parametro")


@admin.register(models.PerfilUtilizador)
class PerfilUtilizadorAdmin(admin.ModelAdmin):
    list_display = ("utilizador", "enfermaria")


@admin.register(models.RegistoAuditoria)
class RegistoAuditoriaAdmin(SoLeituraMixin, admin.ModelAdmin):
    list_display = ("criado_em", "utilizador", "acao", "doente", "caminho", "correlation_id")
    list_filter = ("acao", "utilizador")
    search_fields = ("correlation_id", "caminho", "utilizador__username", "acao")
    date_hierarchy = "criado_em"
    list_select_related = ("utilizador", "doente")