"""PDF rendering of the single predefined certificate template."""
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from . import template_config as cfg

BLUE = colors.HexColor("#306998")     # Python-inspired palette (no logo used)
YELLOW = colors.HexColor("#FFD43B")
NAVY = colors.HexColor("#1F2A44")
GREY = colors.HexColor("#5A6478")
PALE = colors.HexColor("#F3F7FB")


def _fit(text, font, size, max_width, min_size=10):
    """Shrink the font until text fits; truncate with an ellipsis as a last resort."""
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 1
    if stringWidth(text, font, size) > max_width:
        while text and stringWidth(text + "...", font, size) > max_width:
            text = text[:-1]
        text += "..."
    return text, size


def _spaced(c, x, y, text, font, size, spacing):
    """Centered text with letter spacing."""
    t = c.beginText()
    t.setFont(font, size)
    t.setCharSpace(spacing)
    w = stringWidth(text, font, size) + spacing * (len(text) - 1)
    t.setTextOrigin(x - w / 2, y)
    t.textOut(text)
    t.setCharSpace(0)  # PDF text state persists; reset or all later text stays spaced
    c.drawText(t)


def render_certificate(
    path: Path,
    *,
    recipient_name: str,
    title: str,
    course_name: str,
    issued_by: str,
    issue_date: date,
    certificate_id: str | None = None,
) -> None:
    """Render the certificate to `path` (parent dirs are created)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    W, H = landscape(A4)
    cx = W / 2
    tmp = path.with_suffix(".pdf.part")  # write-then-rename: never leave a half file
    c = canvas.Canvas(str(tmp), pagesize=(W, H))
    c.setTitle(f"{title} - {recipient_name}")

    # --- borders: blue outer, yellow inner ---
    c.setStrokeColor(BLUE)
    c.setLineWidth(8)
    c.rect(22, 22, W - 44, H - 44)
    c.setStrokeColor(YELLOW)
    c.setLineWidth(2)
    c.rect(36, 36, W - 72, H - 72)

    # --- header ---
    c.setFillColor(BLUE)
    _spaced(c, cx, H - 82, cfg.DEFAULT_COURSE_NAME.upper(), "Helvetica-Bold", 11, 2.5)
    c.setFillColor(NAVY)
    text, size = _fit(title.upper(), "Helvetica-Bold", 34, W - 200)
    c.setFont("Helvetica-Bold", size)
    c.drawCentredString(cx, H - 122, text)

    c.setFillColor(GREY)
    c.setFont("Helvetica", 13)
    c.drawCentredString(cx, H - 152, "This is to certify that")

    # --- recipient ---
    c.setFillColor(BLUE)
    text, size = _fit(recipient_name, "Helvetica-Bold", 32, W - 200)
    c.setFont("Helvetica-Bold", size)
    c.drawCentredString(cx, H - 194, text)
    c.setStrokeColor(YELLOW)
    c.setLineWidth(2)
    c.line(cx - 230, H - 205, cx + 230, H - 205)

    c.setFillColor(GREY)
    c.setFont("Helvetica", 13)
    c.drawCentredString(cx, H - 228, "has successfully completed the")

    # --- course ---
    c.setFillColor(NAVY)
    text, size = _fit(course_name, "Helvetica-Bold", 24, W - 200, min_size=12)
    c.setFont("Helvetica-Bold", size)
    c.drawCentredString(cx, H - 258, text)

    c.setFillColor(GREY)
    text, size = _fit(cfg.TAGLINE, "Helvetica-Oblique", 11, W - 200)
    c.setFont("Helvetica-Oblique", size)
    c.drawCentredString(cx, H - 278, text)
    c.setFont("Helvetica-Bold", 10.5)
    c.setFillColor(BLUE)
    c.drawCentredString(cx, H - 297, f"{cfg.DURATION}   |   {cfg.MODE}")

    # --- "what the program covered" panel ---
    px, pw, ptop, ph = 90, W - 180, H - 316, 88
    c.setFillColor(PALE)
    c.setStrokeColor(colors.HexColor("#D5E1EE"))
    c.setLineWidth(0.8)
    c.roundRect(px, ptop - ph, pw, ph, 6, fill=1, stroke=1)
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawCentredString(cx, ptop - 17, "WHAT THE PROGRAM COVERED")
    cols, col_w = 3, pw / 3
    c.setFont("Helvetica", 10.5)
    for i, topic in enumerate(cfg.TOPICS):
        col, row = i % cols, i // cols
        x = px + 24 + col * col_w
        y = ptop - 38 - row * 16
        c.setFillColor(YELLOW)
        c.circle(x, y + 3.5, 2.6, fill=1, stroke=0)
        c.setFillColor(NAVY)
        c.drawString(x + 10, y, topic)

    # --- footer: date | seal | signatory ---
    base = 112
    c.setStrokeColor(GREY)
    c.setLineWidth(0.8)
    c.line(90, base, 250, base)
    c.line(W - 250, base, W - 90, base)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(170, base + 6, issue_date.strftime("%d %B %Y"))
    c.setFillColor(GREY)
    c.setFont("Helvetica", 10)
    c.drawCentredString(170, base - 14, "Date of issue")
    c.setFillColor(NAVY)
    text, size = _fit(issued_by, "Helvetica-Bold", 11, 170, min_size=8)
    c.setFont("Helvetica-Bold", size)
    c.drawCentredString(W - 170, base - 14, text)
    c.setFillColor(GREY)
    c.setFont("Helvetica", 10)
    c.drawCentredString(W - 170, base - 28, cfg.SIGNATORY_TITLE)

    # seal
    c.setFillColor(YELLOW)
    c.setStrokeColor(BLUE)
    c.setLineWidth(3)
    c.circle(cx, base + 12, 34, fill=1, stroke=1)
    c.setLineWidth(1)
    c.circle(cx, base + 12, 28, fill=0, stroke=1)
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(cx, base + 23, "COMPLETED")
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(cx, base + 6, "PYTHON")
    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(cx, base - 4, "BEGINNERS")

    if certificate_id:
        c.setFillColor(GREY)
        c.setFont("Helvetica", 8)
        c.drawCentredString(cx, 52, f"Certificate ID: {certificate_id}")

    c.showPage()
    c.save()
    tmp.replace(path)