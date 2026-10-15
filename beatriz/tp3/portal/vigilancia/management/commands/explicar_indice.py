"""EXPLAIN ANALYZE das queries da pagina 500 (offset e cursor), com e sem indices."""
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from vigilancia.models import Dispositivo, Leitura


class Command(BaseCommand):
    help = "Mostra o plano e o tempo das queries de paginacao, com e sem indices."

    def add_arguments(self, parser):
        parser.add_argument("--dispositivo", default="SN-001-0")

    def plano(self, sql, params, sem_indices):
        with transaction.atomic(), connection.cursor() as c:
            if sem_indices:   # so nesta transacao: obriga o PostgreSQL a ler a tabela toda
                c.execute("SET LOCAL enable_indexscan = off; SET LOCAL enable_bitmapscan = off;"
                          " SET LOCAL enable_indexonlyscan = off;")
            c.execute("EXPLAIN ANALYZE " + sql, params)
            linhas = [r[0] for r in c.fetchall()]
        return [l for l in linhas if any(k in l for k in ("Scan", "Sort", "Limit", "Execution Time"))]

    def handle(self, *args, **o):
        d = Dispositivo.objects.get(numero_serie=o["dispositivo"])
        ordem = Leitura.objects.filter(dispositivo=d).order_by("-instante")
        cursor_500 = ordem.values_list("instante", flat=True)[499 * 100 - 1]
        offset_sql, offset_p = ordem[49900:50000].query.sql_with_params()
        cursor_sql, cursor_p = ordem.filter(instante__lt=cursor_500)[:100].query.sql_with_params()
        with connection.cursor() as c:
            c.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'vigilancia_leitura' ORDER BY 1")
            self.stdout.write("Indices em vigilancia_leitura:")
            for nome, definicao in c.fetchall():
                self.stdout.write(f"  {nome}: {definicao.split(' USING ')[1]}")
        for nome, sql, params in [("OFFSET 49900 (pagina 500)", offset_sql, offset_p),
                                  ("CURSOR (pagina 500)", cursor_sql, cursor_p)]:
            for sem in (False, True):
                self.stdout.write(f"\n=== {nome} · {'SEM indices' if sem else 'COM indices'}")
                for linha in self.plano(sql, params, sem):
                    self.stdout.write("  " + linha.strip())
