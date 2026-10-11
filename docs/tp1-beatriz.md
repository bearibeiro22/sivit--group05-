# TP1 · Respostas de Beatriz

Plataforma: Windows com Docker Desktop (backend WSL2), comandos corridos no Ubuntu do WSL.
Como os contentores correm na zona do Docker Desktop e não no Ubuntu, para ver o "host"
usei um contentor auxiliar com `--pid=host` (e `--privileged` para ler `/proc/<pid>/ns/`).

## Exercício 1 · Um contentor não é uma máquina

### 1. Os processos do nginx aparecem na lista de processos do host?

Sim. Visto do host (`docker run --rm --pid=host alpine ps`), o nginx aparece como processos
normais: um master com PID 753 e 8 workers (PIDs 796 a 803). Um contentor não é uma máquina
virtual com sistema operativo próprio: é um conjunto de processos comuns, a correr diretamente
no kernel do host. No Windows, o `ps aux` dentro do Ubuntu do WSL não mostra o nginx, porque
o Ubuntu e o Docker Desktop estão em namespaces de processos diferentes.

### 2. Que namespaces aparecem em /proc/<pid>/ns/? O que isola cada um?

Aparecem `cgroup`, `ipc`, `mnt`, `net`, `pid`, `time`, `user` e `uts`.

- `pid`: a lista de processos (o contentor numera os seus a partir do 1).
- `net`: a rede (interfaces, IP, portas).
- `mnt`: o sistema de ficheiros (o contentor vê a árvore da sua imagem).
- `uts`: o hostname.
- `ipc`: a comunicação entre processos por memória partilhada e filas de mensagens.
- `cgroup`: a vista da hierarquia de cgroups.
- `user`: os utilizadores e grupos (UIDs).
- `time`: os relógios do sistema.

Comparando com o processo 1 do host (numa nova sessão, com o nginx no PID 539), todos os
namespaces têm identificadores diferentes exceto o `user`, que é o mesmo nos dois
(4026531837). O contentor tem processos, rede, ficheiros, hostname, IPC, vista de cgroups e
relógios próprios, mas partilha os utilizadores com o host: o `root` do contentor é o mesmo
`root` de fora.

### 3. Porque é que `docker exec web ps aux` e `ps aux` no host diferem?

Dentro do contentor só aparecem os processos do nginx: o master tem PID 1 e os workers
PIDs 30 a 37. No host, os mesmos processos têm PIDs 753 e 796 a 803, misturados com todos os
outros. A diferença deve-se ao namespace de PIDs: o contentor tem a sua própria numeração e
não vê os processos de fora. O utilizador dos workers aparece como `nginx` dentro e `101`
fora: o UID é o mesmo, mas o nome é lido do `/etc/passwd` do contentor (namespace `mnt`).

### 4. O que aconteceu no teste de memória? Que mecanismo do kernel o causou?

O Python foi terminado à força: o comando saiu com o código 137, que corresponde a 128 + 9,
ou seja, ao sinal `SIGKILL`. O mecanismo são os cgroups: o `--memory=64m` limitou a memória
do contentor a 64 MB e, quando o Python tentou alocar 200 MB, o OOM killer do kernel matou o
processo. O `--cpus=0.5` também usa cgroups, mas limita o tempo de CPU e não mata o processo,
apenas o abranda.

**Conclusão:** um contentor é um processo normal + namespaces (o que vê) + cgroups (o que
pode consumir).

## Exercício 2 · A primeira imagem
respostas obtidas no terminal:
$ curl localhost:8000 echo1 on 3381f08e3df9 at 1791237053.854
$ curl localhost:8000 echo2 on a8b5fcc8ae3d at 1791237104.856
O serviço é stateless: não guarda nenhum estado entre pedidos (nem base de dados, nem
ficheiros, nem dados em memória), e cada resposta depende só do pedido e do contentor que a dá. Por isso, as duas réplicas, criadas a partir da mesma imagem, são intercambiáveis: diferem
apenas no nome (variável de ambiente `SERVICE_NAME`) e na porta do host (8000 e 8001), e
qualquer uma pode responder a qualquer pedido. Os hostnames diferentes (`3381f08e3df9` e `a8b5fcc8ae3d`) confirmam que são contentores distintos da mesma imagem. Ambos escutam na
porta 8000 interna sem conflito, porque cada contentor tem o seu próprio namespace de rede.
Se o serviço guardasse estado, cada réplica teria uma versão diferente dos dados e seria
preciso sincronizá-las, o que tornaria a replicação muito mais difícil.

## Exercício 4 · Medir a falácia n.º 2

Plataforma: Windows com Docker Desktop (backend WSL2). O `localhost` foi medido a partir do
Ubuntu do WSL e os restantes contextos a partir de um contentor (`beatriz/client/main.py`),
com 200 pedidos por contexto e uma ligação nova em cada pedido. Para os EUA usei
`dynamodb.us-east-1.amazonaws.com` (AWS, Virgínia), que não passa por uma CDN: o
`google.com` responderia a partir de um servidor na Europa.

| Contexto | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) | falhas |
| --- | --- | --- | --- | --- | --- |
| Local function call | 0.0001 | 0.0001 | 0.0005 | 0.0006 | 0/200 |
| HTTP to localhost | 1.7476 | 3.5678 | 4.4802 | 18.5459 | 0/200 |
| HTTP between containers | 1.2156 | 1.6792 | 2.3373 | 2.4261 | 0/200 |
| HTTP to a UMinho server | 559.8181 | 727.3719 | 1406.3792 | 1529.1993 | 65/200 |
| HTTP to a server in the USA | 326.5055 | 351.4427 | 379.2387 | 413.1623 | 0/200 |

Os percentis da UMinho foram calculados só com as 135 respostas que chegaram.

**Nota sobre a plataforma:** o `localhost` (p50 1.75 ms) foi mais lento do que a ligação
entre contentores (p50 1.22 ms). No Windows, um pedido do Ubuntu para `localhost:8000`
tem de passar pelo reencaminhamento de portas do Docker Desktop até à VM onde o contentor
corre. Entre contentores, o pedido fica dentro da rede virtual do Docker, na mesma VM.

### 1. Quantas ordens de grandeza separam a chamada local da intercontinental?

Cerca de 6 a 7. O p50 da chamada local é 0.0001 ms e o p50 para os EUA é 326.5 ms:
326.5 / 0.0001 ≈ 3.3 × 10⁶, ou seja, cerca de 6,5 ordens de grandeza. O valor local está
perto da resolução do relógio, por isso a razão é aproximada. Mesmo a chamada entre dois
contentores na mesma máquina (1.22 ms) já fica 4 ordens de grandeza acima da chamada local.

Os 326 ms explicam-se pela distância: cada pedido abre uma ligação nova, o que obriga a
cerca de 3 idas e voltas através do Atlântico (ligação TCP, negociação TLS e o pedido HTTP
em si). Cada ida e volta demora na ordem dos 100 ms.

### 2. Porque é que o p99 é tão maior do que o p50, mesmo entre contentores na mesma máquina?

Entre contentores, o p99 (2.34 ms) é quase o dobro do p50 (1.22 ms). No `localhost`, o p99
(4.48 ms) é 2.6 vezes o p50 (1.75 ms) e o máximo (18.5 ms) é mais de 10 vezes. A maioria dos
pedidos segue o caminho normal, mas alguns apanham um atraso raro: o processo perde o CPU
para outro processo (escalonamento e trocas de contexto), o garbage collector do Python
corre a meio do pedido, a VM do WSL2 é interrompida pelo Windows, ou a rede virtual do
Docker atrasa um pacote. São eventos pouco frequentes, por isso quase não mexem na mediana,
mas dominam a cauda. Com 200 amostras, o p99 corresponde ao 3.º pior valor: bastam 2 ou 3
pedidos azarados para o fazer subir.

Para os EUA, a cauda é proporcionalmente mais pequena (p99 / p50 ≈ 1.16): o tempo de
propagação é grande e constante, e as perturbações de alguns milissegundos ficam diluídas.

### 3. 30 chamadas remotas em sequência, cada uma com p95 = 4 ms. Qual é o p95 do pedido? E em paralelo?

**Em sequência**, as latências somam-se. A estimativa conservadora é 30 × 4 ms = 120 ms.
Mais importante ainda: a probabilidade de as 30 chamadas ficarem todas abaixo do seu p95 é
0.95³⁰ ≈ 21%. Isto quer dizer que cerca de 79% dos pedidos apanham pelo menos uma chamada
lenta, e o que era a cauda de uma chamada passa a ser o caso normal do pedido.

**Em paralelo**, o pedido demora o tempo da chamada mais lenta. Para o total ficar abaixo
de um valor X em 95% dos casos, cada chamada tem de ficar abaixo de X com probabilidade
0.95^(1/30) ≈ 99.83%. Ou seja, o p95 do pedido é o p99.8 de uma chamada individual. Fica
muito abaixo dos 120 ms, mas bem acima de 4 ms: paralelizar elimina a soma, mas não a
cauda. É o "efeito N+1" que aparece na TP2 dentro do ORM do Django.

### 4. Que falácias é que os números refutam?

- **Falácia n.º 2, "a latência é zero":** é a principal. A mesma operação passa de
  0.0001 ms (chamada local) para 1.2 ms (entre contentores), 1.7 ms (`localhost`) e
  326 ms (EUA): mais de 6 ordens de grandeza. Um desenho que trata uma chamada remota como
  uma chamada local fica milhões de vezes mais lento.
- **Falácia n.º 1, "a rede é fiável":** 65 dos 200 pedidos à UMinho (32.5%) falharam,
  contra 0 falhas nas chamadas locais. As falhas foram rápidas (não foram timeouts), o que
  indica que foi o servidor a recusar ou a falhar os pedidos e não a rede em si. Mesmo
  assim, do lado de quem chama, uma chamada remota pode falhar e uma chamada local não.
- **Falácia n.º 8, "a rede é homogénea":** o `localhost` foi mais lento do que a ligação
  entre contentores, por causa do salto extra pela VM do Docker Desktop no Windows. O
  mesmo pedido tem latências diferentes consoante o caminho e a plataforma.

Os números também mostram que a latência não depende só da distância: a UMinho (p50
560 ms), que está perto, foi mais lenta do que os EUA (p50 326 ms). A página da UMinho é
uma página HTML completa, gerada pelo servidor em cada pedido, enquanto o endpoint da AWS
devolve uma resposta curta. O tempo do servidor e o tamanho da resposta também contam.
