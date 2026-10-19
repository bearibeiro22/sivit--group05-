"""Conta consultas e tempo nas quatro versões do painel.

  python manage.py medir_n1

Imprime a tabela do exercício 4 em Markdown, pronta a colar em docs/tp2.md.
Não precisa de DEBUG=True: força o cursor de depuração explicitamente.
"""
import time

from django.core.management.base import BaseCommand
from django.db import connection, reset_queries

from vigilancia.views import MODOS

ETIQUETAS = {
    "ingenuo": "Ingénua",
    "select": "select_related",
    "prefetch": "+ prefetch_related",
    "subquery": "+ subquery para última leitura",
}


class Command(BaseCommand):
    help = "Mede o efeito N+1 nas quatro versões da consulta do painel."

    def add_arguments(self, parser):
        parser.add_argument("--repeticoes", type=int, default=3)

    def handle(self, *args, **o):
        anterior = connection.force_debug_cursor
        connection.force_debug_cursor = True
        try:
            self.stdout.write("| Versão | N.º de consultas | Tempo total (ms) | Linhas |")
            self.stdout.write("|---|---|---|---|")
            for modo, funcao in MODOS.items():
                consultas = tempo = linhas = 0
                for _ in range(o["repeticoes"]):
                    reset_queries()
                    t0 = time.perf_counter()
                    resultado = funcao()
                    tempo += (time.perf_counter() - t0) * 1000
                    consultas = len(connection.queries)
                    linhas = len(resultado)
                self.stdout.write(
                    f"| {ETIQUETAS[modo]} | {consultas} | "
                    f"{tempo / o['repeticoes']:.1f} | {linhas} |")
        finally:
            connection.force_debug_cursor = anterior

        self.stdout.write("""
A lição: a base de dados está no contentor ao lado, com cerca de 0,3 ms de ida
e volta, e mesmo assim a diferença é dramática. Numa arquitetura de
microserviços cada uma destas consultas seria uma chamada de rede de 2 a 10 ms.
É o mesmo erro que T4 descreve como interface remota fina demais, e o ORM
torna-o invisível, o que o torna mais perigoso.""")
