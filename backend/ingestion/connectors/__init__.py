from .alerta_rio import AlertaRioConnector
from .base import BaseConnector, IngestResult
from .cemaden_nacional import CemadenNacionalConnector
from .cemaden_rj_pluviometros import CemadenMcticConnector
from .inea import INEAConnector
from .inmet import InmetConnector
from .niteroi import NiteroiConnector
from .plugfield import PlugfieldConnector
from .rio_chuva_bairro import RioChuvaBairroConnector
from .wunderground import WundergroundConnector

# CemadenRJConnector (cemaden_rj_pluviometros.py) foi RETIRADO do REGISTRY
# em 2026-09-23: era a página pública do portal de sirenes (só as 85
# estações com pluviômetro, coordenada aproximada pelo centroide do
# município). Confirmado que as mesmas 85 estações (external_id idêntico
# nos dois) já vêm melhores pelo cemaden_rj_sirenes.py (autenticado):
# coordenada EXATA, mesma leitura de chuva, e ainda traz as outras 140
# sirenes sem pluviômetro + status de acionamento. Duas fontes pra dado
# idêntico só causava confusão na tabela (pedido do usuário: "deveria ser
# igual") — mantido o arquivo/classe pra referência, mas fora de uso.
REGISTRY: dict[str, type[BaseConnector]] = {
    InmetConnector.slug: InmetConnector,
    CemadenNacionalConnector.slug: CemadenNacionalConnector,
    AlertaRioConnector.slug: AlertaRioConnector,
    WundergroundConnector.slug: WundergroundConnector,
    RioChuvaBairroConnector.slug: RioChuvaBairroConnector,
    PlugfieldConnector.slug: PlugfieldConnector,
    CemadenMcticConnector.slug: CemadenMcticConnector,
    NiteroiConnector.slug: NiteroiConnector,
    INEAConnector.slug: INEAConnector,
}


def get_connector(slug: str) -> BaseConnector:
    try:
        connector_cls = REGISTRY[slug]
    except KeyError as exc:
        raise ValueError(
            f"Conector '{slug}' não encontrado. Disponíveis: {', '.join(REGISTRY)}"
        ) from exc
    return connector_cls()


__all__ = ["BaseConnector", "IngestResult", "REGISTRY", "get_connector"]
