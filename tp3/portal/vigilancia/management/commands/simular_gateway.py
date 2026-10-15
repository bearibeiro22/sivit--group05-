"""Gateway simulado: envia lotes de leituras pela rede (via Nginx) e repete quando nao recebe
resposta valida. No fim compara as linhas esperadas com as que ficaram na base de dados."""
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token

from vigilancia.models import Dispositivo, Leitura

INICIO = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)   # instantes fixos: o mesmo lote e sempre igual


class Command(BaseCommand):
    help = "Envia lotes com retry e verifica se o estado final esta correto."

    def add_arguments(self, parser):
        parser.add_argument("--dispositivo", default="SN-001-0")
        parser.add_argument("--lotes", type=int, default=20)
        parser.add_argument("--tamanho", type=int, default=10)
        parser.add_argument("--url", default="http://nginx/api/v1/readings/")
        parser.add_argument("--tentativas", type=int, default=10)

    def handle(self, *args, **o):
        token = Token.objects.get_or_create(user=User.objects.get_or_create(username="gateway-e1")[0])[0].key
        d = Dispositivo.objects.get(numero_serie=o["dispositivo"])
        Leitura.objects.filter(dispositivo=d, instante__gte=INICIO,
                               instante__lt=INICIO + timedelta(days=1)).delete()   # recomecar do zero

        pedidos = perdidas = 0
        for lote in range(o["lotes"]):
            corpo = json.dumps([{
                "device": d.numero_serie,
                "instant": (INICIO + timedelta(seconds=lote * o["tamanho"] + k)).isoformat(),
                "parameter": "TEMP", "value": 37.0, "unit": "C",
            } for k in range(o["tamanho"])]).encode()
            for tentativa in range(1, o["tentativas"] + 1):
                pedidos += 1
                req = urllib.request.Request(o["url"], data=corpo, method="POST", headers={
                    "Content-Type": "application/json", "Authorization": f"Token {token}"})
                try:
                    with urllib.request.urlopen(req, timeout=5) as r:
                        if r.status == 201:
                            break
                except (urllib.error.URLError, TimeoutError):
                    perdidas += 1                     # sem resposta valida: nao sabemos se gravou
                    time.sleep(0.05 * tentativa)      # espera um pouco e repete o MESMO lote
            else:
                self.stderr.write(f"lote {lote} desistiu ao fim de {o['tentativas']} tentativas")

        esperadas = o["lotes"] * o["tamanho"]
        na_bd = Leitura.objects.filter(dispositivo=d, instante__gte=INICIO,
                                       instante__lt=INICIO + timedelta(days=1)).count()
        self.stdout.write(f"lotes enviados:            {o['lotes']} x {o['tamanho']} leituras")
        self.stdout.write(f"pedidos HTTP (com retries): {pedidos}")
        self.stdout.write(f"respostas perdidas:         {perdidas}")
        self.stdout.write(f"linhas esperadas:           {esperadas}")
        self.stdout.write(f"linhas na base de dados:    {na_bd}  -> {'CORRETO' if na_bd == esperadas else 'DUPLICADOS!'}")
