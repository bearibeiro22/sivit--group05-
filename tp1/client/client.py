import os, sys, time, urllib.request


def percentiles(s):
    s = sorted(s)
    return {"p50": s[len(s) // 2],
            "p95": s[int(len(s) * 0.95)],
            "p99": s[int(len(s) * 0.99)],
            "max": s[-1]}


def measure(url, n=200):
    s = []
    hosts = set()
    for _ in range(n):
        t0 = time.perf_counter()
        body = urllib.request.urlopen(url).read().decode(errors="ignore")
        s.append((time.perf_counter() - t0) * 1000)
        if len(body) < 200 and " on " in body and " at " in body:
            hosts.add(body.split(" on ")[1].split(" at ")[0])
    return percentiles(s), hosts


def measure_local(n=200000):
    def f():
        return 1
    s = []
    for _ in range(n):
        t0 = time.perf_counter()
        f()
        s.append((time.perf_counter() - t0) * 1000)
    return percentiles(s)


def wait_for(url, tries=30):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return
        except Exception:
            time.sleep(1)
    sys.exit(url + " nao respondeu")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TARGET_URL", "http://echo:8000/")
    n = int(os.environ.get("N", "200"))
    if target == "local":
        r = measure_local()
        hosts = set()
    else:
        wait_for(target)
        r, hosts = measure(target, n)
    print(target + "  " + "  ".join(f"{k}={v:.4f} ms" for k, v in r.items()))
    if hosts:
        print("respondentes distintos:", len(hosts), sorted(hosts))
