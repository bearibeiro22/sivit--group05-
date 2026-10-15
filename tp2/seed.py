import json
import urllib.error
import urllib.request

BASE = "http://localhost:8080/api/v1"


def call(method, path, data=None):
    req = urllib.request.Request(
        f"{BASE}/{path}/",
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print("ERRO", e.code, path, e.read().decode())
        raise SystemExit(1)


patients = call("GET", "patients")
p = next((x for x in patients if x["code"] == "P001"), None) or call(
    "POST", "patients",
    {"code": "P001", "name": "Ana Teste", "birth_date": "1980-05-10"})

devices = call("GET", "devices")
d = next((x for x in devices if x["serial"] == "DEV-001"), None)
if d is None:
    a = call("POST", "admissions", {
        "patient": p["id"], "ward": "UCI", "bed": "3",
        "admitted_at": "2026-10-15T08:00:00Z"})
    call("POST", "devices", {"serial": "DEV-001", "type": "SpO2",
                             "admission": a["id"]})

batch = [{"device": "DEV-001", "instant": f"2026-10-15T10:00:{i:02d}Z",
          "parameter": "HR", "value": 70 + i, "unit": "bpm"} for i in range(10)]
json.dump(batch, open("batch.json", "w"), indent=2)

bad = [{"device": "DEV-001", "instant": "2026-10-15T11:00:00Z",
        "parameter": "HR", "value": 300, "unit": "bpm"}]
json.dump(bad, open("bad.json", "w"), indent=2)
print("ok")