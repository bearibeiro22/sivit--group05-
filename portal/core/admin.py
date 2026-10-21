from django.contrib import admin
from . import models


@admin.register(models.Enfermaria)
class EnfermariaAdmin(admin.ModelAdmin):
    list_display = ("nome",)


@admin.register(models.Cama)
class CamaAdmin(admin.ModelAdmin):
    list_display = ("enfermaria", "numero")
    list_filter = ("enfermaria",)


@admin.register(models.Dispositivo)
class DispositivoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "cama")


@admin.register(models.Doente)
class DoenteAdmin(admin.ModelAdmin):
    list_display = ("numero_processo", "nome", "data_nascimento")
    search_fields = ("numero_processo", "nome")


@admin.register(models.Internamento)
class InternamentoAdmin(admin.ModelAdmin):
    list_display = ("doente", "cama", "data_entrada", "data_saida")
    list_filter = ("cama__enfermaria",)


@admin.register(models.Alarme)
class AlarmeAdmin(admin.ModelAdmin):
    list_display = ("criado_em", "dispositivo", "parametro", "valor", "estado", "reconhecido_por")
    list_filter = ("estado", "parametro")
    readonly_fields = ("evento_id", "reconhecido_por", "reconhecido_em")


@admin.register(models.PerfilUtilizador)
class PerfilUtilizadorAdmin(admin.ModelAdmin):
    list_display = ("utilizador", "enfermaria")


@admin.register(models.RegistoAuditoria)
class RegistoAuditoriaAdmin(admin.ModelAdmin):
    list_display = ("criado_em", "utilizador", "acao", "doente", "caminho")
    list_filter = ("acao",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
