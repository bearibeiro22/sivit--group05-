import os, time, urllib.request, urllib.error
URL = "https://www.uminho.pt/robots.txt"
PAUSE = float(os.environ.get("PAUSE", "0"))
ok = 0; erros = []; tempos = []
for i in range(200):
    t0 = time.perf_counter()
    try:
        urllib.request.urlopen(URL).read()
    except urllib.error.HTTPError as e:
        e.read()
    except Exception as e:
        erros.append((i, type(e).__name__))
        time.sleep(PAUSE)
        continue
    tempos.append((time.perf_counter() - t0) * 1000)
    ok += 1
    time.sleep(PAUSE)
print("pedidos ok:", ok, "erros:", len(erros))
print("primeiros erros (indice do pedido, tipo):", erros[:5])
if tempos:
    tempos.sort()
    print("p50 ms:", round(tempos[len(tempos)//2], 1), "p99 ms:", round(tempos[int(len(tempos)*0.99)], 1))
