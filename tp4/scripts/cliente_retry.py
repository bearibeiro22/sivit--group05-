"""Cliente com retries: envia 5 lotes de 10 leituras e repete enquanto falhar."""
import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080/api/v1/readings/"


def enviar(lote, tentativas=15):
    corpo = json.dumps(lote).encode()
    for n in range(1, tentativas + 1):
        req = urllib.request.Request(
            URL, data=corpo, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Token " + os.environ["TOKEN"]})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return n, r.status, json.loads(r.read())
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            print(f"    tentativa {n} falhou: {e}")
            time.sleep(0.2)
    raise SystemExit("desisti: demasiadas falhas")


total = 0
for b in range(5):
    lote = [{"dispositivo": "SN1",
             "instante": f"2026-10-17T12:{b:02d}:{i:02d}Z",
             "parametro": "FC", "valor": 70 + i, "unidade": "bpm"}
            for i in range(10)]
    n, status, resp = enviar(lote)
    total += n
    print(f"lote {b + 1}: {n} tentativa(s), HTTP {status}, {resp}")
print(f"pedidos enviados: {total} (para 5 lotes)")
