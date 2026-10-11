import collections, socket, urllib.request

NOME = "echo"
URL = f"http://{NOME}:8000/"

# 1. Para que IPs e que o nome "echo" resolve? (DNS interno do Docker)
ips = sorted({a[4][0] for a in socket.getaddrinfo(NOME, 8000, proto=socket.IPPROTO_TCP)})
print(f"O nome '{NOME}' resolve para {len(ips)} IP(s): {', '.join(ips)}")

# 2. Quem responde? 30 pedidos, sempre ao mesmo nome
contagem = collections.Counter()
for _ in range(30):
    resposta = urllib.request.urlopen(URL).read().decode()
    contentor = resposta.split(" on ")[1].split(" at ")[0]
    contagem[contentor] += 1
print("Pedidos atendidos por cada contentor:")
for contentor, n in sorted(contagem.items()):
    print(f"  {contentor}: {n}")
