import argparse
import json
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import httpx


class Device:
    """Gera sinais vitais plausiveis para um monitor."""

    def __init__(self, serial, anomaly_rate):
        self.serial = serial
        self.anomaly_rate = anomaly_rate
        self.hr = random.uniform(60, 90)
        self.temp = random.uniform(36.3, 37.0)
        self.occlusion_left = 0

    def step(self):
        # HR: passeio aleatorio em torno de 75 bpm, mais ruido de medida
        self.hr += random.gauss(0, 1.5) + (75 - self.hr) * 0.02
        hr = self.hr + random.gauss(0, 1.0)

        # SpO2: ~97.5%, com oclusoes ocasionais (queda durante alguns segundos)
        if self.occlusion_left > 0:
            self.occlusion_left -= 1
            spo2 = random.uniform(80, 88)
        elif random.random() < 0.01:
            self.occlusion_left = random.randint(3, 8)
            spo2 = random.uniform(80, 88)
        else:
            spo2 = min(100.0, random.gauss(97.5, 0.6))

        # TEMP: deriva lenta
        self.temp = min(39.0, max(35.0, self.temp + random.gauss(0, 0.01)))
        temp = self.temp

        # Anomalias opcionais, para testar alarmes
        if random.random() < self.anomaly_rate:
            which = random.choice(["HR", "SPO2", "TEMP"])
            if which == "HR":
                hr = random.choice([random.uniform(20, 35), random.uniform(200, 240)])
            elif which == "SPO2":
                spo2 = random.uniform(55, 70)
            else:
                temp = random.uniform(40, 42)

        return [("HR", hr, "bpm"), ("SPO2", spo2, "%"), ("TEMP", temp, "C")]


class Buffer:
    """Buffer persistente em disco (SQLite)."""

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS buffer "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)"
        )
        self.db.commit()

    def add(self, readings):
        self.db.executemany(
            "INSERT INTO buffer (payload) VALUES (?)",
            [(json.dumps(r),) for r in readings],
        )
        self.db.commit()

    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM buffer").fetchone()[0]

    def oldest(self, n):
        return self.db.execute(
            "SELECT id, payload FROM buffer ORDER BY id LIMIT ?", (n,)
        ).fetchall()

    def delete(self, ids):
        self.db.executemany("DELETE FROM buffer WHERE id = ?", [(i,) for i in ids])
        self.db.commit()


def post(client, url, readings):
    """'ok' se aceite; 'retry' se indisponivel (rede ou 5xx); 'drop' se rejeitado (4xx)."""
    try:
        r = client.post(url, json=readings)
    except httpx.HTTPError:
        return "retry"
    if r.status_code < 300:
        return "ok"
    if r.status_code >= 500:
        return "retry"
    return "drop"


def flush(client, url, buf, chunk=500):
    """Reenvia o buffer, do mais antigo para o mais recente. Devolve quantas foram repostas."""
    total = 0
    while True:
        rows = buf.oldest(chunk)
        if not rows:
            return total
        result = post(client, url, [json.loads(p) for _, p in rows])
        if result == "retry":
            return total
        buf.delete([i for i, _ in rows])  # aceite ou rejeitado de vez
        if result == "ok":
            total += len(rows)


def main():
    ap = argparse.ArgumentParser(description="Simulador de gateway de monitores")
    ap.add_argument("--devices", type=int, default=5)
    ap.add_argument("--hz", type=float, default=1.0, help="leituras por segundo, por dispositivo")
    ap.add_argument("--url", default="http://ingestion:8000/v1/readings")
    ap.add_argument("--buffer", default="/data/buffer.db")
    ap.add_argument("--anomaly-rate", type=float, default=0.0)
    ap.add_argument("--duration", type=float, default=0, help="segundos (0 = ate Ctrl+C)")
    args = ap.parse_args()

    devices = [Device(f"SIM-{i + 1:03d}", args.anomaly_rate) for i in range(args.devices)]
    buf = Buffer(args.buffer)
    client = httpx.Client(timeout=1.0)
    period = 1.0 / args.hz
    n_ticks = int(args.duration * args.hz) if args.duration else None
    retry_every = 2.0  # com a ingestao em baixo, so volta a tentar passado este tempo
    next_try = 0.0
    generated = sent = replayed = buffered = dropped = 0

    print(f"gateway: {args.devices} dispositivos a {args.hz} Hz -> {args.url}", flush=True)
    print(f"buffer: {buf.count()} leituras pendentes de execucoes anteriores", flush=True)

    start = time.monotonic()
    wall_start = datetime.now(timezone.utc)
    last_log = start
    i = 0
    try:
        while n_ticks is None or i < n_ticks:
            # a amostragem segue o relogio, independentemente do estado da rede
            instant = (wall_start + timedelta(seconds=i * period)).isoformat()
            readings = [
                {"device": d.serial, "instant": instant, "parameter": p,
                 "value": round(v, 2), "unit": u}
                for d in devices for p, v, u in d.step()
            ]
            generated += len(readings)

            if time.monotonic() >= next_try:
                # 1. despejar o que ficou em atraso (mais antigo primeiro)
                if buf.count() > 0:
                    replayed += flush(client, args.url, buf)
                # 2. enviar o instante atual, ou guardar se ainda ha atraso
                if buf.count() == 0:
                    result = post(client, args.url, readings)
                    if result == "ok":
                        sent += len(readings)
                    elif result == "retry":
                        buf.add(readings)
                        buffered += len(readings)
                        next_try = time.monotonic() + retry_every
                    else:
                        dropped += len(readings)
                else:
                    buf.add(readings)
                    buffered += len(readings)
                    next_try = time.monotonic() + retry_every
            else:
                buf.add(readings)
                buffered += len(readings)

            if time.monotonic() - last_log >= 5:
                last_log = time.monotonic()
                print(f"geradas={generated} enviadas={sent} repostas={replayed} "
                      f"em_buffer={buf.count()} descartadas={dropped}", flush=True)

            i += 1
            delay = start + i * period - time.monotonic()
            if delay > 0:
                time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        print(f"FIM: geradas={generated} enviadas={sent} repostas={replayed} "
              f"guardadas={buffered} em_buffer={buf.count()} descartadas={dropped}", flush=True)


if __name__ == "__main__":
    main()
