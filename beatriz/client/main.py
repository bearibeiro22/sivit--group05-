import sys, time, urllib.request

N = 200
UA = {"User-Agent": "Mozilla/5.0 (sivit-group05 latency test)"}

def stats(s):
    s.sort()
    return {"p50": s[len(s)//2], "p95": s[int(len(s)*0.95)],
            "p99": s[int(len(s)*0.99)], "max": s[-1]}

def measure(url, n=N):
    s, erros = [], 0
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=10).read()
            s.append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            erros += 1
            ultimo = e
    if not s:
        print(f"  {url}: todos os pedidos falharam ({ultimo})")
        return None, erros
    return stats(s), erros

def local_call(n=N):
    def f(): pass
    s = []
    for _ in range(n):
        t0 = time.perf_counter(); f(); s.append((time.perf_counter() - t0) * 1000)
    return stats(s), 0

def esperar(url, tentativas=30):
    for _ in range(tentativas):
        try:
            urllib.request.urlopen(url, timeout=2).read(); return
        except Exception:
            time.sleep(1)

def linha(nome, res):
    r, erros = res
    if r is None:
        return f"| {nome} | N/A | N/A | N/A | N/A | {erros}/{N} |"
    return (f"| {nome} | {r['p50']:.4f} | {r['p95']:.4f} | {r['p99']:.4f} "
            f"| {r['max']:.4f} | {erros}/{N} |")

if __name__ == "__main__":
    print("| Contexto | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) | falhas |")
    print("| --- | --- | --- | --- | --- | --- |")
    if len(sys.argv) > 1 and sys.argv[1] == "localhost":
        print(linha("HTTP to localhost", measure("http://localhost:8000/")))
    else:
        esperar("http://echo:8000/")
        print(linha("Local function call", local_call()), flush=True)
        print(linha("HTTP between containers", measure("http://echo:8000/")), flush=True)
        print(linha("HTTP to a UMinho server", measure("https://www.uminho.pt/")), flush=True)
        print(linha("HTTP to a server in the USA", measure("https://dynamodb.us-east-1.amazonaws.com/")), flush=True)
