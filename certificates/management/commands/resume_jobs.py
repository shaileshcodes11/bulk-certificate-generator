from django.core.management.base import BaseCommand

from certificates.models import Job
from certificates.services import process_job


class Command(BaseCommand):
    help = "Finish jobs left 'queued' or 'processing' (e.g. after a server restart)."

    def handle(self, *args, **options):
        ids = list(Job.objects.filter(status__in=[Job.QUEUED, Job.PROCESSING]).values_list("id", flat=True))
        for job_id in ids:
            self.stdout.write(f"Resuming {job_id} ...")
            process_job(job_id)
        self.stdout.write(self.style.SUCCESS(f"Done. {len(ids)} job(s) processed."))
