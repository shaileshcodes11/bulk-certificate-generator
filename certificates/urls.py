from django.urls import path

from . import views

urlpatterns = [
    path("jobs/", views.JobListCreateView.as_view(), name="job-list"),
    path("jobs/<uuid:job_id>/", views.JobDetailView.as_view(), name="job-detail"),
    path("jobs/<uuid:job_id>/certificates/", views.JobCertificatesView.as_view(), name="job-certificates"),
    path("jobs/<uuid:job_id>/download/", views.JobDownloadView.as_view(), name="job-download"),
    path("certificates/<uuid:certificate_id>/download/", views.CertificateDownloadView.as_view(), name="certificate-download"),
]
