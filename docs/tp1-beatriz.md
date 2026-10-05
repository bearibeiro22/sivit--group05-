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

(a fazer)
