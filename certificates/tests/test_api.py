import io
import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.test import override_settings
from rest_framework.test import APITestCase

from certificates import services
from certificates.models import Certificate, Job

TMP = tempfile.mkdtemp(prefix="certgen-drf-tests-")


@override_settings(CERTGEN_RUN_SYNC=True, CERTGEN_STORAGE_DIR=Path(TMP), CERTGEN_MAX_RECIPIENTS=50)
class ApiTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.payload = {
            "certificate": {
                "course_name": "Python Bootcamp",
                "issued_by": "Acme Academy",
                "issue_date": "2026-09-30",
            },
            "recipients": [
                {"name": "Asha Patil", "email": "asha@example.com"},
                {"name": "Rahul Deshmukh"},
                {"name": "Meera Joshi", "email": "meera@example.com"},
            ],
        }

    # ---- helpers
    def submit(self, payload=None):
        return self.client.post("/api/jobs/", payload or self.payload, format="json")

    def job(self, job_id):
        return self.client.get(f"/api/jobs/{job_id}/").json()

    def certs(self, job_id, **params):
        return self.client.get(f"/api/jobs/{job_id}/certificates/", params).json()

    # ---- creating a job
    def test_create_returns_202_with_tracking_info(self):
        r = self.submit()
        self.assertEqual(r.status_code, 202)
        body = r.json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["links"]["self"], f"/api/jobs/{body['id']}/")

    def test_unknown_job_is_404(self):
        self.assertEqual(self.client.get("/api/jobs/00000000-0000-0000-0000-000000000000/").status_code, 404)

    def test_list_jobs(self):
        self.submit()
        self.submit()
        r = self.client.get("/api/jobs/").json()
        self.assertEqual(r["count"], 2)

    # ---- request-level validation
    def test_empty_recipients_rejected(self):
        self.payload["recipients"] = []
        self.assertEqual(self.submit().status_code, 400)

    def test_certificate_info_defaults_to_bootcamp_details(self):
        self.payload["certificate"] = {}
        job = self.submit(self.payload).json()
        self.assertEqual(job["course_name"], "Python for Beginners Bootcamp")
        self.assertEqual(job["issued_by"], "Acme Academy")
        self.assertEqual(job["status"], "completed")

    def test_overlong_course_name_rejected(self):
        self.payload["certificate"]["course_name"] = "x" * 201
        r = self.submit()
        self.assertEqual(r.status_code, 400)
        self.assertIn("course_name", r.json()["certificate"])

    def test_too_many_recipients_rejected(self):
        self.payload["recipients"] = [{"name": f"Person {i}"} for i in range(51)]
        r = self.submit()
        self.assertEqual(r.status_code, 400)
        self.assertIn("maximum is 50", str(r.json()))

    # ---- recipient-level validation
    def test_invalid_recipients_recorded_and_valid_ones_still_generated(self):
        self.payload["recipients"] = [
            {"name": "Valid One", "email": "ok@example.com"},
            {"name": "   "},  # blank name
            {"name": "Bad Email", "email": "not-an-email"},
            {"email": "noname@example.com"},  # missing name
            "just a string",  # wrong type
            None,  # null entry
            {"name": "Ramesh \u0930\u092e\u0947\u0936"},  # unsupported characters
            {"name": "Valid Two"},
        ]
        job_id = self.submit().json()["id"]
        job = self.job(job_id)
        self.assertEqual((job["total"], job["succeeded"], job["failed"]), (8, 2, 6))
        self.assertEqual(job["status"], "completed_with_errors")

        failed = self.certs(job_id, status="failed")
        self.assertEqual(failed["count"], 6)
        self.assertTrue(all(i["error"] for i in failed["results"]))
        self.assertEqual(sorted(i["position"] for i in failed["results"]), [1, 2, 3, 4, 5, 6])

    def test_failed_recipient_keeps_submitted_email(self):
        self.payload["recipients"] = [{"name": "Bad Email Person", "email": "not-an-email"}]
        job_id = self.submit().json()["id"]
        item = self.certs(job_id)["results"][0]
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["recipient_email"], "not-an-email")
        self.assertIn("email", item["error"])

    def test_all_invalid_marks_job_failed(self):
        self.payload["recipients"] = [{"name": ""}, {"email": "x"}]
        job = self.submit().json()
        self.assertEqual(job["status"], "failed")
        self.assertEqual((job["failed"], job["succeeded"]), (2, 0))

    def test_name_whitespace_normalised(self):
        self.payload["recipients"] = [{"name": "  Asha    Patil  "}]
        job_id = self.submit().json()["id"]
        self.assertEqual(self.certs(job_id)["results"][0]["recipient_name"], "Asha Patil")

    # ---- generation + status
    def test_generation_completes(self):
        job_id = self.submit().json()["id"]
        job = self.job(job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual((job["succeeded"], job["failed"], job["pending"]), (3, 0, 0))
        self.assertEqual(job["progress_percent"], 100.0)
        self.assertTrue(job["created_at"].endswith("Z"))
        self.assertTrue(job["completed_at"].endswith("Z"))
        items = self.certs(job_id)["results"]
        self.assertEqual([i["recipient_name"] for i in items], ["Asha Patil", "Rahul Deshmukh", "Meera Joshi"])
        self.assertTrue(all(i["status"] == "success" and i["download_url"] for i in items))

    def test_pending_state_and_progress(self):
        with mock.patch.object(services, "enqueue", lambda job_id: None):
            job = self.submit().json()
        self.assertEqual(job["status"], "queued")
        self.assertEqual((job["pending"], job["succeeded"], job["progress_percent"]), (3, 0, 0.0))
        cert = self.certs(job["id"])["results"][0]
        self.assertEqual(self.client.get(f"/api/certificates/{cert['id']}/download/").status_code, 409)

    def test_pagination(self):
        job_id = self.submit().json()["id"]
        page = self.certs(job_id, limit=2, offset=2)
        self.assertEqual(page["count"], 3)
        self.assertEqual(len(page["results"]), 1)

    def test_invalid_status_filter_is_400(self):
        job_id = self.submit().json()["id"]
        r = self.client.get(f"/api/jobs/{job_id}/certificates/", {"status": "bogus"})
        self.assertEqual(r.status_code, 400)

    # ---- individual failure isolation
    def test_one_generation_failure_does_not_stop_the_others(self):
        real = services.generate_one

        def flaky(job, cert):
            if cert.recipient_name == "Rahul Deshmukh":
                raise RuntimeError("disk exploded")
            return real(job, cert)

        with mock.patch.object(services, "generate_one", flaky):
            job_id = self.submit().json()["id"]
        job = self.job(job_id)
        self.assertEqual(job["status"], "completed_with_errors")
        self.assertEqual((job["succeeded"], job["failed"]), (2, 1))
        by_name = {i["recipient_name"]: i for i in self.certs(job_id)["results"]}
        self.assertEqual(by_name["Rahul Deshmukh"]["status"], "failed")
        self.assertIn("disk exploded", by_name["Rahul Deshmukh"]["error"])
        self.assertIsNone(by_name["Rahul Deshmukh"]["download_url"])
        self.assertEqual(by_name["Meera Joshi"]["status"], "success")  # processed after the failure

    def test_process_job_is_resumable_and_idempotent(self):
        with mock.patch.object(services, "enqueue", lambda job_id: None):
            job_id = self.submit().json()["id"]
        services.process_job(job_id)
        services.process_job(job_id)  # second run finds nothing pending
        job = self.job(job_id)
        self.assertEqual((job["status"], job["succeeded"]), ("completed", 3))

    # ---- downloads
    def test_download_single_pdf(self):
        job_id = self.submit().json()["id"]
        cert = self.certs(job_id)["results"][0]
        r = self.client.get(cert["download_url"])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        content = b"".join(r.streaming_content)
        self.assertTrue(content.startswith(b"%PDF"))

    def test_download_all_zip(self):
        job_id = self.submit().json()["id"]
        r = self.client.get(f"/api/jobs/{job_id}/download/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            names = zf.namelist()
            self.assertEqual(len(names), 3)
            self.assertTrue(names[0].startswith("0001_Asha_Patil"))
            self.assertTrue(all(zf.read(n).startswith(b"%PDF") for n in names))

    def test_zip_only_has_successful_certificates(self):
        self.payload["recipients"].append({"name": ""})
        job_id = self.submit().json()["id"]
        r = self.client.get(f"/api/jobs/{job_id}/download/")
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            self.assertEqual(len(zf.namelist()), 3)

    def test_download_404s(self):
        self.payload["recipients"] = [{"name": ""}]
        job = self.submit().json()
        self.assertEqual(self.client.get(job["links"]["download_all"]).status_code, 404)
        cert = self.certs(job["id"])["results"][0]
        self.assertEqual(self.client.get(f"/api/certificates/{cert['id']}/download/").status_code, 404)
        self.assertEqual(
            self.client.get("/api/certificates/00000000-0000-0000-0000-000000000000/download/").status_code, 404
        )

    def test_resume_jobs_command(self):
        from django.core.management import call_command

        with mock.patch.object(services, "enqueue", lambda job_id: None):
            job_id = self.submit().json()["id"]
        call_command("resume_jobs", stdout=io.StringIO())
        self.assertEqual(Job.objects.get(pk=job_id).status, Job.COMPLETED)
        self.assertEqual(Certificate.objects.filter(job_id=job_id, status="success").count(), 3)
