import random

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (Alarme, Cama, Dispositivo, Doente, Enfermaria, Internamento,
                         PerfilUtilizador)

ENFERMARIAS = {"Medicina Interna A": 6, "Medicina Interna B": 4}
PASSWORD_DEMO = "Sivit2026!x"


class Command(BaseCommand):
    help = "Cria dados sinteticos de demonstracao (idempotente). Use --alarme para disparar um alarme novo."

    def add_arguments(self, parser):
        parser.add_argument("--alarme", action="store_true", help="Cria um alarme ativo novo")

    def handle(self, *args, **opts):
        call_command("criar_grupos")
        U = get_user_model()
        n = 0
        enfs = {}
        for nome, ncamas in ENFERMARIAS.items():
            enf, _ = Enfermaria.objects.get_or_create(nome=nome)
            enfs[nome] = enf
            letra = nome[-1]
            for i in range(1, ncamas + 1):
                cama, _ = Cama.objects.get_or_create(enfermaria=enf, numero=i)
                Dispositivo.objects.get_or_create(codigo=f"DEV-{letra}-{i:02d}", defaults={"cama": cama})
                # os 2 ultimos leitos de cada enfermaria ficam vagos
                if i <= ncamas - 2:
                    n += 1
                    doente, _ = Doente.objects.get_or_create(
                        numero_processo=f"SINT-{n:03d}",
                        defaults={"nome": f"Doente Sintetico {n:02d}", "data_nascimento": "1950-01-01"},
                    )
                    if not Internamento.objects.filter(doente=doente, data_saida__isnull=True).exists():
                        Internamento.objects.get_or_create(
                            cama=cama, data_saida=None,
                            defaults={"doente": doente, "data_entrada": timezone.now()},
                        )

        utilizadores = [
            ("enfermeiro1", "enfermeiro", enfs["Medicina Interna A"]),
            ("enfermeiro2", "enfermeiro", enfs["Medicina Interna A"]),
            ("enfermeiro3", "enfermeiro", enfs["Medicina Interna B"]),
            ("medico1", "medico", None),
        ]
        for username, grupo, enf in utilizadores:
            u, criado = U.objects.get_or_create(username=username)
            if criado:
                u.set_password(PASSWORD_DEMO)
                u.save()
            u.groups.set([Group.objects.get(name=grupo)])
            if u.is_staff != (grupo == "medico"):
                u.is_staff = grupo == "medico"
                u.save(update_fields=["is_staff"])
            PerfilUtilizador.objects.update_or_create(utilizador=u, defaults={"enfermaria": enf})

        if opts["alarme"] or not Alarme.objects.exists():
            ativos = list(Dispositivo.objects.filter(cama__internamentos__data_saida__isnull=True).distinct())
            disp = random.choice(ativos)
            Alarme.objects.create(dispositivo=disp, parametro="SpO2", valor=85,
                                  regra="SpO2 < 90% durante 30 s", criado_em=timezone.now())
            self.stdout.write(f"Alarme criado em {disp.codigo}")

        self.stdout.write("Povoamento concluido.")