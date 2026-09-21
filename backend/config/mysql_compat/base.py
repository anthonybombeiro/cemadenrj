"""Backend MySQL do Django com a exigência de versão reduzida para 5.7.

O HostGator compartilhado só oferece MySQL 5.7.44, e o Django 4.2 recusa
conectar em qualquer coisa abaixo de 8.0 ("MySQL 8 or later is required").
Este projeto não usa nenhum recurso exclusivo do MySQL 8 (funções de
janela, CTE, etc.) — só ORM básico, JSONField (existe desde 5.7.8) e
constraints únicas — então só a checagem de versão precisa ser relaxada.
Trocar para Django 4.1 seria pior: já saiu de suporte de segurança.
"""

from django.db.backends.mysql import base, features


class DatabaseFeatures(features.DatabaseFeatures):
    minimum_database_version = (5, 7)


class DatabaseWrapper(base.DatabaseWrapper):
    features_class = DatabaseFeatures
