import time, statistics, urllib.request

def measure(url, n=200):
    s = []
    for _ in range(n):
        t0 = time.perf_counter()
        urllib.request.urlopen(url).read()
        s.append((time.perf_counter() - t0) * 1000)
    s.sort()
    return {
        "p50": s[len(s)//2],
        "p95": s[int(len(s)*0.95)],
        "p99": s[int(len(s)*0.99)],
        "max": s[-1]
    }

if __name__ == "__main__":
    # 1. Local function call
    def dummy_fn(): pass
    s_fn = []
    for _ in range(200):
        t0 = time.perf_counter()
        dummy_fn()
        s_fn.append((time.perf_counter() - t0) * 1000)
    s_fn.sort()
    print("Local function call:", {
        "p50": s_fn[100], "p95": s_fn[190], "p99": s_fn[198], "max": s_fn[-1]
    })

    # 2. HTTP between containers
    print("HTTP between containers:", measure("http://echo:8000/"))

    # 3. HTTP to UMinho server
    print("HTTP to UMinho:", measure("https://www.uminho.pt"))

    # 4. HTTP to USA server
    print("HTTP to USA:", measure("https://www.google.com"))