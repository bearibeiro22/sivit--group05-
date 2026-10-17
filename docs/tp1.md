# TP1: Environment, Git and Containers

**Plataforma:** Windows com Docker Desktop (VM Linux/WSL2)

## Exercício 1: um container não é uma máquina

1. Sim, os processos do nginx aparecem na lista de processos do host (VM):
   master com PID 3647 e workers 3690-3697. Um container é um processo
   normal do kernel anfitrião com uma vista restrita do sistema, não uma máquina.
2. Namespaces observados em /proc/<pid>/ns/:
   - pid: árvore de processos e PIDs visíveis
   - net: interfaces de rede, IPs, rotas e portas
   - mnt: pontos de montagem e sistema de ficheiros visível
   - uts: hostname e domain name
   - ipc: memória partilhada e filas de mensagens
   - cgroup: vista da hierarquia de cgroups
   - time: relógios boottime e monotonic
   - user: mapeamento de UIDs/GIDs (aqui é o namespace inicial do host,
     logo o Docker não isola utilizadores por omissão)
3. O namespace pid dá ao container a sua numeração: o master é PID 1 lá dentro
   e 3647 no host. Dentro só se vê o nginx; o host vê tudo.
4. O processo foi terminado com código 137 (SIGKILL) pelo OOM killer, porque o
   cgroup do container excedeu o limite de 64 MB. Namespaces limitam o que o
   processo vê; cgroups limitam o que pode consumir.

## Exercício 2: a primeira imagem

Imagem `sivit/echo:0.1` construída e duas réplicas a correr (`echo1` na porta 8000
e `echo2` na porta 8001), com hostnames diferentes e respostas equivalentes.

**Que propriedade tornou a replicação trivial?** O serviço é stateless: não guarda
estado entre pedidos, a resposta depende só do pedido e do ambiente. Qualquer réplica
pode servir qualquer pedido, sem coordenação nem dados partilhados, por isso
replicar é só lançar mais um container da mesma imagem.

## Exercício 3: compose e naming

O cliente aponta para `http://echo:8000/` (um nome, não um IP). Com
`docker compose up --scale echo=3` o mesmo nome resolveu para 3 containers
distintos (3 respondentes diferentes), p50 = 1,40 ms.

## Exercício 4: medir a falácia #2

**Plataforma:** Windows com Docker Desktop (WSL2).

| Contexto | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| Chamada local de função | 0,0001 | 0,0002 | 0,0002 |
| HTTP para localhost | 3,07 | 4,88 | 9,10 |
| HTTP entre containers (1 réplica) | 1,39 | 2,95 | 6,76 |
| HTTP para servidor da UMinho (www.di.uminho.pt, RTT 14 ms) | 147,15 | 186,28 | 189,71 |
| HTTP para servidor nos EUA (www.cs.cmu.edu, RTT 110 ms) | 621,89 | 732,11 | 1530,59 |

Notas: 200 pedidos nas medições locais e entre containers, 50 nos servidores remotos
(o p99 coincide com o máximo). Cada pedido abre uma ligação nova, por isso os tempos
remotos incluem handshake TCP e TLS. O localhost é mais lento que entre containers
por causa do reencaminhamento de portas do Docker Desktop para a VM.

1. A razão entre a chamada local e a intercontinental é ~6,2 milhões, quase 7 ordens
   de grandeza (o valor local está no limite da resolução do relógio).
2. O p99 é ~5x o p50 mesmo entre containers: ligação TCP nova por pedido, servidor
   single-thread, competição por CPU com o Windows e a VM, e com 200 amostras o p99
   é quase o segundo pior pedido.
3. Sequencial: ~30 x 4 = 120 ms (ordem de grandeza, cresce linearmente com N).
   Paralelo: o pedido demora o máximo das 30 chamadas; P(todas < p95) = 0,95^30
   = 21,5%, e o p95 do pedido corresponde ao p99,8 de uma chamada. Muito menos
   que 120 ms mas acima de 4 ms (amplificação da cauda).
4. Refutam a falácia #2 (latência zero): 0,0001 ms, 3 ms, 147 ms e 622 ms para a
   mesma operação. Também contrariam a #8 (rede homogénea), pois localhost é mais
   lento que entre containers, e a #7, pois cada pedido paga TCP e TLS.
