# TP3 · API REST com Django REST Framework

Plataforma: Windows com Docker Desktop (backend WSL2). Código em `tp3/`: é a stack da
TP2 (Nginx → Gunicorn/Django → PostgreSQL) com uma API REST feita com Django REST Framework.
Só dados sintéticos.

## Exercício 1 · A API v1

O portal passou a ser também um **serviço**: além das páginas HTML para pessoas, tem uma API
JSON para máquinas (os gateways das enfermarias).

| Recurso | URI | Verbos |
| --- | --- | --- |
| Doentes | `/api/v1/patients/` | GET, POST |
| Internamentos | `/api/v1/admissions/` (`?active=true`) | GET, POST, PATCH |
| Dispositivos | `/api/v1/devices/` | GET, POST, PATCH |
| Leituras | `/api/v1/readings/` (`?device= ?parameter= ?since= ?until=`) | GET, **POST em lote** |
| Leituras de um dispositivo | `/api/v1/devices/{serial}/readings/` | GET, paginado |
| Última leitura | `/api/v1/devices/{serial}/readings/latest/` | GET, consistência forte |

**Decisões de desenho:**
- **`/v1/` no URL.** O contrato vai mudar, e os gateways dos armários das enfermarias não se
  atualizam todos ao mesmo tempo. Uma `v2` pode coexistir com a `v1` (o sistema é aberto, B1).
- **O serializer é o contrato, não o esquema da BD.** A API usa nomes em inglês (`device`,
  `instant`, `value`) e a BD nomes em português (`dispositivo`, `instante`, `valor`), ligados
  por `source=`. Posso mudar o modelo sem partir os clientes.
- **Não se mostram ids internos.** Os dispositivos são identificados pelo **número de série**
  (o que o gateway conhece) e os doentes pelo código. A exceção são os internamentos, que não
  têm chave natural: aí o id é a única forma de os identificar. Por isso precisam de uma
  Idempotency-Key (exercício 2).
- **Validação no serializer:** cada parâmetro tem um intervalo plausível (FC 20–250 bpm,
  SpO2 50–100 %, PAS 40–300 mmHg, TEMP 30–45 °C). Um valor impossível rejeita o lote inteiro
  com **400**, para não ficar meio lote gravado.
- **POST em lote:** o gateway envia várias leituras num só pedido, em vez de uma ida e volta
  por leitura. É a lição do N+1 da TP2 aplicada à API (uma interface menos "fina", B4).
- **Autenticação:** as máquinas usam **Token** (um utilizador por gateway, sem password,
  criado com `criar_gateway`) e os humanos usam a **sessão** (admin, API navegável). Sem
  credenciais → **401**.
- **Paginação por defeito** de 100 resultados (`count`, `next`, `previous`).
- **`/readings/latest/`** lê sempre da BD, sem cache: a última leitura de um doente tem de
  estar certa.

**Verificação** (`curl` através do Nginx, com o token do `gateway-e1`):

| Pedido | Resultado |
| --- | --- |
| `GET /api/v1/` | 200, com os links dos 4 recursos |
| `GET /api/v1/patients/` | 200, `"count": 20`, paginado |
| `GET /api/v1/devices/` | 200, `"count": 60`, identificados por `serial_number` |
| `GET /api/v1/devices/SN-001-0/readings/latest/` | 200, a última leitura |
| `POST /api/v1/readings/` (lote de 2) | **201**, `{"received": 2, "inserted": 2, "ignored": 0}` |
| `POST` com FC = 900 | **400**, `value outside plausible range` |
| sem token | **401**, "As credenciais de autenticação não foram fornecidas." |

**Nota:** os links da API apareciam como `http://localhost/...`, sem a porta. O Nginx passava
ao Django o nome do servidor sem a porta (`$host`). Com `proxy_set_header Host $http_host` o
link fica correto (`http://localhost:8080/...`), o que é essencial para os links "próxima
página" da paginação.

## Exercício 2 · Idempotência, demonstrada

**Como está implementado:**
- **Ingestão de leituras** (`POST /api/v1/readings/`): `services.ingerir_leituras` faz
  `bulk_create(ignore_conflicts=True)`, ou seja `INSERT ... ON CONFLICT DO NOTHING`, apoiado na
  `UNIQUE(dispositivo, instante, parametro)` da TP2. Uma leitura repetida é ignorada pela base
  de dados e a resposta continua a ser 201.
- **Operações sem chave natural** (criar um internamento): o cliente envia o header
  `Idempotency-Key`. `services.com_idempotencia` procura a chave; se existir, devolve a resposta
  guardada. Se não existir, executa a operação e guarda a resposta no modelo `ChaveIdempotencia`,
  **na mesma transação**. A chave é guardada como `<utilizador>:<chave>`, para que dois gateways
  não colidam.
- **Simular a resposta perdida:** o `PerdaRespostaMiddleware` (ligado com `PERDA_RESPOSTA=0.3`)
  deixa o pedido ser processado e gravado, mas em 30 % dos POST o cliente recebe um erro em vez
  da resposta. O comando `simular_gateway` é um gateway que envia 20 lotes de 10 leituras pela
  rede (via Nginx) e repete o mesmo lote até receber 201.

**Resultados:**

| Experiência | Resultado |
| --- | --- |
| Passo 1: mesmo lote de 10, 3 vezes, **com** UNIQUE | `inserted` 10 → 0 → 0; **10 linhas** |
| Passo 1: mesmo lote de 10, 3 vezes, **sem** UNIQUE | `inserted` 10 → 10 → 10; **30 linhas** |
| Passo 2: 20 lotes, 30 % de respostas perdidas, **com** UNIQUE | 32 pedidos HTTP, 12 respostas perdidas; **200 linhas (correto)** |
| Passo 2: o mesmo, **sem** UNIQUE | 31 pedidos HTTP, 11 respostas perdidas; **310 linhas = 200 + 11 × 10 duplicadas** |
| Passo 3: criar internamento 2× com a mesma `Idempotency-Key` | as duas respostas com **o mesmo `id` (21)**; 1 internamento |
| Passo 3: o mesmo pedido **sem** chave | novo `id` (22): a cama 77 ficou com 2 internamentos |

**Teste automático** (`vigilancia/tests.py`, corre com
`docker compose exec portal python manage.py test vigilancia`): **5 testes, todos OK**.
- `test_mesmo_lote_3_vezes_fica_com_10_linhas`
- `test_respostas_perdidas_com_retry_estado_final_correto`: 30 % de perdas, retry até 201, e no
  fim 200 linhas exatas
- `test_chave_idempotencia_cria_um_so_internamento`
- `test_valor_impossivel_e_rejeitado`
- `test_sem_token_e_recusado`

### 1. Que semântica de falhas implementei: at-least-once, at-most-once ou exactly-once?

**Entrega at-least-once, com processamento idempotente, o que dá um efeito exactly-once.**

Sendo preciso:
- O **gateway** implementa *at-least-once*: repete o mesmo lote até receber 201, e por isso um
  lote pode chegar e ser processado mais do que uma vez. No passo 2 houve 32 pedidos para 20
  lotes: 12 lotes foram processados duas vezes.
- O **servidor** é idempotente: processar o mesmo lote outra vez não muda o estado (ON CONFLICT
  DO NOTHING / Idempotency-Key). O resultado final é o mesmo que se cada lote tivesse sido
  aplicado **exatamente uma vez**: 200 linhas.

Não é *exactly-once* na entrega, porque isso não se consegue garantir numa rede que perde
mensagens: o cliente nunca sabe se a falta de resposta foi antes ou depois de o servidor
gravar. O que se garante é o **efeito** exactly-once.

Há dois limites:
- Se o gateway desistir ao fim de 10 tentativas, esse lote pode não ter sido entregue: aí a
  garantia degrada-se.
- Sem a UNIQUE, a mesma estratégia de retry dá *at-least-once* com duplicados visíveis: 310
  linhas.

### 2. A UNIQUE e a chave de idempotência resolvem o mesmo problema? Quando é que só uma funciona?

Não. As duas evitam duplicados, mas identificam "o mesmo" de formas diferentes:

| | UNIQUE (chave natural) | Idempotency-Key |
| --- | --- | --- |
| O que identifica | o **dado**: (dispositivo, instante, parâmetro) | o **pedido**: a chave que o cliente escolheu |
| Precisa que o cliente colabore | não | sim: tem de reutilizar a mesma chave no retry |
| Devolve a resposta original | não (a repetição dá `inserted: 0`) | sim (o mesmo `id` 21) |
| Expira | não, faz parte dos dados | tem de expirar (pergunta 4) |

- **Só a UNIQUE funciona** quando o duplicado chega sem a mesma chave. Por exemplo: o gateway
  reinicia, perde a chave e reenvia as mesmas leituras noutro lote, ou reenvia-as dias depois
  de a chave ter expirado. A leitura continua a ser a mesma, por isso a base de dados recusa-a.
- **Só a chave funciona** quando a operação **não tem chave natural**: criar um internamento,
  "acknowledge this alarm". Dois internamentos iguais podem ser legítimos (o mesmo doente
  internado duas vezes), por isso não se pode pôr uma UNIQUE nos campos. No passo 3, o pedido
  sem chave criou mesmo um segundo internamento. A chave também é a única que devolve ao
  cliente **a resposta original** (o `id` criado), que ele precisa para continuar.

### 3. Se a resposta guardada for escrita fora da transação da operação, que falha passa a ser possível?

A operação e o registo da chave deixam de ser atómicos, e abrem-se duas janelas de falha:
- **Operação gravada, chave não gravada.** O processo morre (ou a BD falha) entre o commit do
  internamento e o `create` da chave. O cliente não recebeu resposta e repete com a mesma
  chave, mas a chave não existe: a operação é executada outra vez e fica um **internamento
  duplicado**, que é exatamente o problema que a chave devia evitar.
- **Chave gravada, operação desfeita.** Se a chave/resposta for guardada antes e a operação
  falhar depois, o retry devolve um 201 "de sucesso" de algo que **nunca aconteceu**: uma
  escrita perdida e silenciosa.

Também há a **corrida** entre dois pedidos com a mesma chave ao mesmo tempo: os dois não
encontram a chave e os dois executam. Na minha implementação, a chave é a chave primária e
está na mesma transação: o segundo `create` falha com `IntegrityError`, o rollback desfaz o
internamento desse pedido, e ele devolve a resposta do primeiro. Isto só funciona porque
estão na mesma transação.

### 4. Durante quanto tempo se deve guardar uma chave de idempotência? Qual é o compromisso?

Pelo menos durante **a janela máxima em que o cliente pode repetir o pedido**: todas as
tentativas, mais os tempos de espera, mais o tempo em que um gateway pode estar sem rede e a
acumular pedidos para reenviar. Num gateway de enfermaria isso pode ser horas. Um valor
habitual é **24 horas** (a Stripe, por exemplo, apaga as chaves com mais de 24 h).

**O compromisso:**
- **Guardar muito tempo** dá mais segurança contra retries tardios, mas a tabela cresce com
  cada pedido, a limpeza custa mais, e as respostas guardadas contêm **dados de saúde**. O
  princípio da minimização (RGPD) pede que não fiquem lá mais do que o necessário. Também
  aumenta o risco de um cliente que reutilize chaves por engano receber uma resposta antiga
  para uma operação nova.
- **Guardar pouco tempo** poupa espaço, mas um retry que chegue depois de a chave expirar é
  executado outra vez e cria um duplicado.

Por isso o modelo tem `criada` com índice: uma tarefa periódica pode fazer
`DELETE ... WHERE criada < now() - interval '24 hours'`. A UNIQUE das leituras não tem este
problema: não expira, porque faz parte dos próprios dados.

## Exercício 3 · O custo de não paginar

O endpoint `/api/v1/devices/{serial}/readings/` serve as leituras de um dispositivo, das mais
recentes para as mais antigas, de 3 formas:
- `?pagination=none`: tudo de uma vez;
- `?page=N`: offset, `LIMIT 100 OFFSET 100·(N-1)`;
- `?after=<instante>&limit=100`: cursor, `WHERE instante < <cursor> ORDER BY instante DESC LIMIT 100`.
  Cada página de cursor traz o link `next` com o cursor da página seguinte.

Carreguei **50 000 leituras** no `SN-001-0` (`carregar_leituras`, no total 50 050) e medi pela
rede, através do Nginx, como um cliente real (`medir_paginacao`, mediana de 5 pedidos,
páginas de 100):

| Strategy | First page | Page 500 | Response size |
| --- | --- | --- | --- |
| No pagination | 2348 ms (tudo) | – | **4.92 MB** |
| Offset (`?page=`) | 40.5 ms | 51.3 ms | 10.2 KB |
| Cursor (`?after=<instant>&limit=100`) | 32.0 ms | 39.6 ms | 10.2 KB |

**`EXPLAIN ANALYZE` da página 500** (`explicar_indice`). "Sem índices" significa
`enable_indexscan`, `enable_bitmapscan` e `enable_indexonlyscan` desligados só nessa transação,
o que obriga o PostgreSQL a ler a tabela toda sem apagar nenhum índice:

| Query (página 500) | Com índices | Sem índices |
| --- | --- | --- |
| **Offset** (`OFFSET 49900 LIMIT 100`) | Index Scan Backward, **lê 50 000 linhas**: **18.8 ms** | Seq Scan de 50 050 + Sort completo (*external merge*, 2.6 MB em disco): **31.8 ms** |
| **Cursor** (`instante < X LIMIT 100`) | Index Scan Backward, **lê 100 linhas**: **0.21 ms** | Seq Scan + Sort de 150 linhas: **4.8 ms** |

**Análise:**
- **Sem paginação:** uma única resposta de **4.92 MB** e **2.3 s**, só para um dispositivo.
  Com 60 dispositivos e vários clientes, um endpoint destes satura a rede e prende os 3
  workers do Gunicorn durante segundos. Funciona na demo, com 50 leituras, e cai em produção,
  com meses de dados. É a falácia n.º 3, "a largura de banda é infinita": paginar reduz a
  resposta **~490 vezes** (de 4.92 MB para 10 KB).
- **Offset:** o `OFFSET n` obriga a base de dados a **percorrer e deitar fora n linhas** antes
  de devolver as 100 pedidas. O plano mostra `rows=50000` para devolver 100. O custo cresce
  linearmente com o número da página: a página 5 000 de um dispositivo com 500 000 leituras
  seria 10 vezes pior. Além disso, o `PageNumberPagination` faz um `COUNT(*)` em cada página.
- **Cursor:** com o índice, vai **diretamente** ao instante do cursor e lê só as 100 linhas
  seguintes. A página 500 custa o mesmo que a página 1: na base de dados, 0.21 ms contra
  18.8 ms do offset, ou seja **~90 vezes menos**.
- **Pela rede, a diferença é menor** (51 vs 40 ms) porque os custos fixos (Nginx, Gunicorn,
  serializar 100 leituras em JSON, o `COUNT(*)` do offset) escondem parte do trabalho da BD.
  Com mais dados, o termo que cresce é o do offset.
- **Índices:** sem índice, mesmo o cursor tem de ler a tabela toda e ordenar (4.8 ms em vez de
  0.21 ms, ~23 vezes mais). O offset sem índice ordena 50 000 linhas em disco. O PostgreSQL
  escolheu o índice simples em `instante` em vez do composto `(dispositivo, instante DESC)`:
  quase todas as linhas da tabela são deste dispositivo, por isso filtrar pelo dispositivo
  quase não reduz nada. Para um dispositivo com poucas leituras seria o composto a ser usado.
  O planeador decide com base nas estatísticas (`ANALYZE`), e é por isso que se usa o
  `EXPLAIN`.

**O cursor também é mais correto, não só mais rápido.** Chegam leituras novas a cada segundo
e entram no topo da lista. Com offset, as páginas "deslizam" entre pedidos, e o cliente vê
leituras repetidas ou salta outras. Com o cursor ("as 100 anteriores a este instante"), a
página seguinte não muda. O custo é que não se pode saltar diretamente para a página 500, e
a chave do cursor tem de ser **única e estável**. Aqui o instante é único por dispositivo,
porque cada dispositivo tem um só parâmetro. Num caso geral usar-se-ia `(instante, id)` como
cursor, com um índice a condizer.

## Exercício 4 · Autenticação de máquinas e o contrato

**Token por gateway, separado das sessões humanas.** Cada gateway é um utilizador próprio,
sem password utilizável (`criar_gateway gateway-e1`), com um token
(`rest_framework.authtoken`). As máquinas autenticam-se com `Authorization: Token ...` e os
humanos com a sessão do Django (admin, API navegável). Têm ciclos de vida diferentes: um token
de gateway revoga-se sozinho, apagando o token, sem afetar ninguém, e um gateway nunca faz
login nem guarda cookies.

**Throttling por token (bulkhead, B8):** `UserRateThrottle`, com o limite vindo do ambiente
(`THROTTLE_GATEWAY`, por defeito 6000/minuto, ou seja 100 pedidos/s por gateway). Pedidos
anónimos: 60/minuto. Experiência com o limite descido para **20/minuto**:

| Cliente | Pedidos | Resultado |
| --- | --- | --- |
| `gateway-e1` (avariado) | 30 seguidos | **20 × 200**, depois **10 × 429** `Too Many Requests`, com `Retry-After: 59` |
| `gateway-e2` (ao mesmo tempo) | 5 | **5 × 200**: não é afetado |

O gateway avariado fica isolado no seu compartimento, e os outros continuam a ser servidos. A
resposta `429` com `Retry-After` diz-lhe quando pode voltar, em vez de o deixar a martelar o
serviço. É uma degradação controlada, e é **a ele** que se limita, não ao serviço (um `503`
seria "o serviço está em baixo para todos").

**Os contadores têm de ser partilhados.** O throttling guarda os contadores na cache do
Django, que por defeito vive **na memória de cada processo**. Com 3 workers no Gunicorn, cada
worker contaria sozinho, e o gateway conseguiria até 3 × 20 = 60 pedidos/minuto, dependendo do
worker que o atendesse. Mudei a cache para a base de dados (`DatabaseCache`, tabela
`cache_api`, criada no `arranque.sh` com `createcachetable`). O resultado foram exatamente 20
pedidos aceites com 3 workers. É a regra da B3: estado que tem de ser coerente entre réplicas
não pode viver na memória do processo. Com várias réplicas do portal, o natural seria o Redis.

**OpenAPI:** gerado pelo `drf-spectacular` a partir do código, publicado em `/api/schema/`
(HTTP 200, 18 KB, **16 operações** em `/api/v1/patients/`, `/admissions/`, `/devices/`,
`/devices/{serial}/readings/`, `/devices/{serial}/readings/latest/` e `/readings/`, e os
esquemas de autenticação `cookieAuth` e `tokenAuth`). Pode ser explorado no Swagger UI em
`/api/schema/swagger-ui/`.

### Discussão: o OpenAPI é o "IDL" da B4 para REST. Comparado com um `.proto`, qual é mais estrito? O que se ganha e perde com cada um?

**O `.proto` é mais estrito.** Num `.proto` (Protocol Buffers / gRPC) o contrato é **a fonte
da verdade**: o código do cliente e do servidor é **gerado** a partir dele, e a mensagem nem
sequer se consegue construir ou ler sem ele. É binária e os campos são identificados por
número. Os erros de tipo apanham-se ao compilar, e as regras de evolução são explícitas: os
números de campo nunca se reutilizam, um campo novo é ignorado por quem não o conhece.

O meu OpenAPI é **gerado a partir do código** (*code-first*). **Descreve** a API, mas não a
**impõe**: um cliente pode ignorá-lo e enviar o JSON que quiser, e a validação só acontece em
tempo de execução, no serializer (400). Também pode desviar-se da realidade. Por exemplo, o
endpoint `/devices/{serial}/readings/` devolve formas diferentes conforme o parâmetro
(`?page=`, `?after=`, `?pagination=none`), e o esquema gerado automaticamente não o consegue
exprimir com precisão sem anotações manuais (`@extend_schema`).

| | OpenAPI + REST/JSON | `.proto` + gRPC |
| --- | --- | --- |
| **Ganha-se** | legível por humanos; testável com `curl` e com o browser (foi assim que fiz todas as experiências); funciona com qualquer linguagem e através de qualquer proxy (o Nginx); usa a semântica do HTTP (códigos 201/400/401/429, verbos idempotentes, cache); acoplamento fraco: acrescentar campos ao JSON não parte clientes antigos | mensagens binárias compactas e rápidas de processar (os 4.92 MB de JSON do exercício 3 seriam bastante menores); tipos fortes verificados ao compilar; clientes gerados automaticamente; streaming bidirecional sobre HTTP/2 (natural para um fluxo contínuo de leituras) |
| **Perde-se** | JSON é verboso e mais lento de processar; os tipos só se verificam em tempo de execução; o contrato pode desviar-se do código | não é legível sem ferramentas; no browser precisa de gRPC-Web; mais acoplamento (os clientes têm de regenerar o código quando o `.proto` muda); mais difícil de inspecionar e de passar por alguns proxies |

**Para o SIVIT:** REST + OpenAPI é a escolha certa para o portal e para integrações externas,
onde a interoperabilidade e a facilidade de diagnóstico contam mais do que os bytes. Os
gateways das enfermarias são heterogéneos e difíceis de atualizar (a razão do `/v1/`), e o
JSON tolera melhor versões misturadas. Um `.proto`/gRPC faria sentido num canal **interno**
de ingestão de alto débito, entre serviços que controlamos e atualizamos juntos, que é o tipo
de microserviço que aparece na TP4.

