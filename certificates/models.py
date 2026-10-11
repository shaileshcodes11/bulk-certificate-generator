import uuid

from django.db import models


class Job(models.Model):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"  # every certificate succeeded
    COMPLETED_WITH_ERRORS = "completed_with_errors"  # some succeeded, some failed
    FAILED = "failed"  # nothing succeeded
    STATUS_CHOICES = [(s, s) for s in (QUEUED, PROCESSING, COMPLETED, COMPLETED_WITH_ERRORS, FAILED)]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=QUEUED, db_index=True)
    title = models.CharField(max_length=200)
    course_name = models.CharField(max_length=200)
    issued_by = models.CharField(max_length=200)
    issue_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Job {self.id} ({self.status})"


class Certificate(models.Model):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    STATUS_CHOICES = [(s, s) for s in (PENDING, SUCCESS, FAILED)]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="certificates")
    position = models.PositiveIntegerField()  # index in the submitted list
    recipient_name = models.CharField(max_length=200, null=True, blank=True)
    recipient_email = models.CharField(max_length=320, null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    file_path = models.CharField(max_length=500, null=True, blank=True)
    error = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["position"]
        indexes = [models.Index(fields=["job", "status"])]

    def __str__(self):
        return f"{self.recipient_name or '?'} [{self.status}]"
