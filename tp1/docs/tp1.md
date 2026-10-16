# TP1 - Ambiente, Git e Contentores

Aplicações Distribuídas · MEB-IM · Universidade do Minho

**Plataforma:** Docker Desktop no Windows. Os contentores correm numa VM Linux gerida pelo Docker Desktop, por isso o "host" dos comandos `ps` e `/proc` é essa VM e não o Windows.

## 1. Exercício 1 - Um contentor não é uma máquina

**Montagem.** `docker run -d --name web -p 8080:80 nginx:alpine`. Para ver o "host", usei contentores com `--pid=host` (e `--privileged` para ler `/proc/<pid>/ns/`), que partilham o espaço de processos da VM Linux.

**1. Os processos nginx aparecem na lista de processos do host? O que diz isso sobre o que é um contentor?**

Aparecem. Na lista de processos da VM Linux vê-se o processo mestre (PID 446) e oito workers (PIDs 489 a 496). No Windows, o `Get-Process` não devolveu nenhum nginx, porque o kernel que os executa é o da VM e não o do Windows.

São processos normais do kernel do host, escalonados por ele como quaisquer outros. Um contentor não é uma máquina virtual: não tem kernel próprio nem hardware emulado. É um processo (ou uma árvore de processos) isolado por namespaces e limitado por cgroups.

**2. Que namespaces aparecem em `/proc/<pid>/ns/`? O que isola cada um?**

Em `/proc/446/ns/` aparecem `cgroup`, `ipc`, `mnt`, `net`, `pid`, `time`, `user` e `uts`, mais `pid_for_children` e `time_for_children`, que indicam o namespace herdado pelos processos filhos.

| Namespace | O que isola |
|---|---|
| mnt | os pontos de montagem: o sistema de ficheiros que o processo vê (o contentor tem a sua própria raiz) |
| pid | a numeração e a visibilidade dos processos (o nginx mestre é o PID 1 lá dentro) |
| net | interfaces de rede, endereços IP, tabela de rotas e portas |
| ipc | memória partilhada, semáforos e filas de mensagens |
| uts | o nome da máquina (hostname) |
| cgroup | a vista da hierarquia de cgroups |
| time | os desvios dos relógios do sistema |
| user | o mapeamento de UIDs e GIDs |

Observação: o namespace `user` do nginx (4026531837) é o namespace inicial do sistema, ou seja, por omissão o Docker não o isola: o root do contentor é o root da VM, apenas com capacidades reduzidas. Os outros sete namespaces (4026532378 a 4026532383 e 4026532451) são próprios do contentor.

**3. Compare `docker exec web ps aux` com `ps aux` no host. Porque diferem?**

Dentro do contentor, `ps aux` mostra apenas 10 processos: o nginx mestre com PID 1, os oito workers (PIDs 30 a 37) e o próprio `ps` (PID 38). No host (a VM), `ps aux` mostra todos os processos da máquina, e os mesmos processos nginx aparecem com outros PIDs: o mestre com 446 e os workers com 489 a 496.

São os mesmos processos vistos através de dois namespaces de PID diferentes. O contentor tem o seu próprio espaço de PIDs, que começa em 1, e só vê os processos criados lá dentro. O host usa o espaço global e vê tudo. Há ainda uma diferença nos nomes: os workers correm com o UID 101, que dentro do contentor aparece como `nginx` (o `/etc/passwd` do contentor, isolado pelo namespace `mnt`, tem esse nome) e visto de fora aparece só o número 101.

**4. O que aconteceu na experiência dos recursos? Que mecanismo do kernel a causou?**

O contentor foi terminado sem qualquer mensagem de erro do Python, com código de saída 137 (128 + 9, isto é, SIGKILL). O programa tentou reservar 200 MiB com um limite de 64 MiB (`--memory=64m`), e o OOM killer do kernel matou o processo.

O mecanismo são os cgroups, mais precisamente o controlador de memória: o Docker coloca o processo num cgroup com um limite de memória e, quando o consumo o ultrapassa, o kernel mata o processo em vez de deixar o contentor consumir a memória do host. A opção `--cpus=0.5` usa o controlador de CPU (limita o tempo de CPU a meio núcleo), mas não teve influência neste resultado.

Em resumo: um contentor é um processo normal, com namespaces (o que vê) e cgroups (o que pode consumir).

## 2. Exercício 4 - Medir a falácia #2

**Plataforma:** Docker Desktop no Windows (VM Linux). 200 pedidos por linha, pausa de 0,3 s entre pedidos (fora da medição) e ligação nova em cada pedido, pelo que os pedidos HTTPS incluem DNS, TCP e TLS.

| Contexto | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| Local function call | < 0,001 | < 0,001 | 0,001 |
| HTTP to localhost | 4,3 | 7,0 | 19,6 |
| HTTP between containers | 3,6 | 4,3 | 5,0 |
| HTTP to a UMinho server | 167,3 | 206,1 | 382,2 |
| HTTP to a server in the USA | 319,2 | 343,4 | 488,9 |

Servidores usados: `https://www.uminho.pt/robots.txt` e `https://dynamodb.us-east-1.amazonaws.com/` (Virgínia, EUA). Máximos observados: 0,046 / 43,8 / 538,9 / 571,7 ms (função, contentores, UMinho, EUA).

**Nota sobre localhost.** O pedido a localhost (feito a partir do Windows) foi mais lento do que o pedido entre contentores, porque atravessa o encaminhamento de portas do Docker Desktop para a VM Linux, enquanto entre contentores o tráfego fica dentro da VM. Em Linux nativo esta diferença não existiria.

**Nota sobre erros.** Numa primeira execução sem pausa, 2 de 200 pedidos ao UMinho falharam com `URLError` (índices 76 e 139). Com 0,3 s de pausa, as execuções finais tiveram 0 erros. As falhas são excluídas dos percentis e a pausa não entra no tempo medido.

**1. Quantas ordens de magnitude separam a chamada local da intercontinental?**

Uma chamada de função custa da ordem de 10^-5 ms (dezenas de nanossegundos). O p50 para os EUA é 319 ms, ou seja, cerca de 10^2,5 ms. A diferença é de aproximadamente **6 a 7 ordens de magnitude**. Mesmo entre contentores na mesma máquina (3,6 ms) há já cerca de 5 ordens de diferença em relação à função local. Sair do processo tem sempre um custo enorme, mesmo sem sair da máquina.

**2. Porque é que o p99 é tão superior ao p50, mesmo entre contentores?**

Entre contentores, o p50 é 3,6 ms e o p99 é 5,0 ms, mas o máximo chega a 43,8 ms, cerca de 12 vezes a mediana. O caminho de um pedido atravessa muitas camadas partilhadas, e qualquer uma pode introduzir um atraso ocasional:

- o escalonador do kernel (a VM do Docker Desktop partilha CPU com o Windows e com os outros processos);
- a rede virtual (bridge, NAT) e a pilha TCP, com uma ligação nova em cada pedido;
- o garbage collector do Python e o `HTTPServer` de uma só thread, que atende um pedido de cada vez.

A média esconde estes picos raros, que são exatamente o que o p99 mostra. Nas linhas remotas a cauda é maior ainda, porque se somam a internet, as filas dos routers e a carga do servidor: no UMinho o p99 (382 ms) é mais do dobro do p50 (167 ms).

**3. 30 chamadas sequenciais com p95 = 4 ms cada: qual é o p95 do pedido? E em paralelo?**

- **Sequencial:** o tempo é a soma das 30 latências, cerca de 30 x 4 = **120 ms** (um limite superior; com latências independentes o p95 da soma é um pouco inferior, porque é raro as 30 caírem todas na cauda). Com os valores medidos entre contentores, 30 x 3,6 = 108 ms (p50) e 30 x 4,3 = 128 ms (p95). Em chamadas locais seriam microssegundos.
- **Paralelo:** o tempo é o máximo das 30. A probabilidade de todas ficarem abaixo de 4 ms é 0,95^30 ≈ 21%, por isso em cerca de 79% dos pedidos pelo menos uma chamada é lenta. O p95 do pedido corresponde ao percentil 0,95^(1/30) ≈ 99,83 de uma chamada isolada, bem acima de 4 ms. Paralelizar reduz o tempo total, mas a cauda domina: quantas mais chamadas, mais provável é apanhar uma lenta.

**4. Que falácias refutam os números?**

- **#2 "Latency is zero":** é a mais clara. Uma função local custa ~10^-5 ms, uma chamada entre contentores 3,6 ms, a UMinho 167 ms e os EUA 319 ms (p50). O custo da distância é visível e cresce por ordens de magnitude.
- **#1 "The network is reliable":** na rajada sem pausa, 2 em 200 pedidos (1%) falharam sem aviso, para um servidor que normalmente responde bem. Ignorar as exceções teria enviesado os percentis.
- **#7 "Transport cost is zero":** com ligação nova por pedido, cada pedido HTTPS paga DNS, handshake TCP e TLS. É por isso que 167 ms para um servidor em Portugal é alto, e a reutilização de ligações reduziria este custo.


