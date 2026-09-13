from django.core.management.base import BaseCommand, CommandError

from ingestion.connectors import REGISTRY, get_connector


class Command(BaseCommand):
    help = "Roda a ingestão de uma (ou todas as) fontes de dados externas."

    def add_arguments(self, parser):
        parser.add_argument(
            "source",
            nargs="?",
            default="all",
            help=f"Slug da fonte ({', '.join(REGISTRY)}) ou 'all' para todas.",
        )

    def handle(self, *args, **options):
        slug = options["source"]
        slugs = list(REGISTRY) if slug == "all" else [slug]

        for s in slugs:
            if s not in REGISTRY:
                raise CommandError(f"Fonte desconhecida: {s}. Disponíveis: {', '.join(REGISTRY)}")
            self.stdout.write(f"Ingerindo '{s}'...")
            result = get_connector(s).run()
            self.stdout.write(self.style.SUCCESS(f"  {s}: {result.summary()}"))
            if result.errors:
                for err in result.errors:
                    self.stdout.write(self.style.WARNING(f"  ! {err}"))
