import os, time, urllib.request, urllib.error

PAUSE = float(os.environ.get("PAUSE", "0"))
N = 200

def pct(s, p):
    return s[min(int(len(s) * p), len(s) - 1)]

def summarize(s):
    s = sorted(s)
    return {"p50": round(pct(s, 0.50), 3), "p95": round(pct(s, 0.95), 3),
            "p99": round(pct(s, 0.99), 3), "max": round(s[-1], 3)}

def measure(url, n=N):
    tempos, erros = [], 0
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            urllib.request.urlopen(url, timeout=10).read()
        except urllib.error.HTTPError as e:
            e.read()  # resposta HTTP recebida: conta
        except Exception:
            erros += 1  # falha de rede: nao entra nos percentis
            time.sleep(PAUSE)
            continue
        tempos.append((time.perf_counter() - t0) * 1000)
        time.sleep(PAUSE)
    return summarize(tempos), erros

def dummy_fn():
    pass

if __name__ == "__main__":
    s = []
    for _ in range(N):
        t0 = time.perf_counter()
        dummy_fn()
        s.append((time.perf_counter() - t0) * 1000)
    print("Local function call:", summarize(s))

    for nome, url in [
        ("HTTP between containers", "http://echo:8000/"),
        ("HTTP to UMinho", "https://www.uminho.pt/robots.txt"),
        ("HTTP to USA", "https://dynamodb.us-east-1.amazonaws.com/"),
    ]:
        r, erros = measure(url)
        print(f"{nome}: {r} | erros: {erros}")
