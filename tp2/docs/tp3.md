# TP3 — REST API, Idempotência e Paginação

## 1. Objetivos

Nesta TP foi desenvolvida uma API REST para o sistema SIVIT, utilizando Django REST Framework. Os principais objetivos são:

- Disponibilizar uma API versionada através de `/api/v1/`.
- Definir recursos REST para pacientes, internamentos, dispositivos e leituras.
- Implementar serialização e validação dos dados recebidos.
- Garantir a idempotência da ingestão de leituras e de operações que possam ser repetidas.
- Implementar paginação e analisar o impacto da sua ausência.
- Proteger a API através de autenticação por token e limitação de pedidos.
- Disponibilizar documentação OpenAPI através do Swagger UI.

## 2. Desenho da API

### 2.1. Recursos e endpoints

A API disponibiliza os seguintes recursos:

| Recurso | Endpoint | Operações |
|---|---|---|
| Pacientes | `/api/v1/patients/` | GET, POST |
| Internamentos | `/api/v1/admissions/` | GET, POST, PATCH |
| Dispositivos | `/api/v1/devices/` | GET, POST, PATCH |
| Leituras | `/api/v1/readings/` | GET, POST |
| Leituras de um dispositivo | `/api/v1/devices/{id}/readings/` | GET |
| Leitura mais recente | `/api/v1/devices/{id}/readings/latest/` | GET |

A utilização do prefixo `/api/v1/` permite identificar a versão do contrato da API. Esta abordagem facilita futuras alterações sem obrigar todos os clientes a atualizar simultaneamente. Por exemplo, gateways que utilizem a versão 1 podem continuar a funcionar enquanto uma eventual versão 2 introduz alterações incompatíveis.

### 2.2. Serialização e validação

Os serializers convertem os objetos do modelo Django em representações JSON e validam os dados recebidos pelos endpoints.

Na ingestão de leituras, a API deve validar os campos obrigatórios, os tipos de dados e os valores plausíveis dos parâmetros fisiológicos. Os limites definidos no enunciado são:

| Parâmetro | Valor mínimo | Valor máximo |
|---|---:|---:|
| HR | 20 | 250 |
| SPO2 | 50 | 100 |
| TEMP | 30 | 45 |

Os limites devem ser aplicados de acordo com o parâmetro recebido. Um valor fora do intervalo admissível deve ser rejeitado com um erro de validação.

O dispositivo pode ser identificado pelo seu número de série, em vez de expor o identificador interno da base de dados. Esta abordagem reduz o acoplamento dos clientes à estrutura interna do sistema.

## 3. Exercício 2 — Idempotência

### 3.1. Problema da repetição de pedidos

Um cliente pode enviar um lote de leituras e não receber a resposta devido a uma falha de comunicação. Sem saber se o servidor processou o pedido, o cliente pode voltar a enviá-lo.

Se o servidor processar todas as tentativas como novas operações, podem ser criados registos duplicados. Por isso, a API deve garantir que repetir a mesma ingestão não produz leituras duplicadas.

### 3.2. Restrição de unicidade nas leituras

A restrição de unicidade sobre `(device, instant, parameter)` impede a criação de leituras duplicadas para o mesmo dispositivo, instante e parâmetro.

Na ingestão em lote, a utilização de `bulk_create(..., ignore_conflicts=True)` permite ignorar conflitos com registos já existentes, desde que a restrição de unicidade correspondente esteja definida na base de dados.

Assim, o cliente pode repetir o envio de um lote sem duplicar as leituras que já tenham sido persistidas.

### 3.3. Chaves de idempotência

A restrição de unicidade das leituras não resolve todos os casos. Existem operações que não possuem uma chave natural adequada, como o reconhecimento de um alarme.

Para esses casos, foi utilizada a abordagem de uma chave de idempotência, representada pelo modelo `IdempotencyKey`. O registo armazena a chave, a resposta da operação, o respetivo código HTTP e a data de criação.

O processamento segue estes passos:

1. O servidor recebe o pedido e a chave de idempotência.
2. Procura uma resposta previamente armazenada para essa chave.
3. Se a chave já existir, devolve a resposta armazenada sem executar novamente a operação.
4. Caso contrário, executa a operação e guarda a resposta na mesma transação.
5. Se ocorrer um conflito concorrente na criação da chave, procura a resposta já persistida.

A chave é associada ao utilizador autenticado, evitando que utilizadores diferentes partilhem inadvertidamente o mesmo espaço de chaves.

### 3.4. Respostas às questões do exercício 2

**1. Que semântica de falhas foi implementada: at-least-once, at-most-once ou exactly-once?**

A abordagem permite que o cliente volte a enviar pedidos quando não recebe uma resposta, o que corresponde a uma estratégia de entrega *at-least-once*. A restrição de unicidade e as chaves de idempotência evitam repetir determinados efeitos persistentes.

Não é correto afirmar que existe *exactly-once* de forma absoluta: podem ocorrer repetições de pedidos, falhas de comunicação ou efeitos externos que não sejam abrangidos pela mesma transação. A garantia é limitada às operações e aos efeitos persistentes efetivamente protegidos pela implementação.

**2. A restrição UNIQUE e a chave de idempotência resolvem o mesmo problema? Quando funciona apenas uma delas?**

Não. A restrição `UNIQUE(device, instant, parameter)` evita duplicações de leituras com a mesma combinação de dispositivo, instante e parâmetro. É adequada quando existe uma chave natural que identifica univocamente um registo.

A chave de idempotência identifica uma operação através de uma chave fornecida pelo cliente e permite devolver a resposta anteriormente armazenada. É útil para operações sem uma chave natural adequada, como o reconhecimento de um alarme.

A restrição `UNIQUE` não garante, por si só, que a resposta original de uma operação seja devolvida. Por sua vez, uma chave de idempotência não substitui as restrições de integridade da base de dados.

**3. Se a resposta armazenada for escrita fora da transação da operação, que falha se torna possível?**

A operação pode ser concluída e persistida, mas o processo falhar antes de guardar a resposta associada à chave. Quando o cliente repetir o pedido, o servidor pode não encontrar a chave e executar novamente a operação.

Por isso, a operação e o registo da resposta devem ser protegidos pela mesma transação, sempre que ambos dependam da mesma base de dados.

**4. Durante quanto tempo deve ser conservada uma chave de idempotência? Qual é a desvantagem?**

A chave deve ser conservada durante, pelo menos, o período máximo em que o cliente pode repetir legitimamente um pedido. Esse período depende dos tempos de recuperação, das políticas de repetição e dos requisitos do sistema.

Uma retenção mais longa reduz o risco de executar novamente operações antigas, mas aumenta o espaço ocupado na base de dados. Uma retenção demasiado curta diminui esse custo, mas permite que um pedido repetido depois da expiração volte a executar a operação.

A política de retenção deve, portanto, equilibrar segurança contra duplicações, espaço de armazenamento e comportamento esperado dos clientes.

## 4. Exercício 3 — Paginação e desempenho

### 4.1. Metodologia

Os testes foram realizados sobre 50 000 leituras associadas ao dispositivo com ID 1.

Foram comparadas três abordagens:

- **Sem paginação:** devolução de todas as leituras através de `?all=1`.
- **Offset:** utilização de `?page=N`, com 100 registos por página.
- **Cursor:** utilização de `?after=<instant>&limit=100`, para obter um conjunto limitado de leituras a partir de um instante.

Foram realizadas cinco medições por cenário, precedidas por uma chamada de aquecimento não contabilizada. Os valores apresentados correspondem à mediana dos tempos medidos dentro do Django, sem incluir a latência de rede.

### 4.2. Resultados experimentais

| Estratégia | Primeira página / consulta | Consulta próxima da página 500 | Tamanho da resposta |
|---|---:|---:|---:|
| Sem paginação | 2078,12 ms | — | 4 850 027 bytes |
| Offset | 12,06 ms | 30,70 ms | 9 804 bytes / 9 806 bytes |
| Cursor | 7,49 ms | 8,87 ms | 9 749 bytes / 9 749 bytes |

Na abordagem sem paginação, foram devolvidos 50 000 registos. Nas restantes consultas foram devolvidos 100 registos por pedido.

### 4.3. Análise dos resultados

A consulta sem paginação apresentou o pior desempenho, demorando 2078,12 ms, aproximadamente 2,08 segundos, e produzindo uma resposta com 4 850 027 bytes. O envio de todos os registos num único pedido aumenta o volume de dados a serializar e transferir.

Na paginação por offset, o tempo mediano aumentou de 12,06 ms na primeira página para 30,70 ms na página 500. Este comportamento é compatível com o custo de percorrer e ignorar os registos anteriores à página pretendida.

Na paginação por cursor, o tempo mediano foi de 7,49 ms na primeira consulta e 8,87 ms numa consulta próxima da posição da página 500. A diferença foi inferior à observada entre as duas consultas por offset.

As respostas paginadas tiveram aproximadamente 9,7 a 9,8 KB, muito menos do que a resposta sem paginação. Os resultados indicam que limitar o número de registos devolvidos por pedido reduz significativamente o volume de dados e o tempo de resposta.

Estes valores correspondem a medições dentro do Django e não incluem a latência de rede. Além disso, a consulta por cursor próxima da página 500 é uma consulta isolada nessa posição, não o tempo acumulado de percorrer as primeiras 500 páginas.

### 4.4. Conclusão sobre a paginação

Nos testes realizados, a paginação por cursor apresentou os menores tempos medianos. A paginação por offset também reduziu substancialmente o tempo de resposta face à consulta sem paginação, mas apresentou um aumento de latência na página 500.

A paginação é, por isso, essencial quando uma API disponibiliza grandes volumes de dados. Permite limitar o tamanho das respostas e evitar que um único pedido exija a serialização de dezenas de milhares de registos.

Existe ainda uma consideração de implementação: o cursor atual utiliza apenas o campo `instant` como critério de continuação, enquanto a ordenação utiliza `-instant` e `-id`. Se existirem várias leituras com o mesmo instante, esta implementação pode saltar registos. Para garantir uma paginação consistente, o cursor deve incluir ambos os campos, utilizando uma condição de continuação que considere o instante e o identificador.

## 5. Exercício 4 — Autenticação, throttling e OpenAPI

### 5.1. Autenticação

A API utiliza autenticação por token através de `TokenAuthentication`, permitindo autenticar clientes de máquina, como gateways de aquisição de dados.

A autenticação por token é distinta da autenticação por sessão utilizada por utilizadores humanos através de uma interface web. Esta separação é importante porque os gateways precisam de enviar pedidos automaticamente, sem depender de uma sessão interativa.

A API está configurada para exigir autenticação nos endpoints protegidos. Um pedido sem credenciais válidas deve ser rejeitado.

### 5.2. Throttling

O throttling limita a frequência dos pedidos recebidos e ajuda a proteger o serviço contra gateways com comportamento anómalo ou excessivo.

A configuração utilizada define uma taxa de referência de cinco pedidos por minuto para o `UserRateThrottle`. Quando o limite aplicável é excedido, a API pode responder com o código HTTP `429 Too Many Requests`.

Num teste com dez pedidos, foram observadas oito respostas `200` e duas respostas `429`, tendo a primeira resposta `429` ocorrido no nono pedido. Este resultado corresponde ao teste executado; não deve ser interpretado como garantia de que todos os conjuntos de dez pedidos terão exatamente a mesma distribuição de respostas, uma vez que o throttling depende do estado e da janela temporal aplicáveis.

A configuração utiliza `UserRateThrottle`, pelo que o limite é associado ao utilizador autenticado. Para obter isolamento rigoroso por token, mesmo quando vários tokens pertencem ao mesmo utilizador, seria necessário implementar ou configurar uma política de throttling especificamente baseada no token.

### 5.3. OpenAPI e Swagger UI

A documentação da API é gerada com `drf-spectacular`, que permite descrever os endpoints, os métodos HTTP, os parâmetros, os serializers e os esquemas de resposta.

A interface Swagger UI é disponibilizada em:

`/api/schema/swagger-ui/`

A especificação OpenAPI constitui um contrato legível por ferramentas e programadores. Permite consultar os recursos disponíveis, compreender os formatos dos pedidos e das respostas e facilitar a integração de clientes.

A documentação reduz a necessidade de consultar diretamente o código-fonte para compreender a interface disponibilizada pelo serviço.

### 5.4. Comparação entre OpenAPI e `.proto`

OpenAPI e Protocol Buffers podem ser utilizados para definir contratos entre serviços, mas apresentam características diferentes.

| Critério | OpenAPI | Protocol Buffers (`.proto`) |
|---|---|---|
| Utilização típica | APIs REST sobre HTTP | Comunicação estruturada, frequentemente com gRPC |
| Formato dos dados | Normalmente JSON | Formato binário Protobuf |
| Definição do contrato | Esquemas, endpoints, parâmetros e respostas | Mensagens, campos, tipos e serviços |
| Legibilidade | A especificação e os exemplos JSON são facilmente inspecionáveis | A definição `.proto` é legível, mas as mensagens transmitidas são normalmente binárias |
| Tipagem | Tipos e validações definidos pelo esquema | Tipagem explícita dos campos e números de campo |
| Geração de clientes | Suportada por ferramentas OpenAPI | Suportada por compiladores e ferramentas Protobuf/gRPC |
| Compatibilidade | Depende da evolução dos endpoints e dos esquemas | Depende das regras de evolução dos campos e dos serviços |

O OpenAPI é adequado à documentação e integração de APIs REST, sobretudo quando a interoperabilidade com clientes HTTP e ferramentas web é importante. O `.proto` oferece um contrato mais explícito para mensagens e serviços e integra-se diretamente com ferramentas Protobuf e gRPC.

O formato binário Protobuf pode reduzir o tamanho das mensagens e o custo de serialização em determinados cenários. No entanto, a vantagem real depende dos dados, do transporte e da implementação, pelo que deve ser confirmada através de medições.

Em contrapartida, o JSON utilizado habitualmente com REST é mais fácil de inspecionar manualmente e de depurar com ferramentas HTTP comuns. A escolha depende dos requisitos de interoperabilidade, desempenho, simplicidade e evolução do contrato.

## 6. Conclusão geral

A TP3 desenvolve a API REST do SIVIT, acrescentando mecanismos de validação, idempotência, paginação, autenticação, controlo de frequência e documentação.

A idempotência é importante para tolerar repetições de pedidos sem duplicar os efeitos persistentes protegidos. A paginação reduz o tamanho das respostas e, nos testes realizados, a estratégia por cursor apresentou os menores tempos medianos. A autenticação por token e o throttling contribuem para proteger o serviço, enquanto a especificação OpenAPI facilita a utilização da API por outros componentes do sistema.

A API versionada e documentada constitui uma base para a integração com gateways e serviços futuros, permitindo evoluir o sistema com um contrato explícito e com maior controlo sobre o comportamento dos pedidos.