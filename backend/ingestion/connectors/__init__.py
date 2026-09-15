from .alerta_rio import AlertaRioConnector
from .base import BaseConnector, IngestResult
from .cemaden_nacional import CemadenNacionalConnector
from .inmet import InmetConnector
from .plugfield import PlugfieldConnector
from .rio_chuva_bairro import RioChuvaBairroConnector
from .wunderground import WundergroundConnector

REGISTRY: dict[str, type[BaseConnector]] = {
    InmetConnector.slug: InmetConnector,
    CemadenNacionalConnector.slug: CemadenNacionalConnector,
    AlertaRioConnector.slug: AlertaRioConnector,
    WundergroundConnector.slug: WundergroundConnector,
    RioChuvaBairroConnector.slug: RioChuvaBairroConnector,
    PlugfieldConnector.slug: PlugfieldConnector,
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
