"""Acrescenta N leituras sinteticas a um dispositivo (para medir a paginacao)."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from vigilancia.models import Dispositivo, Leitura


class Command(BaseCommand):
    help = "Carrega N leituras num dispositivo, 1 por segundo para tras a partir de ha 1 dia."

    def add_arguments(self, parser):
        parser.add_argument("--dispositivo", default="SN-001-0")
        parser.add_argument("--n", type=int, default=50000)

    def handle(self, *args, **o):
        d = Dispositivo.objects.get(numero_serie=o["dispositivo"])
        base = timezone.now().replace(microsecond=0) - timedelta(days=1)
        leituras = [Leitura(dispositivo=d, instante=base - timedelta(seconds=s), parametro="FC",
                            unidade="bpm", valor=60 + s % 40) for s in range(o["n"])]
        Leitura.objects.bulk_create(leituras, batch_size=5000, ignore_conflicts=True)
        with connection.cursor() as c:
            c.execute("ANALYZE vigilancia_leitura")      # atualiza as estatisticas do planeador
        self.stdout.write(f"{d.numero_serie}: {Leitura.objects.filter(dispositivo=d).count()} leituras")
