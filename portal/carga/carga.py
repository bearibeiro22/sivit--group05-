#!/usr/bin/env python3
"""Ferramenta de carga do portal SIVIT (RNF5). Usa so a biblioteca padrao.

Simula N utilizadores (sessoes autenticadas, ligacao persistente) e mede a latencia de cada pedido.
Cenarios:
  polling  cada utilizador pede /painel/estado/ a cada intervalo (o que o painel faz no browser)
  misto    polling + API de alarmes (a cada 5 ciclos) + pagina completa do painel (a cada 10 ciclos)
Com --sem-pausa nao ha espera entre pedidos: serve para procurar o ponto de saturacao.
"""
import argparse
import csv
import http.client
import itertools
import math
import os
import random
import threading
import time
from collections import Counter
from datetime import datetime
from http.cookies import SimpleCookie
from urllib.parse import urlencode, urlparse

PLANOS = {
    "polling": [("polling", "/painel/estado/", 1)],
    "misto": [
        ("polling", "/painel/estado/", 1),
        ("api_alarmes", "/api/v1/alarmes/?page_size=50", 5),
        ("pagina", "/", 10),
    ],
}


class Sessao:
    def __init__(self, base):
        self.base = base.rstrip("/")
        u = urlparse(base)
        self.host = u.hostname
        self.https = u.scheme == "https"
        self.porta = u.port or (443 if self.https else 80)
        self.cookies = {}
        self.conn = None

    def _ligar(self):
        cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        self.conn = cls(self.host, self.porta, timeout=30)

    def pedir(self, metodo, caminho, corpo=None, cabecalhos=None):
        if self.conn is None:
            self._ligar()
        h = {"Accept": "*/*"}
        if self.cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if cabecalhos:
            h.update(cabecalhos)
        try:
            self.conn.request(metodo, caminho, body=corpo, headers=h)
            r = self.conn.getresponse()
            r.read()
        except Exception:
            self.conn.close()
            self.conn = None
            raise
        for sc in r.headers.get_all("Set-Cookie") or []:
            c = SimpleCookie()
            c.load(sc)
            for k, m in c.items():
                self.cookies[k] = m.value
        return r.status

    def login(self, utilizador, palavra_passe):
        self.pedir("GET", "/accounts/login/")
        corpo = urlencode({
            "username": utilizador,
            "password": palavra_passe,
            "csrfmiddlewaretoken": self.cookies.get("csrftoken", ""),
        })
        estado = self.pedir("POST", "/accounts/login/", corpo, {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": self.base + "/accounts/login/",
        })
        return estado == 302 and "sessionid" in self.cookies

    def medir(self, caminho):
        t = time.perf_counter()
        try:
            estado = self.pedir("GET", caminho)
        except Exception:
            estado = 0
        return (time.perf_counter() - t) * 1000.0, estado


def utilizador(idx, args, plano, conta, barreira, amostras, falhas):
    s = Sessao(args.base)
    try:
        ok = s.login(*conta)
    except Exception:
        ok = False
    if not ok:
        falhas.append(conta[0])
    barreira.wait()  # todos arrancam ao mesmo tempo (o login nao entra na medicao)
    if not ok:
        return
    intervalo = 0.0 if args.sem_pausa else args.intervalo
    if intervalo > 0:
        time.sleep(random.random() * intervalo)  # fases diferentes, como browsers reais
    inicio = time.perf_counter()
    fim = inicio + args.aquecimento + args.duracao
    minha = amostras[idx]
    ciclo = 0
    while True:
        t0 = time.perf_counter()
        if t0 >= fim:
            break
        for rotulo, caminho, cada in plano:
            if ciclo % cada == 0:
                ms, estado = s.medir(caminho)
                if time.perf_counter() - inicio >= args.aquecimento:
                    minha.append((time.time(), rotulo, ms, estado))
        ciclo += 1
        espera = intervalo - (time.perf_counter() - t0)
        if espera > 0:
            time.sleep(espera)


def percentil(valores, p):
    o = sorted(valores)
    return o[min(len(o) - 1, max(0, math.ceil(p / 100 * len(o)) - 1))]


def linha_resumo(nome, pares, duracao):
    ok = [ms for ms, estado in pares if estado == 200]
    erros = len(pares) - len(ok)
    if ok:
        p = (percentil(ok, 50), percentil(ok, 95), percentil(ok, 99), max(ok))
    else:
        p = (float("nan"),) * 4
    return (nome, len(pares), erros, len(pares) / duracao) + p


def main():
    ap = argparse.ArgumentParser(description="Carga do portal SIVIT")
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--utilizadores", type=int, default=20)
    ap.add_argument("--duracao", type=float, default=60.0, help="segundos medidos (apos o aquecimento)")
    ap.add_argument("--aquecimento", type=float, default=5.0, help="segundos descartados no inicio")
    ap.add_argument("--intervalo", type=float, default=1.0, help="segundos entre ciclos de cada utilizador")
    ap.add_argument("--cenario", choices=sorted(PLANOS), default="misto")
    ap.add_argument("--sem-pausa", action="store_true", help="sem espera entre pedidos (procura a saturacao)")
    ap.add_argument("--contas", default="enfermeiro1,enfermeiro2,enfermeiro3,medico1")
    ap.add_argument("--password", default=os.environ.get("SIVIT_DEMO_PASSWORD", "Sivit2026!x"))
    args = ap.parse_args()

    plano = PLANOS[args.cenario]
    nomes = args.contas.split(",")
    contas = list(itertools.islice(((n, args.password) for n in itertools.cycle(nomes)), args.utilizadores))
    barreira = threading.Barrier(args.utilizadores)
    amostras = [[] for _ in range(args.utilizadores)]
    falhas = []

    modo = "sem pausa" if args.sem_pausa else f"intervalo {args.intervalo:g} s"
    print(f"A simular {args.utilizadores} utilizadores ({args.cenario}, {modo}) em {args.base}")
    print(f"Aquecimento {args.aquecimento:g} s + medicao {args.duracao:g} s ...")
    threads = [
        threading.Thread(target=utilizador, args=(i, args, plano, contas[i], barreira, amostras, falhas))
        for i in range(args.utilizadores)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if falhas:
        print(f"AVISO: login falhou para {len(falhas)} utilizador(es): {sorted(set(falhas))}")
    todas = [a for lista in amostras for a in lista]
    if not todas:
        print("Sem amostras. Confirme o endereco e as credenciais.")
        return 1

    por = {}
    for _, rotulo, ms, estado in todas:
        por.setdefault(rotulo, []).append((ms, estado))
    linhas = [linha_resumo(r, por[r], args.duracao) for r in sorted(por)]
    linhas.append(linha_resumo("TOTAL", [(ms, e) for _, _, ms, e in todas], args.duracao))

    cab = f"{'pedido':<12}{'n':>7}{'erros':>7}{'req/s':>8}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'max ms':>9}"
    print()
    print(cab)
    print("-" * len(cab))
    for nome, n, erros, rps, p50, p95, p99, mx in linhas:
        print(f"{nome:<12}{n:>7}{erros:>7}{rps:>8.1f}{p50:>9.1f}{p95:>9.1f}{p99:>9.1f}{mx:>9.1f}")
    print("\nEstados HTTP:", dict(Counter(e for _, _, _, e in todas)))
    total = linhas[-1]
    cumpre = total[2] == 0 and total[5] < 1000
    print(f"RNF5 (p95 < 1000 ms, sem erros), TOTAL: {'SIM' if cumpre else 'NAO'}"
          " (so conta com 500 000 leituras na base)")

    pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
    os.makedirs(pasta, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    caminho_csv = os.path.join(pasta, f"carga-{marca}.csv")
    with open(caminho_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["instante", "pedido", "ms", "estado"])
        for inst, rotulo, ms, estado in sorted(todas):
            w.writerow([f"{inst:.3f}", rotulo, f"{ms:.2f}", estado])
    caminho_md = os.path.join(pasta, f"carga-{marca}.md")
    with open(caminho_md, "w", encoding="utf-8") as f:
        f.write(f"# Carga do portal ({marca})\n\n")
        f.write(f"- Base: {args.base}\n- Utilizadores: {args.utilizadores}\n- Cenario: {args.cenario} ({modo})\n")
        f.write(f"- Aquecimento: {args.aquecimento:g} s; medicao: {args.duracao:g} s\n\n")
        f.write("| pedido | n | erros | req/s | p50 ms | p95 ms | p99 ms | max ms |\n|---|---|---|---|---|---|---|---|\n")
        for nome, n, erros, rps, p50, p95, p99, mx in linhas:
            f.write(f"| {nome} | {n} | {erros} | {rps:.1f} | {p50:.1f} | {p95:.1f} | {p99:.1f} | {mx:.1f} |\n")
    print(f"\nGuardado: {caminho_md}\n          {caminho_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())