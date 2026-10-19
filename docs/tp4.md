# TP4 - Servico de ingestao

## Exercicio 1 - Endpoint de ingestao

Mesmo lote de 1 leitura enviado 2 vezes para `POST /v1/leituras`: ambas as respostas `202` com `recebidas: 1`, e `SELECT count(*)` devolve **1** linha. A idempotencia vive na base de dados (`ON CONFLICT (dispositivo_id, instante, parametro) DO NOTHING`), que e atomica: nao ha corrida entre um SELECT e um INSERT, ao contrario de uma verificacao em Python.

Com a BD parada, `/saude/viva` responde **200** e `/saude/pronto` responde **503**.

## Exercicio 2 - async: quando ajuda, quando destroi

50 clientes concorrentes durante 10 s, atraso simulado de 200 ms por pedido.

| Endpoint | Debito (req/s) | p50 (ms) | p99 (ms) | Falhas |
|---|---|---|---|---|
| `/teste/bloqueante` | 5,0 | 9882 | 10053 | 2 (ReadTimeout) |
| `/teste/assincrono` | 231,5 | 204 | 440 | 0 |
| `/teste/thread` | 186,7 | 250 | 513 | 0 |

Teoria: bloqueante 1/0,2 = 5 req/s; assincrono 50/0,2 = 250 req/s; thread 40/0,2 = 200 req/s (threadpool por omissao com 40 threads).

**1. Explicar o colapso.** O event loop e uma unica thread que faz transitar cada pedido entre estados (recebido, a executar, a espera de I/O, concluido). Com `await`, o pedido passa a espera e o loop avanca os outros. Com `time.sleep`, o pedido fica a executar sem ceder e os restantes ficam em recebido: o servico fica serializado. Lei de Little: N = lambda x W, 50 = 5 x 10 s, que e o p50 medido.

**2. `psycopg2` dentro de `async def`.** E a variante bloqueante: cada query p?ra o loop durante a sua duracao, o debito maximo passa a ser 1/(tempo da query) e uma query lenta congela tudo, incluindo `/saude/viva`. Corrige-se com um driver assincrono (`asyncpg`) ou com `def` simples (threadpool).

**3. Workers necessarios.** Cada worker bloqueante da 5 req/s, logo seriam cerca de 46 a 50 workers para igualar o assincrono. Nao e aceitavel: cada worker e um processo com memoria e pool de ligacoes proprios, a dormir, e o numero cresce com a concorrencia. A variante `def` com threadpool da 187 req/s num so processo e e a correcao mais barata quando o codigo tem de ser sincrono.

## Exercicio 3 - Falha em cascata

Validacao do dispositivo no portal (`GET /api/v1/devices/{serie}/`, campo `internamento`) antes de gravar. Carga: 50 clientes concorrentes, 15 s, lotes de 10 leituras, 60 dispositivos distintos. O portal corre com 3 workers Gunicorn e a latencia de 3 s e injetada por `LATENCIA_MS=3000`. Cada configuracao e cumulativa (inclui as anteriores) e e escolhida por `MODO_VALIDACAO`. Uma execucao por linha.

| Configuracao | Debito (req/s) | Leituras perdidas | p99 (ms) | Falhas HTTP | Retries | Nao validadas | Rejeitadas pelo disjuntor | Cache hits |
|---|---|---|---|---|---|---|---|---|
| Sincrona, portal saudavel | 8,2 | 0 | 7561 | 0 | 0 | 0 | 0 | 0 |
| Sincrona, portal a 3 s | 5,0 | 1000 | 10092 | 100 | 0 | 0 | 0 | 0 |
| + timeout 500 ms | 29,1 | 0 | 2407 | 0 | 0 | 4160 | 0 | 0 |
| + retry com backoff e jitter | 9,6 | 0 | 7507 | 0 | 3452 | 1726 | 0 | 0 |
| + disjuntor | 185,2 | 0 | 1863 | 0 | 442 | 26306 | 26306 | 0 |
| + cache local 60 s | 226,9 | 0 | 1178 | 0 | 0 | 0 | 0 | 32032 |

A ultima linha foi medida com a cache aquecida (60 entradas, disjuntor fechado) antes de o portal passar a 3 s. A primeira execucao desta linha foi descartada: o aquecimento corria com a mesma carga das outras linhas, o disjuntor abriu e a cache nunca se encheu (0 hits).

### Analise

**Porque e que a ingestao parou se o portal esta vivo.** Na variante sincrona cada pedido de ingestao espera pelo portal antes de gravar. Com 3 s por consulta e sem timeout, cada pedido fica preso ate o cliente desistir (10 s). Pela lei de Little, 50 pedidos em curso com tempo de resposta de 10 s dao 5 req/s, que e o debito medido. O pool de ligacoes ao portal enche-se, os clientes dao timeout (100 pedidos = 1000 leituras perdidas) e a ingestao nao grava nada, embora a sua base de dados e o seu codigo estejam intactos. A lentidao propagou-se por uma dependencia sincrona: e uma falha em cascata, e o portal nem sequer esta em baixo.

**Timeout (500 ms) e fail open.** O debito sobe para 29 req/s e deixa de haver leituras perdidas. Quando o timeout dispara, a leitura e aceite sem validacao e o dispositivo fica em `ingestao_reconciliar` (uma linha por dispositivo, nao por leitura, para nao somar uma escrita a cada pedido). A decisao e clinica: perder uma leitura de sinais vitais e pior do que aceitar uma de um dispositivo nao associado, que se corrige depois por reconciliacao. O custo e que, durante a falha, nao ha validacao nenhuma (4160 nao validadas).

**Retry sem disjuntor piora.** O debito cai de 29 para 9,6 req/s e o p99 volta a 7,5 s. Com o portal a 3 s, todas as tentativas falham, logo cada validacao passa a custar ate 3 consultas (3452 retries). O portal nao cancela o trabalho que o cliente abandonou: os 3 workers continuam ocupados com pedidos ja desistidos, e as novas tentativas juntam-se a fila. O retry multiplica a carga sobre um servico que ja esta saturado. O jitter desfaz a sincronia entre clientes, que e o que evita o thundering herd (400 gateways a falhar juntos tentariam todos juntos), mas nao reduz a carga total. Por isso o retry so e seguro com um limite que o corte: o disjuntor.

**Disjuntor.** Abre apos 5 falhas consecutivas e fica aberto 10 s. Depois deixa passar um unico pedido de teste (meio-aberto): se resulta, fecha, se falha, reabre. Enquanto esta aberto responde logo com o valor por omissao, sem tocar no portal. Foi o salto grande: 185 req/s, e 26306 validacoes evitadas. Os 442 retries sao so os das janelas em que estava fechado ou a testar. O portal fica com carga quase nula e tem hipotese de recuperar. O custo e o mesmo do fail open, com mais leituras nao validadas.

**Cache local, TTL 60 s.** Com a cache aquecida, as 32032 validacoes foram respondidas localmente, sem uma unica chamada ao portal: 227 req/s, 0 nao validadas, 0 retries. Isto e replicacao com consistencia eventual e um limite explicito de desatualizacao (B6): a ingestao mantem uma copia local do estado "dispositivo com internamento ativo", que pode estar atrasada ate 60 s. Consequencias: um dispositivo que perdeu o internamento continua aceite ate 60 s, e um dispositivo desconhecido (invalido) fica rejeitado ate 60 s mesmo que entretanto seja associado. Ganhamos disponibilidade e latencia a custa de frescura, o que e aceitavel para este dominio. A cache so guarda respostas definitivas (valido ou invalido), nunca falhas: por isso nao se enche sozinha com o portal lento, e e preciso aquece-la quando o portal esta saudavel. Passados 60 s sem renovar, as entradas expiram e o sistema volta ao comportamento do disjuntor.

### Limites das medicoes

- Uma execucao por linha, sem repeticoes: os valores mostram ordens de grandeza, nao intervalos de confianca.
- O debito de 8,2 req/s com o portal saudavel e baixo porque cada pedido faz cerca de 9 consultas ao portal (um por dispositivo distinto do lote) contra 3 workers e um pool de 20 ligacoes na ingestao. O teto da primeira linha e o portal, nao a ingestao.
- Com `Timeout(0.5)` a espera por uma ligacao do pool tambem conta como timeout, por isso parte das falhas das linhas 3 a 5 pode ser do pool e nao do portal. Nao foi medido separadamente.
- Sem validacao (`MODO_VALIDACAO=off`) a ingestao faz 198,7 req/s com p99 de 1154 ms (30080 leituras, 0 perdidas). A linha da cache (226,9 req/s, p99 de 1178 ms) esta na mesma ordem de grandeza: com a cache aquecida a validacao deixa de ter custo e o limite passa a ser a escrita na base de dados. A diferenca de 14% a favor da cache esta dentro da variacao entre execucoes unicas, nao e um ganho real.

## Exercicio 4 - Gateway e recuperacao apos falha

### Configuracao

O gateway foi executado com 80 dispositivos, 4 sensores por dispositivo, frequencia de 1 Hz e duracao de 90 segundos. Durante a execucao, o servico de ingestao foi interrompido temporariamente com `docker compose stop ingestao` e reiniciado posteriormente com `docker compose start ingestao`.

Durante a indisponibilidade, o gateway continuou a gerar leituras e guardou os lotes pendentes em disco. Quando a ingestao recuperou, o gateway reenviou os lotes em fila.

| Parametro | Valor |
|---|---:|
| Dispositivos | 80 |
| Sensores por dispositivo | 4 |
| Frequencia | 1 Hz |
| Duracao da simulacao | 90 s |
| Indisponibilidade observada | 30,7 s |
| Interrupcoes detetadas | 1 |
| Maximo de lotes em fila | 18 |
| Lotes em fila quando a ingestao recuperou | 17 |

### Resultados

| Metrica | Resultado |
|---|---:|
| Leituras geradas | 7280 |
| Leituras confirmadas pelo gateway | 7280 |
| Leituras na base de dados durante o intervalo do teste | 7280 |
| Falhas de envio reportadas | 5 |
| Atraso maximo reportado | 34,7 s |
| Leituras descartadas por overflow | 0 |
| Rejeicoes definitivas | 0 |
| Leituras rejeitadas pelo servico | 0 |
| Lotes pendentes no final | 0 |
| Leituras pendentes em disco no final | 0 |
| Oclusoes de SpO2 | 3 |

### Analise

Durante a interrupcao da ingestao, o gateway detetou a indisponibilidade do servico e guardou os lotes pendentes em disco. A fila aumentou enquanto o servico esteve indisponivel, atingindo um maximo reportado de 18 lotes.

Apos aproximadamente 30,7 segundos, a ingestao recuperou e o gateway iniciou o reenvio dos 17 lotes em fila. No final da simulacao, o gateway reportou 7280 leituras geradas e confirmadas, sem leituras descartadas por overflow e sem dados pendentes em disco.

Foi tambem consultada a tabela `vigilancia_leitura` na base de dados, restringindo a contagem ao intervalo temporal da execucao. A consulta devolveu 7280 registos, o mesmo numero de leituras reportado pelo gateway.

Os resultados mostram que, nesta execucao, o gateway conseguiu tolerar uma interrupcao temporaria da ingestao, armazenar localmente as leituras pendentes e retomar o envio apos a recuperacao do servico.

### Conclusao

O teste demonstrou a recuperacao do envio apos uma interrupcao temporaria da ingestao. Todas as 7280 leituras geradas foram reportadas como confirmadas pelo gateway e a contagem na base de dados, no intervalo do teste, coincidiu com esse total. O buffer terminou vazio e nao foram reportadas perdas por overflow ou rejeicoes definitivas.

Esta conclusao corresponde a uma unica execucao e nao constitui uma garantia de ausencia de perdas em todas as condicoes de falha.
