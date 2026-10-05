import time
from django.core.management.base import BaseCommand
from django.db import connection
from django.test.utils import CaptureQueriesContext
from sivit.views import build_rows

class Command(BaseCommand):
    help = "Conta queries e mede tempo de cada versao do dashboard"

    def handle(self, *args, **options):
        for v in ["naive", "select", "prefetch", "subquery"]:
            build_rows(v)
            ts = []
            for _ in range(10):
                with CaptureQueriesContext(connection) as c:
                    t = time.perf_counter()
                    build_rows(v)
                    ts.append((time.perf_counter() - t) * 1000)
            ts.sort()
            self.stdout.write(f"{v:10s} queries={len(c)} p50_ms={ts[len(ts) // 2]:.1f}")
