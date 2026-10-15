"""Mede as 3 estrategias de paginacao pela rede (via Nginx), como um cliente real."""
import statistics
import time
import urllib.request

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token

from vigilancia.models import Dispositivo, Leitura
from vigilancia.services import query_cursor


class Command(BaseCommand):
    help = "Tabela: primeira pagina, pagina 500 e tamanho da resposta para cada estrategia."

    def add_arguments(self, parser):
        parser.add_argument("--dispositivo", default="SN-001-0")
        parser.add_argument("--base", default="http://nginx/api/v1/devices/")
        parser.add_argument("--repeticoes", type=int, default=5)

    def medir(self, url, n):
        tempos = []
        for _ in range(n):
            req = urllib.request.Request(url, headers={"Authorization": f"Token {self.token}"})
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=30) as r:
                corpo = r.read()
            tempos.append((time.perf_counter() - t0) * 1000)
        return statistics.median(tempos), len(corpo)

    def handle(self, *args, **o):
        self.token = Token.objects.get_or_create(user=User.objects.get_or_create(username="gateway-e1")[0])[0].key
        d = Dispositivo.objects.get(numero_serie=o["dispositivo"])
        total = Leitura.objects.filter(dispositivo=d).count()
        url = f"{o['base']}{d.numero_serie}/readings/"
        n = o["repeticoes"]

        # o cursor da pagina 500 = instante da ultima linha da pagina 499 (calculado fora da medicao)
        ordem = Leitura.objects.filter(dispositivo=d).order_by("-instante")
        cursor_500 = ordem.values_list("instante", flat=True)[499 * 100 - 1]

        sem_t, sem_b = self.medir(url + "?pagination=none", max(1, n // 2))
        off1_t, off1_b = self.medir(url + "?page=1", n)
        off500_t, _ = self.medir(url + "?page=500", n)
        cur1_t, cur1_b = self.medir(url + "?" + query_cursor(ordem[0].instante, 100), n)
        cur500_t, _ = self.medir(url + "?" + query_cursor(cursor_500, 100), n)

        self.stdout.write(f"Dispositivo {d.numero_serie}: {total} leituras; paginas de 100; mediana de {n} pedidos\n")
        self.stdout.write("| Strategy | First page | Page 500 | Response size |")
        self.stdout.write("| --- | --- | --- | --- |")
        self.stdout.write(f"| No pagination | {sem_t:.0f} ms (tudo) | - | {sem_b / 1024 / 1024:.2f} MB |")
        self.stdout.write(f"| Offset (?page=) | {off1_t:.1f} ms | {off500_t:.1f} ms | {off1_b / 1024:.1f} KB |")
        self.stdout.write(f"| Cursor (?after=&limit=100) | {cur1_t:.1f} ms | {cur500_t:.1f} ms | {cur1_b / 1024:.1f} KB |")
