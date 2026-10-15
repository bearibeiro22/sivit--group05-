import json, time, urllib.request, urllib.error

URL = "http://localhost:8080/api/v1/readings/"
batch = open("batch.json", "rb").read()

for attempt in range(1, 11):
    req = urllib.request.Request(URL, data=batch, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            print(f"Tentativa {attempt}: OK {r.status} {r.read().decode()}")
            break
    except urllib.error.HTTPError as e:
        print(f"Tentativa {attempt}: erro {e.code} (resposta perdida), a repetir...")
    except Exception as e:
        print(f"Tentativa {attempt}: {e}, a repetir...")
    time.sleep(0.3)
