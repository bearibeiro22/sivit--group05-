"""Gerador de carga com medição, para os exercícios 2 e 3.

  python carga.py <url> --concorrencia 50 --duracao 15
  python carga.py <url> --metodo POST --lote 10 --dispositivos 20 ...

Substitui o `hey` ou o `wrk`: evita instalações e mede exatamente o que
interessa para as tabelas do guião, incluindo leituras perdidas.
"""
import argparse
import asyncio
import json
import random
import statistics
import time
from datetime import datetime, timedelta, timezone

import httpx


def percentil(amostras, q):
    a = sorted(amostras)
    return a[min(len(a) - 1, int(len(a) * q))] if a else float("nan")


def gerar_lote(n_dispositivos, tamanho, contador):
    base = datetime.now(timezone.utc).replace(microsecond=0)
    return [{
        "dispositivo": f"SN-{random.randint(1, n_dispositivos):04d}-{random.randint(0, 2)}",
        "instante": (base + timedelta(milliseconds=contador * 1000 + i)).isoformat(),
        "parametro": "FC", "valor": round(random.uniform(60, 100), 1),
        "unidade": "bpm",
    } for i in range(tamanho)]


async def trabalhador(cliente, args, estado, fim):
    # Com --taxa, cada trabalhador espaça os seus pedidos para que o conjunto
    # não ultrapasse a taxa pedida. É o que permite encher uma fila devagar e
    # observá-la a crescer, em vez de a saturar de imediato.
    intervalo = (args.concorrencia / args.taxa) if args.taxa else 0.0
    proximo = time.monotonic()
    while time.monotonic() < fim:
        if args.maximo and estado["contador"] >= args.maximo:
            return
        if intervalo:
            proximo += intervalo
            atraso = proximo - time.monotonic()
            if atraso > 0:
                await asyncio.sleep(atraso)
            if time.monotonic() >= fim:
                break
        estado["contador"] += 1
        t0 = time.perf_counter()
        try:
            if args.metodo == "POST":
                r = await cliente.post(args.url,
                                       json=gerar_lote(args.dispositivos, args.lote,
                                                       estado["contador"]))
            else:
                r = await cliente.get(args.url)
            ms = (time.perf_counter() - t0) * 1000
            estado["amostras"].append(ms)
            if r.status_code < 400:
                estado["ok"] += 1
                estado["leituras_confirmadas"] += args.lote if args.metodo == "POST" else 0
            else:
                estado["erros"] += 1
                estado["por_codigo"][r.status_code] = estado["por_codigo"].get(r.status_code, 0) + 1
        except Exception as e:                                  # noqa: BLE001
            estado["amostras"].append((time.perf_counter() - t0) * 1000)
            estado["falhas"] += 1
            estado["por_codigo"][type(e).__name__] = estado["por_codigo"].get(type(e).__name__, 0) + 1


async def principal(args):
    estado = {"ok": 0, "erros": 0, "falhas": 0, "amostras": [], "contador": 0,
              "leituras_confirmadas": 0, "por_codigo": {}}
    limites = httpx.Limits(max_connections=args.concorrencia * 2)
    async with httpx.AsyncClient(timeout=args.timeout, limits=limites) as cliente:
        inicio = time.monotonic()
        fim = inicio + args.duracao
        await asyncio.gather(*(trabalhador(cliente, args, estado, fim)
                               for _ in range(args.concorrencia)))
        decorrido = time.monotonic() - inicio

    total = estado["ok"] + estado["erros"] + estado["falhas"]
    enviadas = estado["contador"] * (args.lote if args.metodo == "POST" else 1)
    resultado = {
        "pedidos": total,
        "debito_req_s": round(total / decorrido, 1),
        "ok": estado["ok"], "erros_http": estado["erros"], "falhas": estado["falhas"],
        "media_ms": round(statistics.mean(estado["amostras"]), 2) if estado["amostras"] else None,
        "p50_ms": round(percentil(estado["amostras"], .50), 2),
        "p95_ms": round(percentil(estado["amostras"], .95), 2),
        "p99_ms": round(percentil(estado["amostras"], .99), 2),
        "por_codigo": estado["por_codigo"],
    }
    if args.metodo == "POST":
        resultado["leituras_enviadas"] = enviadas
        resultado["leituras_confirmadas"] = estado["leituras_confirmadas"]
        resultado["leituras_perdidas"] = enviadas - estado["leituras_confirmadas"]
    print(json.dumps(resultado))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--metodo", default="GET", choices=["GET", "POST"])
    p.add_argument("--concorrencia", type=int, default=50)
    p.add_argument("--duracao", type=float, default=10.0)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--lote", type=int, default=10)
    p.add_argument("--dispositivos", type=int, default=20)
    p.add_argument("--taxa", type=float, default=0.0,
                   help="pedidos por segundo no total (0 = sem limite)")
    p.add_argument("--maximo", type=int, default=0,
                   help="parar ao fim de N pedidos (0 = sem limite)")
    asyncio.run(principal(p.parse_args()))
