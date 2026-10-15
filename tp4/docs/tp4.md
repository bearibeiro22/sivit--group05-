# TP4 - Microserviço de Ingestão

Aplicações Distribuídas · MEB-IM · Universidade do Minho

## 1. Justificação da separação em dois serviços

| | Portal Django | Serviço de ingestão |
|---|---|---|
| Pedidos/s | ~20 (80 clínicos) | 400-2000 (400 monitores) |
| Perfil | leituras de perfil, sessões, escritas HTML | escritas stateless, JSON pequeno |
| Latência aceitável | 800 ms | 50 ms |
| Ritmo de alteração | semanal | raro |

Os dois componentes têm perfis de carga muito diferentes. Escalar o Django para 2000 escritas/s escalaria também templates, sessões e autenticação, que não precisam disso. Separar permite escalar só a ingestão, com uma latência-alvo 16 vezes menor e um ciclo de vida de alterações diferente.

O custo da separação é real: passam a existir dois serviços, duas pipelines e uma fronteira de rede onde antes havia uma chamada de função. Compensa porque os perfis divergem, e não por princípio.

## 2. Exercício 1 - O endpoint de ingestão

O serviço foi feito em FastAPI com `asyncpg` e corre num contentor. Expõe `POST /v1/readings`, `GET /health/live` e `GET /health/ready`. A idempotência foi testada enviando a mesma leitura duas vezes: a tabela continuou com uma só linha.

**1. `ON CONFLICT ... DO NOTHING`: idempotência na base de dados. Comparação com a solução Python do TP3: qual é mais segura sob concorrência?**

A solução com `ON CONFLICT` é mais segura. A verificação feita em Python (consultar e depois inserir) deixa uma janela entre o `SELECT` e o `INSERT`: dois pedidos concorrentes podem ambos concluir que a leitura não existe e ambos inserir. Com `ON CONFLICT`, a verificação e a inserção são uma única operação atómica, e a restrição `UNIQUE (device_serial, instant, parameter)` garante a unicidade na própria base de dados, independentemente de quantas instâncias do serviço existam.

**2. Porquê `202 Accepted` e não `201 Created`?**

O 202 diz ao cliente que o pedido foi aceite, sem prometer que o recurso já está criado e visível. No TP5 a escrita passa a ser assíncrona (via mensageria), e um contrato que já devolve 202 continua válido sem alterar os clientes. Um 201 prometeria algo que deixaria de ser verdade.

**3. Dois health endpoints: o que acontece se o balanceador usar `ready` e a BD abrandar? E se usar `live`?**

- Com `ready`: quando a BD abranda, as instâncias deixam de passar a verificação e o balanceador retira-as de circulação, em vez de lhes enviar tráfego que iria falhar. O risco é que, se todas as instâncias dependem da mesma BD lenta, ficam todas fora de circulação ao mesmo tempo e o serviço fica totalmente indisponível, mesmo estando os processos saudáveis.
- Com `live`: o endpoint só confirma que o processo está de pé, por isso o balanceador continua a enviar tráfego para instâncias que não conseguem escrever na BD, e os pedidos falham ou expiram.

Por isso `live` não verifica dependências (se verificasse, um problema na BD levaria a reiniciar processos saudáveis), e `ready` verifica a ligação à BD.

## 3. Exercício 2 - async: quando ajuda, quando destrói

Teste: 50 clientes concorrentes, 10 s por endpoint, com `hey`.

| Endpoint | Throughput (req/s) | p50 (ms) | p99 (ms) |
|---|---|---|---|
| /test/blocking | 4,9 | 2826 | ~20000* |
| /test/async | 242,1 | 203,5 | 216,8 |
| /test/thread | 194,1 | 217,9 | 380,7 |

\* No `blocking` o `hey` não imprimiu a linha de 99%, porque muitos pedidos ficaram em espera; indica-se o pedido mais lento (19,9997 s). O teste durou 20 s em vez de 10 s pelo mesmo motivo.

O `thread` fica abaixo do `async` porque o threadpool tem cerca de 40 threads, o que dá um teto de ~200 req/s (40 / 0,2 s). Com 50 clientes, 10 esperam por uma thread livre, o que explica o p99 de ~0,38 s.

**1. Explicação do colapso em termos do modelo de máquina de estados finita (B3)**

O B3 distingue três organizações de servidor: single-threaded, multi-threaded e máquina de estados finita (event loop + I/O não bloqueante). O Uvicorn + FastAPI async é a máquina de estados finita: há um único event loop, e cada pedido avança de estado quando acontece um evento (por exemplo, uma operação de I/O que termina). O `await` devolve o controlo ao loop, que passa a tratar de outro pedido, e por isso não há custo de sincronização. O reverso, como diz o B3, é que "um bloqueio mata tudo": o `time.sleep` não devolve o controlo, o loop inteiro fica parado durante 0,2 s e nenhum outro evento é processado. O servidor passa a comportar-se como single-threaded, atendendo um pedido de cada vez (1 / 0,2 s = 5 req/s), apesar de o endpoint estar declarado `async`. Os restantes pedidos ficam em fila, e a latência sobe para segundos (p50 de 2,8 s).

O endpoint `thread` corresponde à organização multi-threaded (threadpool do FastAPI): atende vários pedidos em simultâneo (194 req/s), mas limitado ao tamanho do pool.

**2. Um driver síncrono (`psycopg2`) dentro de `async def`: que variante estamos a construir?**

A variante `blocking`. A chamada síncrona à base de dados bloqueia o event loop inteiro enquanto espera pela resposta, tal como o `time.sleep`. É o erro mais comum em FastAPI (B3). O throughput fica limitado a 1 / (duração da query). A solução é usar um driver assíncrono (`asyncpg`, como neste serviço) ou declarar o endpoint com `def` para correr no threadpool.

**3. Quantos workers Uvicorn para o `blocking` igualar o `async`? É uma correção aceitável?**

Cada worker atende um pedido de cada vez, a 0,2 s por pedido, ou seja 5 req/s por worker (a mesma conta do B3: um servidor que espera 50 ms por query faz 20 req/s por processo, e 400 monitores a 1 Hz exigiriam 20 processos). Para igualar os 242 req/s do `async` seriam precisos cerca de 50 workers. Não é aceitável: cada worker é um processo com memória própria e ligações próprias à base de dados, e estaria a usar-se hardware para compensar um erro de código. Além disso, o número de workers necessários cresce com a latência da operação bloqueante: com uma dependência a 3 s, seriam precisas centenas.

## 4. Exercício 3 - Falha em cascata

**Montagem.** O serviço de ingestão valida cada dispositivo no portal (`GET /api/v1/devices/{serial}/`) antes de gravar a leitura. O portal foi substituído por um stub com latência configurável, equivalente a um middleware de latência no portal. Cada configuração acrescenta um padrão à anterior, e os padrões ligam-se e desligam-se em runtime (`/admin/config`).

**Carga.** 50 clientes concorrentes durante 10 s, com `hey`, e um limite de 1 s por pedido, como se o gateway desistisse ao fim de 1 s. Uma leitura perdida é um pedido que não recebe 202 dentro desse tempo. O throughput é o número de respostas 202 a dividir pela duração do teste.

| Configuração | Throughput (req/s) | Leituras perdidas | p99 (ms) |
|---|---|---|---|
| Síncrono, portal saudável | 77 | 75 de 853 (8,8 %) | 975 |
| Síncrono, portal a 3 s | 0 | 500 de 500 (100 %) | n/d (>1000) |
| + timeout 500 ms | 36,6 | 225 de 609 (37 %) | 996 |
| + retry com backoff e jitter | 0 | 500 de 500 (100 %) | n/d (>1000) |
| + circuit breaker | 654,8 | 50 de 6629 (0,8 %) | 261 |
| + cache local 60 s | 936,8 | 0 de 9428 (0 %) | 133 |

Nas linhas sem respostas concluídas o `hey` não calcula o p99, por isso indica-se apenas que ultrapassa o limite de 1000 ms.

**Porque parou a ingestão, se o portal está lento mas de pé?** A validação é feita de forma síncrona dentro do pedido: cada pedido à ingestão espera pela resposta do portal. Com o portal a 3 s, todos os pedidos demoram mais de 3 s, passam o limite de 1 s do gateway e perdem-se (100 %). A lentidão de um serviço propagou-se a outro que estava saudável, porque não havia isolamento entre os dois: é uma falha em cascata.

**Timeout (500 ms).** Limita a espera pelo portal. Quando dispara, a decisão é clínica: perder uma leitura de sinais vitais é pior do que aceitar uma de um dispositivo sem admissão associada, por isso a ingestão aceita a leitura (fail open) e marca-a na coluna `unvalidated` para reconciliação posterior. As perdas desceram de 100 % para 37 %, mas continuam altas.

**Retry com backoff exponencial e jitter.** Não ajudou, e piorou: com o portal lento de forma persistente, 3 tentativas de 0,5 s excedem o limite de 1 s do gateway (100 % de perdas). O retry ajuda em falhas transitórias, não numa lentidão persistente. O jitter evita o thundering herd (B8): sem ele, 400 gateways que falham ao mesmo tempo tentariam de novo ao mesmo tempo.

**Circuit breaker.** Depois de 5 falhas seguidas, deixa de chamar o portal durante 10 s e usa a decisão por omissão (aceitar e marcar). O throughput passou para 655 req/s. As 50 perdas são a rajada inicial de 50 pedidos, que pagaram as tentativas antes de o circuito abrir.

**Cache local de dispositivos válidos (TTL 60 s).** É replicação com consistência eventual e um limite explícito de desatualização (B6): a ingestão pode usar informação com até 60 s de atraso (por exemplo, um dispositivo cuja admissão terminou continua a ser aceite até 60 s). Em troca, deixa de chamar o portal e atinge 937 req/s sem perdas. A cache foi aquecida com o portal saudável; com a cache vazia e o portal já lento, o comportamento seria o da linha anterior.

As leituras aceites sem validação ficam marcadas em `unvalidated` e precisam de um processo de reconciliação, que fica para o TP5.

## 5. Exercício 4 - Simulador de gateway

**Implementação.** O simulador (`gateway/gateway.py`) corre num contentor, lançado com `docker compose run --rm gateway --devices N --hz F --url URL --anomaly-rate P --duration S`. Todos os parâmetros são configuráveis: número de dispositivos, frequência, endereço de destino, taxa de anomalias e duração.

Sinais gerados por dispositivo:
- **HR:** passeio aleatório em torno de 75 bpm, com ruído de medida.
- **SpO2:** cerca de 97,5 %, com oclusões ocasionais (queda para 80-88 % durante alguns segundos).
- **TEMP:** deriva lenta em torno de 36-37 graus.
- **Anomalias (opcional):** valores fora do normal injetados com a probabilidade pedida, para testar alarmes no futuro.

**Buffer local.** Quando a ingestão não está disponível (erro de rede ou resposta 5xx), as leituras são guardadas num buffer em disco (SQLite, num volume do Docker, por isso sobrevive a reinícios do contentor). Quando a ingestão volta, o buffer é reenviado por ordem, do mais antigo para o mais recente, e só depois se retoma o envio normal. Uma resposta 4xx significa que o pedido nunca vai ser aceite, por isso a leitura é descartada em vez de ficar a ser reenviada para sempre. O reenvio é seguro porque a ingestão ignora duplicados (`ON CONFLICT DO NOTHING`), pelo que a entrega é "pelo menos uma vez" sem duplicados na base de dados. Isto é comunicação persistente implementada à mão (B4); no TP5 é o broker que o faz.

**Teste.** 5 dispositivos a 1 Hz durante 70 s, com a ingestão parada durante cerca de 25 s a meio do teste.

| Métrica | Leituras |
|---|---|
| Geradas | 1050 |
| Enviadas diretamente | 645 |
| Guardadas no buffer (ingestão parada) | 405 |
| Repostas do buffer | 405 |
| Pendentes no fim | 0 |
| Descartadas | 0 |

Na base de dados ficaram as 1050 leituras desta execução, sem duplicados (o número de linhas é igual ao de linhas distintas). Não se perdeu nenhuma leitura.

**Problema.** Na primeira versão, cada tentativa de envio falhada bloqueava o simulador até 2 s, e durante a paragem só se guardaram 90 leituras em vez das cerca de 375 esperadas: o gateway deixava de amostrar quando a rede caía, o que contradiz o objetivo do buffer. Na versão final a amostragem segue o relógio (1 leitura por segundo por dispositivo, seja qual for o estado da rede) e, depois de uma falha, só se volta a tentar ao fim de 2 s, guardando entretanto as leituras no buffer.

**Limitação.** O intervalo entre tentativas é fixo (2 s). Com centenas de gateways a reconectar-se ao mesmo tempo, isso pode causar um thundering herd (B8). Uma melhoria seria usar backoff exponencial com jitter, como no Exercício 3.
