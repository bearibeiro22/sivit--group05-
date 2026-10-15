"""Dados SINTETICOS: 20 internamentos ativos x 3 dispositivos x 50 leituras."""
import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from vigilancia.models import Dispositivo, Doente, Internamento, Leitura

PARAMETROS = {  # tipo -> (parametro, unidade, minimo, maximo)
    "ECG": ("FC", "bpm", 55, 120),
    "SpO2": ("SpO2", "%", 88, 100),
    "NIBP": ("PAS", "mmHg", 95, 160),
    "TEMP": ("TEMP", "C", 35.8, 39.0),
}


class Command(BaseCommand):
    help = "Apaga os dados e cria dados sinteticos para o painel."

    def add_arguments(self, parser):
        parser.add_argument("--internamentos", type=int, default=20)
        parser.add_argument("--dispositivos", type=int, default=3)
        parser.add_argument("--leituras", type=int, default=50)

    @transaction.atomic
    def handle(self, *args, **o):
        rnd = random.Random(42)                     # sempre os mesmos dados
        Leitura.objects.all().delete()
        Dispositivo.objects.all().delete()
        Internamento.objects.all().delete()
        Doente.objects.all().delete()

        agora = timezone.now().replace(microsecond=0)
        tipos = list(PARAMETROS)
        leituras = []
        for n in range(1, o["internamentos"] + 1):
            doente = Doente.objects.create(
                codigo=f"D{n:04d}", nome=f"Doente {n:03d}",
                data_nascimento=date(1940, 1, 1) + timedelta(days=rnd.randint(0, 25000)))
            internamento = Internamento.objects.create(
                doente=doente, enfermaria=f"E{1 + n % 3}", cama=f"{n:02d}",
                admissao=agora - timedelta(days=rnd.randint(1, 10)))
            for k in range(o["dispositivos"]):
                tipo = tipos[k % len(tipos)]
                d = Dispositivo.objects.create(numero_serie=f"SN-{n:03d}-{k}", tipo=tipo,
                                               internamento=internamento)
                parametro, unidade, lo, hi = PARAMETROS[tipo]
                for s in range(o["leituras"]):
                    leituras.append(Leitura(dispositivo=d, instante=agora - timedelta(minutes=s),
                                            parametro=parametro, unidade=unidade,
                                            valor=round(rnd.uniform(lo, hi), 1)))
        Leitura.objects.bulk_create(leituras)
        self.stdout.write(self.style.SUCCESS(
            f"{Internamento.objects.count()} internamentos, {Dispositivo.objects.count()} "
            f"dispositivos, {Leitura.objects.count()} leituras"))
