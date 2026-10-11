"""Job creation and (background) certificate generation."""
import logging
import threading

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import Certificate, Job
from .pdf import render_certificate
from .serializers import RecipientSerializer

log = logging.getLogger(__name__)


def _flatten_errors(errors: dict) -> str:
    parts = []
    for field, msgs in errors.items():
        label = "recipient" if field == "non_field_errors" else field
        text = "; ".join(str(m) for m in msgs) if isinstance(msgs, (list, tuple)) else str(msgs)
        parts.append(f"{label}: {text}")
    return "; ".join(parts)


def job_counts(job_id) -> dict:
    return Certificate.objects.filter(job_id=job_id).aggregate(
        total=Count("id"),
        succeeded=Count("id", filter=Q(status=Certificate.SUCCESS)),
        failed=Count("id", filter=Q(status=Certificate.FAILED)),
        pending=Count("id", filter=Q(status=Certificate.PENDING)),
    )


def finalise_if_done(job: Job) -> None:
    """Set the terminal status once no pending certificates remain."""
    n = job_counts(job.id)
    if n["pending"]:
        return
    if n["succeeded"] == n["total"]:
        job.status = Job.COMPLETED
    elif n["succeeded"] == 0:
        job.status = Job.FAILED
    else:
        job.status = Job.COMPLETED_WITH_ERRORS
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "completed_at"])


@transaction.atomic
def create_job(data: dict) -> Job:
    """Persist the job and one row per recipient.

    Recipients failing validation are stored immediately as failed rows (with the
    reason, and whatever name/email the client sent); valid ones are stored as
    pending for the worker.
    """
    info = data["certificate"]
    job = Job.objects.create(
        title=info["title"],
        course_name=info["course_name"],
        issued_by=info["issued_by"],
        issue_date=info["issue_date"],
    )
    rows = []
    for position, raw in enumerate(data["recipients"]):
        cert = Certificate(job=job, position=position)
        s = RecipientSerializer(data=raw)
        if s.is_valid():
            cert.recipient_name = s.validated_data["name"]
            cert.recipient_email = s.validated_data.get("email")
        else:
            cert.status = Certificate.FAILED
            cert.error = _flatten_errors(s.errors)
            if isinstance(raw, dict):  # keep what was sent so the failure is identifiable
                name, email = raw.get("name"), raw.get("email")
                cert.recipient_name = name[:200] if isinstance(name, str) else None
                cert.recipient_email = email[:320] if isinstance(email, str) else None
        rows.append(cert)
    Certificate.objects.bulk_create(rows)
    finalise_if_done(job)
    return job


def generate_one(job: Job, cert: Certificate):
    """Generate one certificate file. Separate function so tests can make it fail."""
    path = settings.CERTGEN_STORAGE_DIR / str(job.id) / f"{cert.id}.pdf"
    render_certificate(
        path,
        recipient_name=cert.recipient_name,
        title=job.title,
        course_name=job.course_name,
        issued_by=job.issued_by,
        issue_date=job.issue_date,
    )
    return path


def process_job(job_id) -> None:
    """Generate every pending certificate of a job.

    Each certificate is saved on its own, so progress is visible while the job
    runs and an exception on one certificate is recorded without stopping the
    rest. Re-running is safe: only 'pending' rows are processed.
    """
    try:
        job = Job.objects.get(pk=job_id)
    except Job.DoesNotExist:
        return
    if job.status == Job.QUEUED:
        job.status = Job.PROCESSING
        job.save(update_fields=["status"])

    for cert in list(job.certificates.filter(status=Certificate.PENDING).order_by("position")):
        try:
            path = generate_one(job, cert)
            cert.status, cert.file_path, cert.error = Certificate.SUCCESS, str(path), None
        except Exception as exc:  # noqa: BLE001 - isolate any per-certificate failure
            log.exception("certificate %s failed", cert.id)
            cert.status, cert.error = Certificate.FAILED, f"generation failed: {exc}"
        cert.save(update_fields=["status", "file_path", "error"])

    finalise_if_done(job)


def _thread_target(job_id) -> None:
    try:
        process_job(job_id)
    except Exception:  # noqa: BLE001
        log.exception("job %s crashed", job_id)
    finally:
        connection.close()  # each thread owns its DB connection


def enqueue(job_id) -> None:
    """Run the job in the background (or inline when CERTGEN_RUN_SYNC is set)."""
    if settings.CERTGEN_RUN_SYNC:
        process_job(job_id)
    else:
        threading.Thread(target=_thread_target, args=(job_id,), daemon=True).start()
