from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

VER = ["enfermaria", "cama", "dispositivo", "doente", "internamento", "alarme"]

GRUPOS = {
    # enfermeiro: ve dados e reconhece alarmes (change_alarme)
    "enfermeiro": [f"view_{m}" for m in VER] + ["change_alarme"],
    # medico: ve tudo, gere doentes/internamentos e associa dispositivos
    "medico": (
        [f"view_{m}" for m in VER]
        + ["add_doente", "change_doente", "add_internamento", "change_internamento", "change_dispositivo"]
    ),
}


class Command(BaseCommand):
    help = "Cria (ou atualiza) os grupos enfermeiro e medico com as suas permissoes."

    def handle(self, *args, **options):
        for nome, codenames in GRUPOS.items():
            grupo, _ = Group.objects.get_or_create(name=nome)
            perms = Permission.objects.filter(content_type__app_label="core", codename__in=codenames)
            if perms.count() != len(codenames):
                self.stderr.write(f"Aviso: permissoes em falta para {nome}")
            grupo.permissions.set(perms)
            self.stdout.write(f"{nome}: {perms.count()} permissoes")
