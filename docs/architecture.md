# Arquitetura do portal SIVIT

Dois diagramas, separados de propósito: o primeiro mostra a organização do **código** (módulos e
dependências), o segundo mostra **onde corre** cada coisa (contentores, rede e volumes).

## 1. Diagrama de software

```mermaid
flowchart TB
  subgraph APRES["Apresentação"]
    TPL["templates/ (base.html, painel.html)"]
  end
  subgraph PROC["Processamento (Django)"]
    URL["urls.py"]
    VIEW["views.py (painel, saude)"]
    MID["middleware.py (latência artificial)"]
    SRV["services.py (regras de domínio, sem HTTP)"]
  end
  subgraph DADOS["Dados"]
    MOD["models.py (Doente, Internamento, Dispositivo, Leitura)"]
  end
  URL --> VIEW
  MID -.->|"em torno de cada pedido"| VIEW
  VIEW --> TPL
  VIEW --> MOD
  SRV -.->|"reutilizado pela API (TP3) e pelo consumidor de fila (TP5)"| MOD
```

As views falam com os modelos e com os *templates*. O `services.py` contém a lógica de domínio sem HTTP
(por exemplo `registar_leitura`, idempotente graças à restrição `uniq_leitura`), para que a API e o
consumidor de fila a reutilizem sem depender do Django HTTP.

## 2. Diagrama de sistema

```mermaid
flowchart LR
  B["Browser"] -->|"HTTP, porta 8080"| NG
  subgraph COMPOSE["docker compose (rede tp2_default)"]
    NG["nginx (nginx:alpine)"]
    P["portal: Gunicorn (3 workers) + Django"]
    DB[("sivitDB: postgres:16-alpine")]
    VS[("volume static_files")]
    VD[("volume db_data")]
  end
  NG -->|"proxy_pass portal:8000 (timeout 10 s)"| P
  P -->|"TCP 5432, por nome"| DB
  P -->|"collectstatic escreve"| VS
  NG -->|"serve /static/ (só leitura)"| VS
  DB --- VD
```

Só o Nginx publica uma porta para fora (8080). O portal e a base de dados só são alcançáveis
dentro da rede do Compose, e comunicam por nome (`portal`, `sivitDB`). O volume `db_data` guarda
os dados da BD fora do ciclo de vida do contentor, e o `static_files` é partilhado entre portal
(escreve) e Nginx (lê).
