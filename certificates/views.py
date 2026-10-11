import io
import zipfile
from pathlib import Path

from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status as http
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Certificate, Job
from .serializers import CertificateSerializer, JobCreateSerializer, JobSerializer


class CertificatePagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 1000


class JobPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 100


class JobListCreateView(ListAPIView):
    """POST: submit a bulk request (returns 202 immediately). GET: list jobs, newest first."""

    queryset = Job.objects.all()
    pagination_class = JobPagination

    def get_serializer_class(self):
        return JobCreateSerializer if self.request.method == "POST" else JobSerializer

    def post(self, request):
        serializer = JobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = services.create_job(serializer.validated_data)
        if job.status == Job.QUEUED:  # nothing to do if every recipient was invalid
            services.enqueue(job.id)
        job.refresh_from_db()
        return Response(JobSerializer(job).data, status=http.HTTP_202_ACCEPTED)


class JobDetailView(APIView):
    def get(self, request, job_id):
        return Response(JobSerializer(get_object_or_404(Job, pk=job_id)).data)


class JobCertificatesView(ListAPIView):
    """Per-recipient results. Filter with ?status=pending|success|failed."""

    serializer_class = CertificateSerializer
    pagination_class = CertificatePagination

    def get_queryset(self):
        get_object_or_404(Job, pk=self.kwargs["job_id"])
        qs = Certificate.objects.filter(job_id=self.kwargs["job_id"])
        wanted = self.request.query_params.get("status")
        if wanted:
            if wanted not in dict(Certificate.STATUS_CHOICES):
                raise ValidationError({"status": "Must be one of: pending, success, failed."})
            qs = qs.filter(status=wanted)
        return qs.order_by("position")


def _safe(name):
    return "".join(ch if ch.isalnum() else "_" for ch in (name or "certificate"))


def _existing_file(cert):
    if cert.status != Certificate.SUCCESS or not cert.file_path:
        return None
    p = Path(cert.file_path)
    return p if p.is_file() else None


class CertificateDownloadView(APIView):
    def get(self, request, certificate_id):
        cert = get_object_or_404(Certificate, pk=certificate_id)
        if cert.status == Certificate.PENDING:
            return Response({"detail": "Certificate is not generated yet."}, status=http.HTTP_409_CONFLICT)
        path = _existing_file(cert)
        if path is None:
            raise NotFound("Certificate was not generated successfully.")
        return FileResponse(
            open(path, "rb"),
            as_attachment=True,
            filename=f"{_safe(cert.recipient_name)}_{str(cert.id)[:8]}.pdf",
            content_type="application/pdf",
        )


class JobDownloadView(APIView):
    """ZIP of every successfully generated certificate in the job so far."""

    def get(self, request, job_id):
        job = get_object_or_404(Job, pk=job_id)
        certs = job.certificates.filter(status=Certificate.SUCCESS).order_by("position")
        files = [(c, p) for c in certs if (p := _existing_file(c))]
        if not files:
            raise NotFound("No generated certificates available for this job yet.")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:  # PDFs are already compressed
            for c, p in files:
                zf.write(p, f"{c.position + 1:04d}_{_safe(c.recipient_name)}.pdf")
        resp = HttpResponse(buf.getvalue(), content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="certificates_{str(job.id)[:8]}.zip"'
        return resp
