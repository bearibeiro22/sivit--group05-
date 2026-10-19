"""Router de leitura e escrita, usado a partir de TP7.

Só entra em vigor quando existe REPLICA_URL no ambiente. Em TP2 o portal tem
uma só base de dados e este ficheiro não é usado.
"""


class RouterLeituraEscrita:
    def db_for_read(self, model, **hints):
        return "replica"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, *a, **kw):
        return True

    def allow_migrate(self, db, *a, **kw):
        return db == "default"
