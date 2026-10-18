# TP3 - REST API com Django REST Framework

## Exercicio 2 - Idempotencia demonstrada

### Resultados experimentais

| Experiencia | Resultado |
|---|---|
| Mesmo lote de 10 leituras enviado 3 vezes, **sem** UNIQUE | **30** linhas |
| Mesmo lote de 10 leituras enviado 3 vezes, **com** UNIQUE (dispositivo, instante, parametro) | **10** linhas |
| 5 lotes com 50% de respostas perdidas e cliente com retries | 18 pedidos enviados, **50** linhas (e nao 180) |
| Mesma `Idempotency-Key` em 2 `POST /admissions/` | 1 internamento, 2.a resposta com `Idempotent-Replay: true` |

O teste automatico (`python manage.py test vigilancia`, ficheiro `vigilancia/tests/test_idempotencia.py`) tem 7 testes e passa. Demonstra que reenviar o mesmo lote nao duplica, que uma resposta perdida seguida de retry deixa o estado correto, e que sem chave o retry duplica um internamento mas com chave nao.

### Respostas

**1. Que semantica de falha implementamos?**
O cliente (`scripts/cliente_retry.py`) implementa **at-least-once**: repete o pedido ate receber 2xx, por isso o mesmo pedido pode ser executado mais de uma vez (18 pedidos para 5 lotes). O servidor torna a operacao **idempotente** (UNIQUE nas leituras, `Idempotency-Key` nos internamentos). A combinacao at-least-once + recetor idempotente da um **efeito exatamente uma vez** sobre o estado. Nao e entrega exactly-once: o trabalho duplicado acontece e e descartado. At-most-once seria nao repetir, e perderiamos leituras sempre que um pedido ou uma resposta se perdesse.

**2. A UNIQUE e a chave de idempotencia resolvem o mesmo problema?**
Resolvem o mesmo problema (o retry nao duplica), mas em casos diferentes. A UNIQUE exige uma **chave natural**: uma leitura e identificada por (dispositivo, instante, parametro). Funciona mesmo que o gateway nao envie nenhum cabecalho. So a UNIQUE funciona quando o cliente nao sabe gerar chaves (gateways antigos). Para operacoes **sem chave natural**, como abrir um internamento ou confirmar um alarme, nao ha nada unico que a base de dados possa usar (dois internamentos com os mesmos dados podem ser legitimos). So a chave de idempotencia funciona ai. A chave tem ainda a vantagem de devolver a **mesma resposta** da primeira execucao.

**3. E se a resposta guardada for escrita fora da transacao da operacao?**
Passam a ser possiveis duas falhas. (a) A operacao faz commit e o processo morre antes de guardar a chave: o retry nao encontra a chave e **executa outra vez** (duplicado, que e o que a chave devia evitar). (b) A chave fica guardada mas a operacao fez rollback: o retry recebe uma resposta de sucesso para algo que **nunca aconteceu**. Na mesma transacao, ou ficam as duas coisas ou nenhuma. Alem disso, o `get_or_create` sobre a chave primaria faz com que dois pedidos concorrentes com a mesma chave se serializem.

**4. Durante quanto tempo guardar uma chave? Qual o compromisso?**
Pelo menos mais do que a **janela maxima de retries** do cliente. Os gateways dos armarios das enfermarias podem ficar offline e reenviar horas depois, por isso uma retencao de 24 a 48 horas e razoavel. Se for curta demais, um retry tardio ja nao encontra a chave e duplica. Se for longa demais, a tabela cresce sem limite, o indice pesa, e a resposta guardada contem dados de doentes que ficam retidos mais tempo do que o necessario (minimizacao de dados no RGPD). Convem um trabalho periodico que apague as chaves com `created` anterior ao limite.

## Exercicio 3 - O custo de nao paginar

Dados: 50 000 leituras na tabela `vigilancia_leitura` (geradas com `generate_series`), paginas de 100 linhas. Cada estrategia foi medida 3 vezes com `curl`; a tabela mostra a mediana dos tempos totais (HTTP completo: nginx, Gunicorn, Django, DRF e base de dados). A "pagina 500" e a ultima (100 linhas).

| Estrategia | Primeira pagina | Pagina 500 | Tamanho da resposta |
|---|---|---|---|
| Sem paginacao | ~2,0 s (2,13 / 2,09 / 1,85 s) | n/a (a mesma resposta completa) | 5 116 661 bytes (~5,1 MB) |
| Offset (`?page=`) | 33 ms (18 a 190 ms) | 73 ms (38 a 214 ms) | ~10,3 KB (10 291 / 10 275 bytes) |
| Cursor (`?after=<instante>&limit=100`) | 10 ms (10 a 12 ms) | 12 ms (11 a 15 ms) | ~10,3 KB (10 328 / 10 246 bytes) |

### Porque e que o offset na pagina 500 e lento?

`OFFSET n` obriga a base de dados a percorrer n linhas antes de devolver alguma. Com `EXPLAIN ANALYZE`:

| Consulta | Linhas lidas | Execution Time |
|---|---|---|
| `... ORDER BY instante DESC, id DESC OFFSET 49900 LIMIT 100` | 50 000 | 16,9 ms |
| `... WHERE instante < <cursor> ORDER BY instante DESC, id DESC LIMIT 101` | ~100 | 0,16 ms |

O cursor (keyset) usa o indice para saltar diretamente para a posicao pedida, e o custo nao depende de quao fundo se esta. Ao nivel do HTTP a diferenca entre offset e cursor e pequena (73 ms contra 12 ms) porque 50 000 linhas e pouco para o PostgreSQL; o custo do offset cresce linearmente com a profundidade, o do cursor nao.

Outras diferencas: o offset precisa de um `COUNT(*)` para devolver o numero de paginas, o cursor nao (pede 1 linha a mais para saber se ha pagina seguinte). Com leituras a chegar continuamente, as paginas por offset deslocam-se (uma leitura nova empurra todas as outras e pode repetir ou perder linhas entre pedidos), enquanto o cursor e estavel. Em contrapartida o cursor nao permite saltar para a "pagina 500": so se avanca para a seguinte, o que serve bem uma serie temporal.

### Um endpoint sem paginacao e uma bomba-relogio

Sem paginacao, cada pedido devolve 5,1 MB e demora ~2 s com 50 000 leituras, e o custo cresce linearmente com a tabela. Atras do nginx (`proxy_read_timeout 10s`), extrapolando linearmente, o pedido deixaria de caber nos 10 s por volta das 250 000 leituras (estimativa, nao medida). Funciona na demonstracao e cai em producao: a falacia 3 (a largura de banda e infinita).


### Com e sem o indice `(dispositivo, -instante)`

Consulta da listagem de leituras de um dispositivo (a do endpoint `/devices/{serie}/readings/`), com 50 000 leituras distribuidas por 50 dispositivos (1000 cada):

`SELECT * FROM vigilancia_leitura WHERE dispositivo_id = <SN1> ORDER BY instante DESC, id DESC LIMIT 100`

Cada experiencia correu dentro de uma transacao terminada em `ROLLBACK`, por isso os indices apagados ficam repostos.

| Experiencia | Plano | Execution Time |
|---|---|---|
| E1 - todos os indices | percorre um indice, sem Seq Scan, e ordena com Incremental Sort | 0,66 ms |
| E2 - sem o indice composto | Index Scan Backward em `uniq_leitura` | 0,64 ms |
| E3 - sem o composto e sem a UNIQUE | Index Scan Backward no indice de `instante`, filtrando por dispositivo | 1,83 ms |
| E4 - sem nenhum indice util | **Seq Scan** a toda a tabela + Sort top-N | 4,54 ms |

Leitura dos resultados:

- Retirar **so** o indice composto nao mudou nada (0,66 ms contra 0,64 ms): a restricao `UNIQUE (dispositivo, instante, parametro)` cria um indice cujas colunas iniciais sao `(dispositivo, instante)`, e o PostgreSQL usa-o para esta consulta. Neste modelo o indice composto e redundante enquanto a UNIQUE existir, e passa a ser necessario se ela for retirada.
- Sem indice por dispositivo (E3) o PostgreSQL percorre o indice de `instante` e despreza as linhas de outros dispositivos (~3x mais lento).
- Sem nenhum indice util (E4) faz um **Seq Scan**: le a tabela inteira para devolver 100 linhas (~7x mais lento que E1). Com 50 000 linhas sao milissegundos, mas o custo do Seq Scan cresce com a tabela e o dos indices praticamente nao, por isso em milhoes de leituras a diferenca passa de milissegundos a segundos.

## Exercício 4 — Autenticação de máquinas e contrato da API

### 4.1. Autenticação dos gateways

O SIVIT recebe dados de dispositivos através de gateways, pelo que é necessário
garantir que apenas clientes autenticados conseguem aceder aos endpoints protegidos.
Para este efeito, a API utiliza autenticação por token, separada das sessões de
utilizadores humanos.

Cada gateway pode ter um token próprio, permitindo identificar o cliente que efetua
os pedidos. No projeto, os tokens dos gateways `alfa` e `beta` são criados através
do comando de gestão `criar_gateway`. O token é enviado no cabeçalho HTTP
`Authorization`, utilizando o prefixo `Token`.

Exemplo de pedido autenticado:

```http
GET /api/v1/readings/?limit=1 HTTP/1.1
Host: localhost:8080
Authorization: Token <token_do_gateway>
```

O token deve ser tratado como uma credencial secreta: não deve ser incluído no
repositório, em documentação pública ou em registos que possam ser consultados
por pessoas não autorizadas.

#### Testes de autenticação

A autenticação foi testada no endpoint `/api/v1/readings/`, comparando um pedido
sem token com outro que utiliza um token válido.

| Situação | Código HTTP | Significado |
|---|---:|---|
| Pedido sem token | 401 Unauthorized | O pedido não está autenticado |
| Pedido com token válido | 200 OK | O pedido foi aceite |

Os resultados obtidos foram `401` sem token e `200` com o token do gateway `alfa`.
Isto confirma que o endpoint exige autenticação e que o token utilizado foi aceite.
A autenticação por token permite que os gateways comuniquem com a API sem depender
de uma sessão interativa de um utilizador humano.

### 4.2. Throttling e isolamento entre gateways

A autenticação identifica o cliente, mas não impede que um gateway envie um número
excessivo de pedidos. Para reduzir o impacto de um gateway com comportamento
defeituoso, a API utiliza throttling, que limita a frequência dos pedidos.

Este mecanismo está relacionado com o padrão de resiliência *bulkhead* (B8):
pretende limitar o impacto de um componente sobre os restantes e ajudar a preservar
a disponibilidade do serviço. Por exemplo, um gateway que envie milhares de pedidos
por segundo não deve conseguir consumir indefinidamente os recursos disponíveis.

O limite de pedidos pode ser configurado através da variável de ambiente
`THROTTLE_RATE`. Para testar o mecanismo, foi definido temporariamente o limite
`5/min`, ou seja, cinco pedidos por minuto para a taxa configurada. O valor foi
confirmado dentro do contentor `portal`.

Foram efetuados oito pedidos consecutivos autenticados ao endpoint
`/api/v1/readings/?limit=1`, utilizando um token criado para o teste.

Resultado observado:

```text
200 200 200 200 200 429 429 429
```

| Pedidos | Resultado | Interpretação |
|---|---|---|
| 1.º ao 5.º | 200 OK | Pedidos aceites |
| 6.º ao 8.º | 429 Too Many Requests | Pedidos limitados por throttling |

As cinco primeiras chamadas foram aceites e as três seguintes receberam `429`.
Este resultado demonstra que o limite configurado foi aplicado durante o teste.

O enunciado refere especificamente o throttling por token. Para demonstrar que
as quotas são independentes entre gateways, é necessário testar os dois tokens
separadamente: depois de esgotar a quota de um gateway, deve verificar-se se o
outro consegue continuar a efetuar pedidos. O teste apresentado acima utiliza
apenas um token e, por isso, não permite concluir isoladamente que essa separação
de quotas está garantida.

Depois do teste, a configuração temporária deve ser removida e a configuração
normal do ambiente restaurada.

### 4.3. Geração e validação do contrato OpenAPI

A API utiliza `drf-spectacular` para gerar a especificação OpenAPI a partir da
implementação Django REST Framework. A documentação interativa está disponível
em:

`http://localhost:8080/api/schema/swagger-ui/`

O esquema OpenAPI descreve o contrato disponibilizado aos clientes, incluindo
os endpoints, os métodos HTTP, os parâmetros, os formatos dos pedidos e das
respostas e os requisitos de autenticação. Esta informação permite que os
programadores conheçam a interface da API sem terem de analisar toda a
implementação interna do servidor.

A validação foi realizada com o seguinte comando:

```powershell
docker compose exec -T portal python manage.py spectacular --validate --file /tmp/openapi.yaml
```

O comando terminou sem apresentar avisos no output observado. O ficheiro gerado
foi posteriormente copiado para `docs/openapi.yaml`, para ficar disponível na
documentação do projeto.

A geração e validação do esquema contribuem para manter o contrato documentado
e facilitar a integração de clientes. No entanto, a validação OpenAPI não substitui
os testes funcionais: não demonstra, por si só, que todos os endpoints se comportam
corretamente em execução.

### 4.4. Comparação entre OpenAPI e `.proto`

O OpenAPI e o Protocol Buffers (`.proto`) permitem definir contratos entre
serviços, mas são normalmente utilizados em contextos diferentes.

#### OpenAPI

O OpenAPI é utilizado sobretudo para descrever APIs HTTP, nomeadamente APIs REST.
Especifica caminhos, métodos HTTP, parâmetros, esquemas de dados, códigos de
resposta e mecanismos de autenticação.

Uma das suas principais vantagens é a integração natural com HTTP e JSON. A
documentação pode ser explorada através de ferramentas como o Swagger UI, e a
especificação pode ser utilizada para gerar documentação e clientes em diferentes
linguagens.

A sua flexibilidade facilita a integração com aplicações web e serviços que já
comunicam através de HTTP. Por outro lado, a especificação descreve o contrato
da API, mas não garante automaticamente que a implementação respeita todos os
comportamentos documentados. Essa correspondência tem de ser mantida através
de validações e testes.

#### Protocol Buffers e `.proto`

Um ficheiro `.proto` define explicitamente mensagens, campos, tipos de dados e,
quando utilizado com gRPC, serviços e métodos remotos. A partir dessa definição
podem ser gerados tipos e código para clientes e servidores.

Esta abordagem fornece um contrato tipado e estruturado, favorecendo a
consistência entre as implementações e detetando várias incompatibilidades
durante a geração de código ou a compilação. É especialmente útil na comunicação
entre serviços que utilizam gRPC.

Em contrapartida, exige ferramentas e suporte específicos para Protocol Buffers
e gRPC. A interface também não é tão diretamente explorável através de um
navegador como uma API REST documentada com Swagger UI.

#### Qual é o contrato mais estrito?

O `.proto` tende a ser mais estrito na definição das mensagens e dos tipos,
sobretudo quando é utilizado para gerar código gRPC para clientes e servidores.
Os campos e os tipos são definidos explicitamente numa estrutura comum.

O OpenAPI também permite descrever esquemas, tipos, parâmetros e respostas, mas
a força do contrato depende da especificação produzida e de como os clientes e
o servidor a validam. Assim, não se deve concluir que o OpenAPI não permite
validação de tipos; a diferença está sobretudo no modelo de comunicação, nas
ferramentas e no grau de integração do contrato com a geração de código.

#### O que se ganha e o que se perde?

| Aspeto | OpenAPI / REST | `.proto` / gRPC |
|---|---|---|
| Comunicação | HTTP e recursos REST | Normalmente gRPC e chamadas a métodos |
| Definição do contrato | Endpoints, parâmetros, respostas e esquemas | Mensagens, campos, tipos e serviços |
| Tipagem | Esquemas descritos na especificação | Mensagens explicitamente tipadas |
| Ferramentas | Swagger UI, documentação e geração de clientes | Compilador Protocol Buffers e geração de código |
| Integração web | Direta e amplamente acessível | Exige suporte adequado para gRPC |
| Utilização típica | APIs públicas, aplicações web e integrações HTTP | Comunicação tipada entre serviços |

No contexto do SIVIT, o OpenAPI é adequado para publicar e explorar a API REST,
documentar os endpoints e facilitar a integração dos gateways. Se o sistema
necessitar de comunicação gRPC entre serviços, com contratos de mensagens
fortemente tipados e geração de código, o `.proto` poderá ser uma alternativa
mais adequada para essa comunicação.

Conclui-se que nenhum dos formatos é universalmente superior. A escolha depende
dos requisitos de interoperabilidade, das ferramentas disponíveis e do tipo de
comunicação pretendido.
