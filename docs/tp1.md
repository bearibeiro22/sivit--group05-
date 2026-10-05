# TP1


### Exercise 1

**1. Do the nginx processes appear in the host's process list? What does that tell you about what a container is ?**

Ao inspecionar a lista de processos da máquina anfitriã, confirma-se que o processo associado ao Nginx é visível no sistema anfitrião. Este comportamento evidencia que um contentor não é uma máquina virtual completa, a qual exigiria a virtualização de um sistema operativo inteiro e de hardware dedicado. Na realidade, um contentor é simplesmente um processo ou grupo de processos convencional a correr diretamente sobre o kernel do host, estando apenas isolado através de funcionalidades nativas do próprio sistema operativo.

**2. Which namespaces are listed under `/proc/<pid>/ns/`? What does each isolate?**

No diretório `/proc/<PID>/ns/` observam-se diversos namespaces do Linux responsáveis por garantir o isolamento do ambiente. O PID namespace restringe a visão da árvore de processos, fazendo com que o contentor apenas identifique os seus próprios programas e atribua o PID 1 à sua aplicação principal. O NET namespace providencia a segregação de rede, atribuindo ao contentor a sua própria pilha de rede, interfaces virtuais e tabelas de encaminhamento. Por fim, o MNT namespace isola a estrutura do sistema de ficheiros e os pontos de montagem, enquanto o IPC namespace impede a partilha indevida de mecanismos de comunicação entre processos com a máquina anfitriã.

**3. Compare `docker exec web ps aux` with `ps aux` on the host. Why do they differ?**

A execução do comando `ps aux` no interior do contentor revela unicamente o processo do Nginx e os seus subprocessos, ao passo que a verificação no host apresenta a totalidade dos processos em execução no sistema operativo. Esta divergência decorre da atuação do PID namespace, que limita a visibilidade interna do contentor aos processos criados dentro do seu próprio domínio de isolamento. Enquanto o host mantém uma perspetiva global de todos os processos a correr na máquina, o contentor opera numa perspetiva restrita, sem qualquer conhecimento dos processos externos.

**4. What happened? Which kernel mechanism caused it?**

Quando a aplicação Python tenta alocar 200MB de memória num ambiente com o limite fixado em 64MB, o processo é imediatamente interrompido e abortado pelo sistema operativo. O mecanismo do kernel encarregue de impor esta restrição são os cgroups (*Control Groups*), atuando em conjunto com o OOM Killer (*Out-Of-Memory Killer*) do Linux. Ao passo que os namespaces gerem o isolamento da visibilidade, os cgroups gerem a quota máxima de recursos físicos que o contentor pode consumir. Ao ultrapassar o patamar de memória atribuído, o kernel intervém para cessar a execução do processo e salvaguardar a estabilidade global da máquina anfitriã.

---

### Exercise 2

**Q: Replicating took one command. Which property of this service made that trivial?**

O serviço é *stateless* (não guarda estado localmente), o que permite criar múltiplas instâncias idênticas em paralelo sem conflitos de dados. Podes apontar esta resposta para juntares à documentação do trabalho.

---

### Exercise 4

Fill this in:

| Cenário de Teste | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) |
| --- | --- | --- | --- | --- |
| **Local function call** | 0.00050 | 0.00060 | 0.00220 | 0.00260 |
| **HTTP to localhost** | 7.66 | 10.12 | 11.59 | 166.28 |
| **HTTP between containers** | 4.33 | 7.00 | 9.98 | 110.37 |
| **HTTP to UMinho** | N/A * | N/A * | N/A * | N/A * |
| **HTTP to USA** | 381.22 | 489.05 | 596.81 | 4000.97 |

** **Nota:** O pedido ao servidor da UMinho (`[https://www.uminho.pt](https://www.uminho.pt)`) resultou num `HTTP Error 500: Internal Server Error` provavelmente devido às políticas de segurança/proteção do servidor de destino.*

**1. How many orders of magnitude separate the local call from the intercontinental one?**

A chamada de função local registou uma mediana (p50) de cerca de 0.0005 ms, enquanto a chamada HTTP intercontinental para os EUA obteve um p50 de cerca de 381.22 ms. Dividindo o valor intercontinental pelo valor local ($381.22 / 0.0005 \approx 762\ 440$), observa-se um fator de quase $10^6$. Isto significa que a chamada intercontinental é aproximadamente 6 ordens de magnitude mais lenta do que a chamada local, uma diferença imposta pelas restrições físicas da velocidade da luz na fibra ótica e pelos múltiplos saltos de encaminhamento transatlânticos.

**2. Why is p99 so much higher than p50, even between containers on one machine?**

A diferença entre o p99 e o p50 no caso de chamadas entre contentores na mesma máquina — onde o p50 ronda os 4.33 ms e o p99 atinge cerca de 9.98 ms, disparando até um máximo de 110.37 ms — deve-se à ocorrência de picos de latência (*jitter*) causados por concorrência de recursos no sistema anfitrião. Mesmo dentro da mesma máquina, fatores como interrupções de CPU pelo sistema operativo (Windows/WSL), ações de recolha de lixo (*Garbage Collection*) da linguagem, trocas de contexto (*context switching*) entre threads e flutuações temporárias no escalonamento de pacotes na pilha de rede do Docker perturbam esporadicamente o fluxo contínuo dos pedidos, afetando a cauda da distribuição.

**3. A service makes 30 sequential remote calls to serve one request, each with p95 = 4 ms. What is the p95 of the whole request? And if they ran in parallel?**

Quando 30 chamadas remotas são executadas de forma sequencial, as latências acumulando-se diretamente resultam num p95 global que se aproxima da soma simples dos percentis individuais, totalizando $30 \times 4\text{ ms} = 120\text{ ms}$ (na verdade, a probabilidade de um pedido falhar o limiar de 4 ms em pelo menos uma das 30 chamadas faz com que a latência combinada do p95 seja tipicamente superior a 120 ms). Caso as 30 chamadas fossem executadas em paralelo, o tempo total de resposta deixaria de ser aditivo e passaria a ser determinado pelo valor máximo (a chamada mais lenta), pelo que o p95 global ficaria ligeiramente acima dos 4 ms individuais (por volta dos 5 ms a 7 ms), limitado apenas pelo pior caso da chamada paralela e pelo pequeno *overhead* de sincronização de threads.

**4. Which of the eight fallacies do your numbers refute? Justify with the values.**

Os dados recolhidos na tabela refutam categoricamente a falácia de que "a latência é zero" (Latency is zero) e a falácia de que "a rede é fiável" (The network is reliable). A falácia da latência zero é desmentida logo pela transição de uma chamada local de $0.0005\text{ ms}$ para um pedido HTTP local de $7.66\text{ ms}$ e intercontinental de $381.22\text{ ms}$, demonstrando que passar dados pela rede introduz atrasos reais e mensuráveis. Já a falácia da fiabilidade é desmentida pelo facto do teste ao servidor da UMinho ter resultado num erro HTTP 500 e pelos picos no valor máximo (como os $166.28\text{ ms}$ em localhost e $4000.97\text{ ms}$ para os EUA), provando que as ligações de rede estão sujeitas a falhas pontuais e instabilidade temporária.