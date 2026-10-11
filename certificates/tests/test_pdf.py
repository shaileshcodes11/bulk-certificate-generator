import tempfile
from datetime import date
from pathlib import Path

from django.test import SimpleTestCase

from certificates.pdf import render_certificate


class PdfTests(SimpleTestCase):
    def test_render_writes_valid_pdf_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "nested" / "c.pdf"
            render_certificate(
                out,
                recipient_name="Asha Patil",
                title="Certificate of Completion",
                course_name="Python Bootcamp",
                issued_by="Acme Academy",
                issue_date=date(2026, 9, 30),
            )
            data = out.read_bytes()
            self.assertTrue(data.startswith(b"%PDF"))
            self.assertTrue(data.rstrip().endswith(b"%%EOF"))
            self.assertEqual(list(out.parent.glob("*.part")), [])
