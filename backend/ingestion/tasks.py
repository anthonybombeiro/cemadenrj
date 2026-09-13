import logging

from celery import shared_task

from .connectors import get_connector

logger = logging.getLogger("ingestion")


@shared_task
def ingest_source(slug: str) -> str:
    connector = get_connector(slug)
    result = connector.run()
    logger.info("Ingestão %s concluída: %s", slug, result.summary())
    return result.summary()
