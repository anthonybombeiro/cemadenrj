from rest_framework.pagination import LimitOffsetPagination


class SafeLimitOffsetPagination(LimitOffsetPagination):
    """Mesma paginação padrão do DRF, mas com um teto pro `?limit=`.

    Sem `max_limit`, um cliente pedindo `?limit=1000` (era o que o
    frontend fazia em `fetchStations()`) contorna o `PAGE_SIZE` e faz o
    Django montar/serializar todas as ~670+ estações (e suas leituras
    recentes) numa passada só — no processo CGI do HostGator (recursos de
    plano compartilhado, sem tuning de servidor dedicado) isso já bateu
    erro 500 por estourar limite de tempo/memória do processo (medido em
    produção em 2026-09-23: ~13ms/estação, ~600 estações ainda respondia
    em 8s, 670 já estourava). 300 é um teto testado como seguro; qualquer
    endpoint com mais itens que isso PRECISA paginar de verdade (seguir o
    `next` da resposta) em vez de pedir tudo de uma vez — ver
    `fetchAllPages()` em frontend/src/lib/api.ts.
    """

    max_limit = 300
