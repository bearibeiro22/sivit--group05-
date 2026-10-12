# TP2 - Resolução

Plataforma: Windows com Docker Desktop (backend WSL2). Código em `beatriz/tp2/`: projeto
`config` e app `vigilancia`. Só dados sintéticos.

## Exercício 1 

```
Doente (1) ──< Internamento (1) ──< Dispositivo (1) ──< Leitura
```

Cada classe em `vigilancia/models.py` é uma tabela. A migração `0001_initial.py` foi gerada
dentro do contentor (`makemigrations`) e está no Git, para que todos os ambientes fiquem com o
mesmo esquema.

O `on_delete` de cada `ForeignKey` é uma decisão de desenho:

| Relação | `on_delete` | Porquê |
| --- | --- | --- |
| Internamento → Doente | `PROTECT` | não se apaga um doente que tenha internamentos |
| Dispositivo → Internamento | `SET_NULL` | o dispositivo continua a existir depois da alta |
| Leitura → Dispositivo | `CASCADE` | uma leitura sem o dispositivo não significa nada |

A restrição `UniqueConstraint(dispositivo, instante, parametro)` é o que torna a ingestão
**idempotente** (B7). Se um monitor envia uma leitura e a resposta se perde (timeout), o
monitor volta a enviá-la. Sem a restrição, a leitura ficava duplicada. Com ela, a base de
dados recusa o duplicado e a repetição é inofensiva. É a base de dados a garantir a regra, e
não o código: a regra continua a valer mesmo com várias réplicas do portal a escrever ao
mesmo tempo.

O índice `(dispositivo, -instante)` serve a pergunta "qual é a última leitura de cada
dispositivo?", que é a pergunta que o painel faz no exercício 4.

