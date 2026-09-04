"""Render optimized resumes using the supplied compact navy resume format."""
from __future__ import annotations

from io import BytesIO
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = colors.HexColor("#26457B")
TEXT = colors.HexColor("#252525")
MUTED = colors.HexColor("#404040")
EXPERIENCE_HEADINGS = {"experience", "work experience", "professional experience"}
STANDARD_HEADINGS = {
    "summary", "profile summary", "professional summary", "skills", "key skills",
    "technical skills", "core competencies", "experience", "work experience",
    "professional experience", "education", "certifications", "certificates", "projects",
}


def _lines(value: str) -> list[str]:
    """Normalize non-empty source lines without changing their factual content."""
    return [re.sub(r"\s+", " ", line).strip() for line in (value or "").splitlines() if line.strip()]


def _header(original_resume: str) -> tuple[str, str, str]:
    """Extract a presentational header from original text, never from model output."""
    lines = _lines(original_resume)
    if not lines:
        return "OPTIMIZED RESUME", "", ""
    name, candidates = lines[0], lines[1:8]
    contact_index = next((i for i, line in enumerate(candidates) if "@" in line or re.search(r"\+?\d[\d\s()\-]{7,}", line)), None)
    if contact_index is None:
        return name, candidates[0] if candidates else "", ""
    return name, " ".join(candidates[:contact_index]).strip(), candidates[contact_index]


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    """Escape resume text before it reaches ReportLab's mini-markup parser."""
    return Paragraph(escape(text).replace("•", "&bull;"), style)


def _skill_rows(content: str) -> list[tuple[str, str]]:
    lines, rows, index = _lines(content), [], 0
    while index < len(lines):
        line = lines[index]
        if ":" in line:
            label, value = line.split(":", 1)
            rows.append((label.strip(), value.strip()))
        elif index + 1 < len(lines) and len(line) < 42:
            rows.append((line, lines[index + 1]))
            index += 1
        else:
            rows.append(("", line))
        index += 1
    return rows


def _render_sections(sections: list[dict]) -> list[dict]:
    """Repair common PDF-extraction fragments before laying content out.

    Some PDFs expose every bullet, date, or certification as a top-level heading.
    Those fragments belong to the preceding real section; retaining them as sections
    would make a visually noisy resume and is not an intended content change.
    """
    normalized: list[dict] = []
    for section in sections or []:
        heading = str(section.get("heading", "")).strip()
        content = str(section.get("content", "")).strip()
        heading_key = heading.lower()
        heading_is_glyph = not re.search(r"[A-Za-z0-9]", heading)
        is_known_heading = heading_key in STANDARD_HEADINGS

        if not normalized and not is_known_heading:
            # The first extracted item is usually the name/contact header.
            continue
        if normalized and (heading_is_glyph or not is_known_heading):
            prefix = "• " if heading_is_glyph else f"{heading}\n"
            prior = normalized[-1]["content"]
            normalized[-1]["content"] = f"{prior}\n{prefix}{content}".strip()
            continue
        normalized.append({"heading": heading, "content": content})
    return normalized


def build_resume_pdf(sections: list[dict], rewritten_experience: str | None = None, original_resume: str = "") -> bytes:
    """Build a selected resume version in the supplied navy, one-page-friendly style."""
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=LETTER, leftMargin=.55 * inch, rightMargin=.55 * inch, topMargin=.34 * inch, bottomMargin=.32 * inch, title="Optimized Resume")
    base = getSampleStyleSheet()
    name_style = ParagraphStyle("ResumeName", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=20, leading=22, alignment=TA_CENTER, textColor=NAVY, spaceAfter=0)
    role_style = ParagraphStyle("ResumeRole", parent=base["Normal"], fontName="Helvetica-Oblique", fontSize=11.5, leading=13, alignment=TA_CENTER, textColor=TEXT, spaceAfter=1)
    contact_style = ParagraphStyle("ResumeContact", parent=base["Normal"], fontName="Helvetica", fontSize=8, leading=9.5, alignment=TA_CENTER, textColor=MUTED, spaceAfter=5)
    section_style = ParagraphStyle("ResumeSection", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=11.2, leading=12.5, textColor=NAVY, spaceBefore=0, spaceAfter=0)
    body_style = ParagraphStyle("ResumeBody", parent=base["Normal"], fontName="Helvetica", fontSize=7.65, leading=9.05, textColor=TEXT, spaceAfter=.7)
    bullet_style = ParagraphStyle("ResumeBullet", parent=body_style, leftIndent=11, firstLineIndent=-7, spaceAfter=1.1)
    skill_label_style = ParagraphStyle("SkillLabel", parent=body_style, fontName="Helvetica-Bold", textColor=TEXT, spaceAfter=0)
    skill_value_style = ParagraphStyle("SkillValue", parent=body_style, textColor=TEXT, spaceAfter=0)

    name, headline, contact = _header(original_resume)
    story: list = [_paragraph(name, name_style)]
    if headline:
        story.append(_paragraph(headline, role_style))
    if contact:
        story.append(_paragraph(contact, contact_style))
    else:
        story.append(Spacer(1, 7))

    for section in _render_sections(sections):
        heading, content = str(section.get("heading", "")).strip(), str(section.get("content", "")).strip()
        if rewritten_experience is not None and heading.lower() in EXPERIENCE_HEADINGS:
            content = rewritten_experience.strip()
        if not heading or not content:
            continue
        story.extend([_paragraph(heading.upper(), section_style), HRFlowable(width="100%", thickness=.7, color=NAVY, spaceAfter=2)])
        if heading.lower() in {"skills", "key skills", "technical skills", "core competencies"}:
            rows = _skill_rows(content)
            table = Table([[_paragraph(label, skill_label_style), _paragraph(value, skill_value_style)] for label, value in rows], colWidths=[1.42 * inch, 5.15 * inch], hAlign="LEFT")
            table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
            story.append(table)
        else:
            for line in _lines(content):
                if line.startswith(("•", "-", "*")):
                    story.append(_paragraph(f"• {line.lstrip('•-* ').strip()}", bullet_style))
                else:
                    story.append(_paragraph(line, body_style))
        story.append(Spacer(1, 2.3))
    document.build(story)
    return output.getvalue()
