import datetime

from django.conf import settings
from django.urls import reverse
from rest_framework import serializers
from . import template_config as cfg

from .models import Certificate, Job


class CertificateInfoSerializer(serializers.Serializer):
    """Information shared by every certificate in a job."""

    title = serializers.CharField(max_length=200, default="Certificate of Completion")
    course_name = serializers.CharField(max_length=200, default=cfg.DEFAULT_COURSE_NAME)
    issued_by = serializers.CharField(max_length=200, default=cfg.DEFAULT_ISSUED_BY)
    issue_date = serializers.DateField(default=datetime.date.today)


class JobCreateSerializer(serializers.Serializer):
    """Request-level validation. Individual recipients are NOT validated here:
    each is checked separately (RecipientSerializer) so one bad entry is recorded
    as a failed certificate instead of rejecting the whole request."""

    certificate = CertificateInfoSerializer()
    recipients = serializers.ListField(child=serializers.JSONField(allow_null=True), allow_empty=False)

    def validate_recipients(self, value):
        limit = settings.CERTGEN_MAX_RECIPIENTS  # read at call time so tests can override
        if len(value) > limit:
            raise serializers.ValidationError(f"Too many recipients ({len(value)}); maximum is {limit} per job.")
        return value


class RecipientSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True, max_length=320)

    def validate_name(self, value):
        value = " ".join(value.split())
        try:
            value.encode("cp1252")
        except UnicodeEncodeError:
            raise serializers.ValidationError(
                "Name contains characters the certificate font cannot render (Latin characters only)."
            )
        return value

    def validate_email(self, value):
        return value or None


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = ["id", "status", "title", "course_name", "issued_by", "issue_date", "created_at", "completed_at"]

    def to_representation(self, job):
        from .services import job_counts  # local import avoids a circular import

        data = super().to_representation(job)
        n = job_counts(job.id)
        done = n["succeeded"] + n["failed"]
        data.update(
            total=n["total"],
            succeeded=n["succeeded"],
            failed=n["failed"],
            pending=n["pending"],
            progress_percent=round(100 * done / n["total"], 1) if n["total"] else 100.0,
            links={
                "self": reverse("job-detail", args=[job.id]),
                "certificates": reverse("job-certificates", args=[job.id]),
                "download_all": reverse("job-download", args=[job.id]),
            },
        )
        return data


class CertificateSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Certificate
        fields = ["id", "position", "recipient_name", "recipient_email", "status", "error", "download_url"]

    def get_download_url(self, cert):
        if cert.status == Certificate.SUCCESS:
            return reverse("certificate-download", args=[cert.id])
        return None
