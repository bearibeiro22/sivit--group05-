"""Mede cada modo do painel: numero de queries e tempo (mediana de N execucoes)."""
import statistics
import time

from django.core.management.base import BaseCommand
from django.db import connection, reset_queries

from vigilancia.services import MODOS

NOMES = {
    "ingenuo": "Naive",
    "select_related": "+ select_related",
    "prefetch": "+ prefetch_related",
    "subquery": "+ subquery for last reading",
}


class Command(BaseCommand):
    help = "Tabela do efeito N+1 (queries e tempo por modo)."

    def add_arguments(self, parser):
        parser.add_argument("--repeticoes", type=int, default=10)

    def handle(self, *args, **o):
        connection.force_debug_cursor = True        # regista as queries mesmo com DEBUG=0
        self.stdout.write("| Versao | Queries | Tempo total (ms) |")
        self.stdout.write("| --- | --- | --- |")
        for modo, funcao in MODOS.items():
            funcao()                                # aquecimento (abre a ligacao)
            tempos = []
            for _ in range(o["repeticoes"]):
                reset_queries()
                t0 = time.perf_counter()
                linhas = funcao()
                tempos.append((time.perf_counter() - t0) * 1000)
                n = len(connection.queries)
            self.stdout.write(f"| {NOMES[modo]} | {n} | {statistics.median(tempos):.1f} |")
        self.stdout.write(f"\n({len(linhas)} linhas por pedido, mediana de {o['repeticoes']} execucoes)")
