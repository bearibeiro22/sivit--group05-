import argparse
import collections
import itertools
import json
import math
import os
import random
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

SENSORES = [("ECG", "FC", "bpm"), ("SpO2", "SPO2", "%"),
            ("PANI", "PAS", "mmHg"), ("TEMP", "TEMP", "C")]

PERFIS = {
    "FC":   dict(media=(75, 8, 55, 95),      theta=0.05,     std=3.5,  casas=0, lim=(20, 250)),
    "SPO2": dict(media=(97, 1, 94, 99),      theta=0.2,      std=0.5,  casas=0, lim=(50, 100)),
    "PAS":  dict(media=(120, 10, 100, 140),  theta=0.01,     std=5.0,  casas=0, lim=(40, 260)),
    "TEMP": dict(media=(36.8, 0.3, 36.0, 37.5), theta=1 / 1800, std=0.12, casas=1, lim=(30, 43)),
}

ANOMALIAS = {
    "FC":   [("taquicardia", 135, 170, 5), ("bradicardia", 30, 42, 5)],
    "SPO2": [("dessaturacao", 78, 88, 5)],
    "PAS":  [("hipertensao", 185, 220, 5), ("hipotensao", 60, 78, 5)],
    "TEMP": [("febre", 39.2, 40.5, 20)],
}

OCLUSAO = ("oclusao", 55, 80, 1.5)

T0 = time.monotonic()


def log(msg):
    print(f"[+{time.monotonic() - T0:7.1f}s] {msg}", flush=True)


class Episodio:
    __slots__ = ("nome", "artefacto", "inicio", "duracao", "rampa", "alvo")

    def __init__(self, nome, artefacto, inicio, duracao, rampa, alvo):
        self.nome, self.artefacto = nome, artefacto
        self.inicio, self.duracao, self.rampa, self.alvo = inicio, duracao, rampa, alvo

    @property
    def fim(self):
        return self.inicio + self.duracao + 2 * self.rampa

    def envelope(self, t):
        x = t - self.inicio
        if x < 0 or x > self.duracao + 2 * self.rampa:
            return 0.0
        if x < self.rampa:
            return x / self.rampa
        if x < self.rampa + self.duracao:
            return 1.0
        return 1.0 - (x - self.rampa - self.duracao) / self.rampa


class Sensor:
    def __init__(self, serie, parametro, unidade, rng, dt, args, registar):
        p = PERFIS[parametro]
        mu, sg, lo, hi = p["media"]
        self.serie, self.parametro, self.unidade = serie, parametro, unidade
        self.rng, self.p, self.registar = rng, p, registar
        self.mu = min(max(rng.gauss(mu, sg), lo), hi)
        self.x = self.mu + p["std"] * rng.gauss(0, 1)

        self.a = math.exp(-p["theta"] * dt)
        self.b = p["std"] * math.sqrt(1 - self.a * self.a)
        self.p_anom = args.anomalias / 3600.0 * dt if ANOMALIAS.get(parametro) else 0.0
        self.p_ocl = args.oclusoes / 3600.0 * dt if parametro == "SPO2" else 0.0
        self.anom_dur = args.anomalia_duracao
        self.ep = None

    def _novo_episodio(self, t, nome, lo, hi, rampa, duracao, artefacto):
        ep = Episodio(nome, artefacto, t, duracao, rampa, self.rng.uniform(lo, hi))
        self.ep = ep
        self.registar(self, ep)

    def amostra(self, t):
        r = self.rng
        self.x = self.mu + (self.x - self.mu) * self.a + self.b * r.gauss(0, 1)
        ep = self.ep
        if ep is not None and t > ep.fim:
            ep = self.ep = None
        if ep is None:
            if self.p_ocl and r.random() < self.p_ocl:
                n, lo, hi, rampa = OCLUSAO
                self._novo_episodio(t, n, lo, hi, rampa, r.uniform(4, 15), True)
            elif self.p_anom and r.random() < self.p_anom:
                n, lo, hi, rampa = r.choice(ANOMALIAS[self.parametro])
                self._novo_episodio(t, n, lo, hi, rampa,
                                    self.anom_dur * r.uniform(0.5, 1.5), False)
            ep = self.ep
        v = self.x
        if ep is not None:
            env = ep.envelope(t)
            if env > 0:
                v += (ep.alvo - v) * env + r.gauss(0, 0.005 * abs(ep.alvo))
        lo, hi = self.p["lim"]
        return round(min(max(v, lo), hi), self.p["casas"])


def criar_sensores(args, dt, registar):
    sensores = []
    for d in range(args.dispositivos):
        doente = args.primeiro + d // args.sensores
        k = d % args.sensores
        _, parametro, unidade = SENSORES[k]
        serie = f"SN-{doente:04d}-{k}"

        rng = random.Random(f"{args.semente}/{serie}")
        sensores.append(Sensor(serie, parametro, unidade, rng, dt, args, registar))
    return sensores


class Fila:

    def __init__(self, base, max_bytes):
        self.dir = os.path.join(base, "fila")
        self.rej = os.path.join(base, "rejeitados")
        os.makedirs(self.dir, exist_ok=True)
        os.makedirs(self.rej, exist_ok=True)
        self.max_bytes = max_bytes
        self.cond = threading.Condition()
        self.seq = itertools.count()
        self.nomes = collections.deque()
        self.bytes = 0
        self.descartadas = 0
        for f in sorted(os.listdir(self.dir)):
            caminho = os.path.join(self.dir, f)
            if f.endswith(".tmp"):
                os.remove(caminho)
            elif f.endswith(".json"):
                tam = os.path.getsize(caminho)
                self.nomes.append((f, tam, self._n(f)))
                self.bytes += tam
        self.herdadas = sum(n for _, _, n in self.nomes)

    @staticmethod
    def _n(nome):
        return int(nome[:-5].split("-")[2])

    def push(self, lote):
        corpo = json.dumps(lote, separators=(",", ":")).encode()
        nome = f"{time.time_ns():020d}-{next(self.seq):05d}-{len(lote)}.json"
        final = os.path.join(self.dir, nome)
        with open(final + ".tmp", "wb") as f:
            f.write(corpo)
        os.replace(final + ".tmp", final)
        apagar = []
        with self.cond:
            self.nomes.append((nome, len(corpo), len(lote)))
            self.bytes += len(corpo)
            while self.bytes > self.max_bytes and len(self.nomes) > 1:
                velho, tam, n = self.nomes.popleft()
                self.bytes -= tam
                self.descartadas += n
                apagar.append(velho)
            self.cond.notify()
        for velho in apagar:
            self._apagar(os.path.join(self.dir, velho))
        if apagar:
            log(f"AVISO buffer cheio: {len(apagar)} lote(s) mais antigo(s) descartado(s)")

    def espreitar(self, timeout):
        with self.cond:
            if not self.nomes:
                self.cond.wait(timeout)
            return self.nomes[0] if self.nomes else None

    def remover(self, nome, rejeitar=False):
        with self.cond:
            if not self.nomes or self.nomes[0][0] != nome:
                return False
            _, tam, _ = self.nomes.popleft()
            self.bytes -= tam
        origem = os.path.join(self.dir, nome)
        if rejeitar:
            os.replace(origem, os.path.join(self.rej, nome))
        else:
            self._apagar(origem)
        return True

    @staticmethod
    def _apagar(caminho):
        try:
            os.remove(caminho)
        except FileNotFoundError:
            pass

    def ler(self, nome):
        with open(os.path.join(self.dir, nome), "rb") as f:
            return f.read()

    def estado(self):
        with self.cond:
            return len(self.nomes), self.bytes, sum(n for _, _, n in self.nomes)

REPETIR = "repetir"
DEFINITIVO = "definitivo"
OK = "ok"


def enviar(url, corpo, args):
    cab = {"Content-Type": "application/json"}
    if args.token:
        cab["Authorization"] = f"Token {args.token}"
    req = urllib.request.Request(url, data=corpo, method="POST", headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as r:
            return OK, (r.status, r.read())
    except urllib.error.HTTPError as e:
        e.read()
        if e.code in (408, 425, 429) or e.code >= 500:
            return REPETIR, f"HTTP {e.code}"
        return DEFINITIVO, f"HTTP {e.code}"
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        motivo = getattr(e, "reason", e)
        return REPETIR, f"{type(motivo).__name__}: {motivo}"


def emissor(fila, args, stats, fim):
    url = args.alvo.rstrip("/") + "/v1/leituras"
    falhas, online, avisou = 0, True, False
    t_falha = 0.0
    while not fim.is_set():
        item = fila.espreitar(0.2)
        if item is None:
            continue
        nome, _, n = item
        try:
            corpo = fila.ler(nome)
        except FileNotFoundError:
            fila.remover(nome)
            continue
        resultado, detalhe = enviar(url, corpo, args)
        if resultado == OK:
            if not fila.remover(nome):
                continue
            stats["confirmadas"] += n
            stats["lotes_ok"] += 1
            stats["max_atraso_s"] = max(
                stats["max_atraso_s"], (time.time_ns() - int(nome[:20])) / 1e9)
            try:
                resp = json.loads(detalhe[1])
                stats["rejeitadas_servico"] += resp.get("rejeitadas", 0)
                stats["nao_validadas"] += resp.get("nao_validadas", 0)
                if resp.get("rejeitadas", 0) and not avisou:
                    avisou = True
                    log("AVISO a ingestao rejeitou leituras: dispositivo(s) sem internamento "
                        "ativo ou inexistente(s). Ver o seed (--dispositivos-por-internamento).")
            except (ValueError, AttributeError):
                pass
            if not online:
                online = True
                log(f"ingestao recuperada apos {time.monotonic() - t_falha:.1f}s; "
                    f"a reenviar {fila.estado()[0]} lote(s) em fila")
            falhas = 0
        elif resultado == DEFINITIVO:
            if fila.remover(nome, rejeitar=True):
                stats["rejeitadas_definitivas"] += n
                log(f"lote recusado definitivamente ({detalhe}); movido para rejeitados/")
        else:
            stats["falhas_envio"] += 1
            if online:
                online, t_falha = False, time.monotonic()
                stats["interrupcoes"] += 1
                log(f"ingestao indisponivel ({detalhe}); a guardar em disco")
            falhas += 1
            espera = random.uniform(0, min(args.backoff_max, args.backoff_base * 2 ** falhas))
            fim.wait(espera)


def parse(argv=None):
    p = argparse.ArgumentParser(description="Simulador de gateway SIVIT")
    e = os.environ.get
    p.add_argument("--alvo", default=e("ALVO", "http://localhost:8001"),
                   help="endereco base da ingestao (env ALVO)")
    p.add_argument("--dispositivos", type=int, default=80)
    p.add_argument("--sensores", type=int, default=4, choices=range(1, 5),
                   help="dispositivos por cama: 1=FC 2=+SPO2 3=+PAS 4=+TEMP")
    p.add_argument("--primeiro", type=int, default=1,
                   help="numero do primeiro doente (para correr varios gateways)")
    p.add_argument("--frequencia", type=float, default=1.0,
                   help="amostras por segundo por dispositivo (Hz)")
    p.add_argument("--duracao", type=float, default=0, help="segundos (0 = ate Ctrl+C)")
    p.add_argument("--envio", type=float, default=1.0, help="segundos entre lotes")
    p.add_argument("--lote", type=int, default=200, help="maximo de leituras por pedido")
    p.add_argument("--timeout", type=float, default=5.0, help="timeout de cada pedido (s)")
    p.add_argument("--backoff-base", type=float, default=0.5)
    p.add_argument("--backoff-max", type=float, default=10.0)
    p.add_argument("--dir", default=e("GATEWAY_DIR", "./gateway_data"),
                   help="diretorio do buffer em disco (env GATEWAY_DIR)")
    p.add_argument("--buffer-max-mb", type=float, default=200.0)
    p.add_argument("--drenar", type=float, default=30.0,
                   help="ao terminar, esperar ate N s para esvaziar a fila")
    p.add_argument("--anomalias", type=float, default=0.0,
                   help="episodios anomalos por dispositivo e por hora (0 = desligado)")
    p.add_argument("--anomalia-duracao", type=float, default=30.0,
                   help="duracao tipica do patamar de uma anomalia (s)")
    p.add_argument("--oclusoes", type=float, default=6.0,
                   help="oclusoes do sensor de SpO2 por dispositivo e por hora")
    p.add_argument("--semente", default="sivit")
    p.add_argument("--token", default=e("GATEWAY_TOKEN", ""),
                   help="Authorization: Token ... (opcional)")
    a = p.parse_args(argv)
    if not 0 < a.frequencia <= 100:
        p.error("--frequencia tem de estar em (0, 100] (chave unica = ms)")
    if a.dispositivos < 1 or a.lote < 1:
        p.error("--dispositivos e --lote tem de ser >= 1")
    return a


def main(argv=None):
    args = parse(argv)
    dt = 1.0 / args.frequencia
    fila = Fila(args.dir, int(args.buffer_max_mb * 1024 * 1024))
    stats = collections.defaultdict(int)
    stats["max_atraso_s"] = 0.0
    anomalias_log = os.path.join(args.dir, "anomalias.jsonl")
    t0_dt = datetime.now(timezone.utc)

    def registar(sensor, ep):
        stats["oclusoes" if ep.artefacto else "anomalias"] += 1
        ini = t0_dt + timedelta(seconds=ep.inicio + ep.rampa)
        linha = {"dispositivo": sensor.serie, "parametro": sensor.parametro,
                 "tipo": ep.nome, "artefacto": ep.artefacto,
                 "alvo": round(ep.alvo, 1),
                 "patamar_inicio": ini.isoformat(timespec="milliseconds"),
                 "patamar_fim": (ini + timedelta(seconds=ep.duracao)).isoformat(
                     timespec="milliseconds")}
        with open(anomalias_log, "a") as f:
            f.write(json.dumps(linha) + "\n")
        if not ep.artefacto:
            log(f"anomalia injetada: {sensor.serie} {ep.nome} -> {ep.alvo:.1f}")

    sensores = criar_sensores(args, dt, registar)
    ultimo = sensores[-1].serie
    log(f"gateway: {len(sensores)} dispositivos (SN-{args.primeiro:04d}-0 .. {ultimo}) "
        f"a {args.frequencia:g} Hz -> {args.alvo}")
    log(f"buffer em {os.path.abspath(args.dir)}; {len(fila.nomes)} lote(s) herdados "
        f"({fila.herdadas} leituras) serao reenviados primeiro")

    parar, fim_emissor, abortar = threading.Event(), threading.Event(), threading.Event()

    def sinal(*_):
        if parar.is_set():
            abortar.set()
            fim_emissor.set()
        parar.set()

    signal.signal(signal.SIGINT, sinal)
    try:
        signal.signal(signal.SIGTERM, sinal)
    except (AttributeError, ValueError):
        pass

    th = threading.Thread(target=emissor, args=(fila, args, stats, fim_emissor), daemon=True)
    th.start()

    pendentes, ultimo_instante = [], t0_dt
    t0 = time.monotonic()
    k = 0
    proximo_flush = t0 + args.envio
    proximo_estado = t0 + 5.0

    def flush():
        nonlocal pendentes
        for i in range(0, len(pendentes), args.lote):
            fila.push(pendentes[i:i + args.lote])
        pendentes = []

    while not parar.is_set():
        agora = time.monotonic()
        while t0 + k * dt <= agora:
            t = k * dt
            ultimo_instante = t0_dt + timedelta(seconds=t)
            inst = ultimo_instante.isoformat(timespec="milliseconds")
            for s in sensores:
                pendentes.append({"dispositivo": s.serie, "instante": inst,
                                  "parametro": s.parametro, "valor": s.amostra(t),
                                  "unidade": s.unidade})
            stats["geradas"] += len(sensores)
            k += 1
        if agora >= proximo_flush:
            flush()
            proximo_flush = agora + args.envio
            stats["max_fila_lotes"] = max(stats["max_fila_lotes"], fila.estado()[0])
        if agora >= proximo_estado:
            proximo_estado = agora + 5.0
            lotes, tam, leit = fila.estado()
            log(f"geradas={stats['geradas']} confirmadas={stats['confirmadas']} "
                f"em_fila={lotes} lotes/{leit} leituras ({tam / 1e6:.2f} MB)")
        if args.duracao and agora - t0 >= args.duracao:
            break
        parar.wait(max(0.0, min(t0 + k * dt, proximo_flush) - time.monotonic()))

    flush()
    stats["max_fila_lotes"] = max(stats["max_fila_lotes"], fila.estado()[0])
    decorrido = time.monotonic() - t0

    limite = time.monotonic() + args.drenar
    while fila.estado()[0] and time.monotonic() < limite and not abortar.is_set():
        time.sleep(0.1)
    fim_emissor.set()
    th.join(args.timeout + 1)

    lotes, tam, leit = fila.estado()
    if lotes:
        log(f"{lotes} lote(s) ({leit} leituras) ficam em disco; "
            f"serao reenviados no proximo arranque")
    resumo = {
        "dispositivos": len(sensores), "frequencia_hz": args.frequencia,
        "duracao_s": round(decorrido, 1),
        "inicio": t0_dt.isoformat(timespec="milliseconds"),
        "fim": ultimo_instante.isoformat(timespec="milliseconds"),
        "geradas": stats["geradas"], "herdadas": fila.herdadas,
        "confirmadas": stats["confirmadas"],
        "em_disco_lotes": lotes, "em_disco_leituras": leit,
        "descartadas_overflow": fila.descartadas,
        "rejeitadas_definitivas": stats["rejeitadas_definitivas"],
        "rejeitadas_servico": stats["rejeitadas_servico"],
        "nao_validadas": stats["nao_validadas"],
        "interrupcoes": stats["interrupcoes"], "falhas_envio": stats["falhas_envio"],
        "max_fila_lotes": stats["max_fila_lotes"],
        "max_atraso_s": round(stats["max_atraso_s"], 1),
        "anomalias": stats["anomalias"], "oclusoes": stats["oclusoes"],
    }
    print(json.dumps(resumo), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())