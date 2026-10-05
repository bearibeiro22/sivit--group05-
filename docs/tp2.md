## Exercício 2: Isolamento da Camada de Dados
### 1. **Tipo de Falha:** 
De acordo com a taxonomia estudada, trata-se de uma falha de *Crash* (falha por paragem) do lado da base de dados, pois o serviço foi interrompido abruptamente e deixou de responder aos pedidos do portal.
### 2. **Compreensão do Erro:** 
O erro apresentado não é compreensível para um utilizador final. Como a aplicação está em modo `DEBUG=True`, o Django devolve um *Stack Trace* detalhado com caminhos de ficheiros internos, o que num ambiente de produção representaria uma grave falha de segurança.
### 3. **Recuperação:** 
A recuperação foi imediata e autónoma. Assim que o contentor `sivitDB` foi reiniciado, a aplicação voltou a processar o login com sucesso no *refresh* seguinte, sem necessidade de reiniciar o portal.




## Exercício 3 - A Stack de Produção

### 1. Identificação das três camadas do B2 na stack e partilha de contentores
* **Camada de Apresentação (Presentation Tier):** Nginx (que serve ficheiros estáticos e atua como *Reverse Proxy*).
* **Camada de Aplicação/Processamento (Application/Logic Tier):** Gunicorn + Django (executa a lógica de negócio).
* **Camada de Dados (Data Tier):** PostgreSQL (armazena os dados persistentes).

**Partilha de Contentores:** O **Gunicorn** e o **Django** partilham o mesmo contentor (o serviço `portal`). Isto acontece porque o Gunicorn é um servidor WSGI HTTP em Python que carrega e executa diretamente o runtime da aplicação Django no mesmo ambiente/processo de execução.

---

### 2. Modelo de Concorrência do `--workers 3`
* **Modelo de Concorrência:** Trata-se de um modelo de **Múltiplos Processos (Pre-fork worker model)** de B3.
* **Pedidos Simultâneos:** O Gunicorn cria 3 processos *workers* independentes e isolados. Por isso, consegue processar exatamente **3 pedidos simultâneos** em paralelo (um pedido por *worker*).

---

### 3. Servir ficheiros estáticos pelo Nginx em vez do Django
Os ficheiros estáticos (CSS, JS, Imagens) são servidos diretamente pelo Nginx pelos seguintes motivos:
* **Eficiência e Desempenho:** O Nginx é um servidor de alto rendimento otimizado para operações de I/O de ficheiros estáticos (como *sendfile*), consumindo significativamente menos memória e CPU.
* **Libertação de Recursos do Django:** Se o Django estivesse a servir ficheiros estáticos, estaria a ocupar um dos 3 *workers* do Gunicorn para entregar um ficheiro CSS ou JS, impedindo que esse *worker* processasse pedidos dinâmicos de lógica de negócio e consultas à base de dados.

---

### 4. Importância da diretiva `proxy_read_timeout 10s`
Se o Django/Gunicorn bloquear ou demorar excessivamente a responder e **não existir** a diretiva `proxy_read_timeout 10s`:
* A ligação entre o Nginx e o utilizador ficaria **bloqueada indefinidamente** (ou até ao timeout global do SO), mantendo recursos da rede e do servidor pendurados sem dar feedback.
* **Com a diretiva ativada:** Se o Django demorar mais do que 10 segundos a responder, o Nginx corta o pedido pendente e devolve imediatamente ao cliente um erro `504 Gateway Timeout`, libertando a ligação e informando o cliente de forma clara que o serviço falhou.




## Exercício 4 - O Efeito N+1

| Versão | Número de Queries | Tempo Total (ms) |
| :--- | :---: | :---: |
| Naive (Ingénua) | 7 | 38.08 |
| + select_related | 5 | 40.94 |
| + prefetch_related | 4 | 47.55 |
| + subquery para a última leitura | 2 | 40.34 |