"""Safe fixed-page ReportLab resume rendering and template-data validation."""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import re

from pypdf import PdfReader
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


class ResumeLayoutError(RuntimeError):
    """The selected resume cannot be rendered within its original page count."""


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _header(text: str) -> dict[str, str]:
    lines = [_clean(line) for line in text.splitlines() if _clean(line)]
    name = lines[0] if lines else "OPTIMIZED RESUME"
    candidates = lines[1:8]
    contact_index = next((i for i, line in enumerate(candidates) if "@" in line or re.search(r"\+?\d[\d\s()\-]{7,}", line)), None)
    if contact_index is None:
        return {"name": name, "headline": candidates[0] if candidates else "", "contact": ""}
    return {"name": name, "headline": " ".join(candidates[:contact_index]), "contact": candidates[contact_index]}


def source_template_data(original_resume: str, sections: list[dict]) -> dict:
    """Create the immutable structural baseline supplied to the writer."""
    normalized = {str(item.get("heading", "")).strip().lower(): str(item.get("content", "")).strip() for item in sections}
    summary = next((value for key, value in normalized.items() if "summary" in key), "")
    skills_text = next((value for key, value in normalized.items() if "skill" in key), "")
    experience_text = next((value for key, value in normalized.items() if "experience" in key or "employment" in key), "")
    # pypdf can expose every bullet as a new pseudo-heading. Recover the whole
    # experience range from raw text so the immutable bullet baseline is accurate.
    raw_lines = [line.strip() for line in original_resume.splitlines() if line.strip()]
    start = next((i for i, line in enumerate(raw_lines) if re.sub(r"[^a-z ]", "", line.lower()).strip() in {"experience", "work experience", "professional experience", "employment history"}), None)
    if start is not None:
        end = next((i for i in range(start + 1, len(raw_lines)) if re.sub(r"[^a-z ]", "", raw_lines[i].lower()).strip() in {"education", "certifications", "certificates", "projects"}), len(raw_lines))
        experience_text = "\n".join(raw_lines[start + 1:end])
    education_text = next((value for key, value in normalized.items() if "education" in key), "")
    certification_text = next((value for key, value in normalized.items() if "cert" in key), "")
    project_text = next((value for key, value in normalized.items() if "project" in key), "")
    skill_rows, pending = [], None
    for line in [line.strip() for line in skills_text.splitlines() if line.strip()]:
        if ":" in line:
            label, items = line.split(":", 1); skill_rows.append({"label": label.strip(), "items": [_clean(x) for x in items.split(",") if _clean(x)]}); pending = None
        elif pending is None and len(line) < 45:
            pending = line
        elif pending is not None:
            skill_rows.append({"label": pending, "items": [_clean(x) for x in line.split(",") if _clean(x)]}); pending = None
    if pending: skill_rows.append({"label": "Skills", "items": [pending]})
    raw_experience_lines = [line.strip() for line in experience_text.splitlines() if line.strip()]
    lines = [line.strip(" \t•-*�") for line in raw_experience_lines if line.strip(" \t•-*�")]
    action_starts = {"accomplished", "achieved", "architected", "automated", "built", "created", "delivered", "designed", "developed", "directed", "implemented", "improved", "increased", "integrated", "launched", "led", "managed", "migrated", "optimized", "provisioned", "reduced", "streamlined", "transformed"}

    def starts_bullet(line: str) -> bool:
        clean = line.strip(" \t•-*�")
        first = clean.split(maxsplit=1)[0].lower() if clean else ""
        return line.lstrip().startswith(("•", "-", "*")) or first in action_starts

    first_bullet = next((index for index, line in enumerate(raw_experience_lines) if starts_bullet(line)), min(4, len(lines)))
    metadata = lines[:first_bullet]
    bullets, current = [], []
    for line in raw_experience_lines[first_bullet:]:
        is_marker = not re.search(r"[A-Za-z0-9]", line) or starts_bullet(line)
        if is_marker:
            if current: bullets.append(_clean(" ".join(current))); current = []
            if re.search(r"[A-Za-z0-9]", line):
                current.append(line.strip(" \t•-*�"))
            continue
        current.append(line.strip(" \t•-*�"))
    if current: bullets.append(_clean(" ".join(current)))
    # Documents without explicit bullet glyphs still preserve their post-metadata
    # content as one bullet per logical line rather than silently dropping it.
    if not bullets: bullets = [_clean(line) for line in lines[first_bullet:]]
    title_line = metadata[0] if metadata else ""
    title, company = ([_clean(value) for value in title_line.split("|", 1)] + [""])[:2] if "|" in title_line else (title_line, "")
    role = {"title": title, "company": company, "dates": metadata[1] if len(metadata) > 1 else "", "location": " | ".join(metadata[2:]), "bullets": bullets}
    education = [{"institution": line, "details": "", "dates": ""} for line in education_text.splitlines() if line.strip()]
    certifications = [_clean(line.lstrip("•-* ")) for line in certification_text.splitlines() if _clean(line.lstrip("•-* "))]
    project_lines = [line.strip(" \t•-*�") for line in project_text.splitlines() if line.strip(" \t•-*�")]
    project_start = next((index for index, line in enumerate(project_lines) if starts_bullet(line)), len(project_lines))
    project_metadata = project_lines[:project_start]
    project_bullets, current = [], []
    for line in project_lines[project_start:]:
        if starts_bullet(line):
            if current:
                project_bullets.append(_clean(" ".join(current)))
                current = []
        current.append(line)
    if current:
        project_bullets.append(_clean(" ".join(current)))
    projects = [{"title": project_metadata[0], "details": project_metadata[1:], "bullets": project_bullets}] if project_metadata else []
    return {"header": _header(original_resume), "summary": _clean(summary), "skills": skill_rows, "experience": [role] if role["title"] else [], "projects": projects, "education": education, "certifications": certifications}


def validate_template_data(candidate: object, source: dict) -> dict:
    """Reject malformed structure and restore protected identity/role metadata."""
    if not isinstance(candidate, dict): raise ResumeLayoutError("Generation model must return a resume_template object.")
    data = deepcopy(candidate.get("resume_template", candidate))
    for key in ("summary", "skills", "experience", "education", "certifications"):
        if key not in data: raise ResumeLayoutError(f"Generation model omitted required template field: {key}.")
    if not isinstance(data["experience"], list) or len(data["experience"]) != len(source["experience"]): raise ResumeLayoutError("Generation model changed the number of experience roles.")
    for index, baseline in enumerate(source["experience"]):
        role = data["experience"][index]
        if not isinstance(role, dict) or not isinstance(role.get("bullets"), list) or len(role["bullets"]) != len(baseline["bullets"]): raise ResumeLayoutError("Generation model changed the required bullet count for an experience role.")
        for protected in ("title", "company", "dates", "location"): role[protected] = baseline[protected]
        role["bullets"] = [_clean(item) for item in role["bullets"] if _clean(item)]
        if len(role["bullets"]) != len(baseline["bullets"]): raise ResumeLayoutError("Generation model returned an empty experience bullet.")
    if not isinstance(data["skills"], list) or not isinstance(data["education"], list) or not isinstance(data["certifications"], list): raise ResumeLayoutError("Generation model returned invalid template arrays.")
    normalized_skills = []
    for row in data["skills"]:
        if isinstance(row, str):
            normalized_skills.append({"label": "Skills", "items": [_clean(row)]})
        elif isinstance(row, dict) and _clean(row.get("label")) and isinstance(row.get("items"), list):
            normalized_skills.append({"label": _clean(row["label"]), "items": [_clean(item) for item in row["items"] if _clean(item)]})
        else:
            raise ResumeLayoutError("Generation model returned an invalid skill group.")
    data["skills"] = normalized_skills
    # Education and certifications are protected facts. Retain the parsed source
    # structure even when a model returns shorthand strings for these sections.
    data["education"] = deepcopy(source["education"])
    data["certifications"] = deepcopy(source["certifications"])
    data["projects"] = deepcopy(source.get("projects", []))
    data["header"] = deepcopy(source["header"])
    data["summary"] = _clean(data["summary"])
    if not data["summary"]: raise ResumeLayoutError("Generation model returned an empty summary.")
    return data


def plain_text(data: dict) -> str:
    lines = [data["header"].get("name", ""), data["header"].get("headline", ""), data["header"].get("contact", ""), "SUMMARY", data.get("summary", ""), "SKILLS"]
    lines += [f"{row.get('label', '')}: {', '.join(row.get('items', []))}" for row in data.get("skills", [])]
    lines.append("EXPERIENCE")
    for role in data.get("experience", []):
        lines += [role.get("title", ""), role.get("company", ""), role.get("dates", ""), role.get("location", ""), *[f"• {bullet}" for bullet in role.get("bullets", [])]]
    lines.append("PROJECTS")
    for project in data.get("projects", []):
        lines += [project.get("title", ""), *project.get("details", []), *[f"• {bullet}" for bullet in project.get("bullets", [])]]
    lines += ["EDUCATION", *[" | ".join(filter(None, (item.get("institution", ""), item.get("details", ""), item.get("dates", "")))) for item in data.get("education", [])], "CERTIFICATIONS", *[f"• {item}" for item in data.get("certifications", [])]]
    return "\n".join(line for line in lines if line)


NAVY = HexColor("#26457B")
BLACK = HexColor("#101010")


def _wrap(text: object, font: str, size: float, width: float) -> list[str]:
    """Wrap plain text deterministically without relying on external layout tools."""
    words = _clean(text).split()
    if not words:
        return []
    lines, current = [], ""
    for word in words:
        proposal = word if not current else f"{current} {word}"
        if current and stringWidth(proposal, font, size) > width:
            lines.append(current)
            current = word
        else:
            current = proposal
    if current:
        lines.append(current)
    return lines


def _line_block(kind: str, text: str, style: dict, **extra) -> dict:
    lines = _wrap(text, style["body_font"], style["body_size"], style["width"])
    return {"kind": kind, "text": text, "lines": lines, "height": max(1, len(lines)) * style["leading"] + style["gap"], **extra}


def _blocks(data: dict, style: dict) -> list[dict]:
    """Build semantic drawing blocks from validated resume data.

    All text is rendered as plain PDF text by ReportLab; model output never
    controls a markup interpreter or external compiler.
    """
    blocks: list[dict] = []

    def section(name: str) -> None:
        blocks.append({"kind": "section", "text": name, "height": style["section_height"], "spread": True})

    section("Summary")
    blocks.append(_line_block("paragraph", data.get("summary", ""), style, spread=True))

    if data.get("skills"):
        section("Technical Skills")
        for row in data["skills"]:
            label = _clean(row.get("label", "Skills"))
            items = ", ".join(_clean(item) for item in row.get("items", []) if _clean(item))
            blocks.append(_line_block("skill", f"{label}: {items}", style, label=label, items=items))

    if data.get("experience"):
        section("Experience")
        for role in data["experience"]:
            title = _clean(role.get("title", ""))
            company = _clean(role.get("company", ""))
            dates = _clean(role.get("dates", ""))
            location = _clean(role.get("location", ""))
            heading = " | ".join(part for part in (title, company) if part)
            date_width = stringWidth(dates, style["body_bold"], style["body_size"]) if dates else 0
            title_width = max(80, style["width"] - date_width - (10 if dates else 0))
            title_lines = _wrap(heading, style["body_bold"], style["body_size"], title_width)
            blocks.append({"kind": "role", "title_lines": title_lines, "dates": dates, "location": location, "height": max(1, len(title_lines)) * style["leading"] + (style["leading"] if location else 0) + style["role_gap"], "spread": True})
            for bullet in role.get("bullets", []):
                blocks.append(_line_block("bullet", _clean(bullet), style))

    if data.get("projects"):
        section("Projects")
        for project in data["projects"]:
            title = _clean(project.get("title", ""))
            details = [_clean(detail) for detail in project.get("details", []) if _clean(detail)]
            project_title_lines = _wrap(title, style["body_bold"], style["body_size"], style["width"] - (110 if details else 0))
            project_height = max(1, len(project_title_lines)) * style["leading"] + (style["leading"] if len(details) > 1 else 0) + style["role_gap"]
            blocks.append({"kind": "role", "title_lines": project_title_lines, "dates": details[0] if details else "", "location": " | ".join(details[1:]), "height": project_height, "spread": True})
            for bullet in project.get("bullets", []):
                blocks.append(_line_block("bullet", bullet, style))

    if data.get("education"):
        section("Education")
        for item in data["education"]:
            left = " | ".join(part for part in (_clean(item.get("institution", "")), _clean(item.get("details", ""))) if part)
            dates = _clean(item.get("dates", ""))
            date_width = stringWidth(dates, style["body_font"], style["body_size"]) if dates else 0
            education_width = max(80, style["width"] - date_width - (10 if dates else 0))
            education_lines = _wrap(left, style["body_bold"], style["body_size"], education_width)
            blocks.append({"kind": "education", "left_lines": education_lines, "dates": dates, "height": max(1, len(education_lines)) * style["leading"] + style["gap"], "spread": True})

    if data.get("certifications"):
        section("Certifications")
        for certification in data["certifications"]:
            blocks.append(_line_block("certification", _clean(certification), style))
    return blocks


def _partition(blocks: list[dict], capacity: float, page_count: int) -> list[list[dict]] | None:
    """Keep blocks ordered, fit them within page capacity, then balance pages."""
    pages: list[list[dict]] = [[]]
    used = 0.0
    for block in blocks:
        if block["height"] > capacity:
            return None
        if pages[-1] and used + block["height"] > capacity:
            pages.append([])
            used = 0.0
        pages[-1].append(block)
        used += block["height"]
    if len(pages) > page_count:
        return None
    while len(pages) < page_count:
        # Split the largest page near its visual midpoint so an input that was
        # originally two pages never becomes a one-page output plus a blank page.
        source_index = max(range(len(pages)), key=lambda index: sum(item["height"] for item in pages[index]))
        source = pages[source_index]
        if len(source) < 2:
            return None
        total = sum(item["height"] for item in source)
        running, split = 0.0, 1
        for index, item in enumerate(source[:-1], 1):
            running += item["height"]
            if running >= total / 2:
                split = index
                break
        pages.insert(source_index + 1, source[split:])
        pages[source_index] = source[:split]
    return pages


def _draw_page(pdf: canvas.Canvas, data: dict, blocks: list[dict], style: dict, page_number: int) -> None:
    width, height = letter
    left, right = style["margin"], width - style["margin"]
    pdf.setFillColor(BLACK)
    name = _clean(data["header"].get("name", "OPTIMIZED RESUME"))
    headline = _clean(data["header"].get("headline", ""))
    contact = _clean(data["header"].get("contact", ""))
    y = height - style["top_margin"]
    if page_number == 1:
        pdf.setFont("Times-Bold", style["name_size"])
        pdf.drawCentredString(width / 2, y, name)
        y -= style["name_size"] + 5
        if headline:
            pdf.setFont("Times-Roman", style["headline_size"])
            pdf.drawCentredString(width / 2, y, headline)
            y -= style["headline_size"] + 5
        if contact:
            pdf.setFont("Times-Roman", style["contact_size"])
            pdf.drawCentredString(width / 2, y, contact)
            y -= style["contact_size"] + 10
    else:
        pdf.setFont("Times-Bold", style["continued_size"])
        pdf.drawString(left, y, name)
        pdf.setFont("Times-Roman", style["contact_size"])
        pdf.drawRightString(right, y, f"Page {page_number}")
        y -= style["continued_size"] + 9

    usable = y - style["bottom_margin"]
    base_height = sum(block["height"] for block in blocks)
    spreadable = [block for block in blocks if block.get("spread")]
    # For short resumes, distribute remaining vertical space over semantic
    # boundaries. This avoids one large blank block at the bottom while keeping
    # spacing capped at a readable amount.
    extra = min(style["max_spread"], max(0.0, usable - base_height) / max(1, len(spreadable)))

    for block in blocks:
        kind = block["kind"]
        if kind == "section":
            pdf.setFillColor(NAVY)
            pdf.setFont("Times-Bold", style["section_size"])
            pdf.drawString(left, y - style["section_size"], block["text"])
            rule_y = y - style["section_size"] - 3
            pdf.setLineWidth(0.55)
            pdf.line(left, rule_y, right, rule_y)
            y -= block["height"] + extra
        elif kind == "paragraph":
            pdf.setFillColor(BLACK)
            pdf.setFont(style["body_font"], style["body_size"])
            for line in block["lines"]:
                pdf.drawString(left, y - style["body_size"], line)
                y -= style["leading"]
            y -= style["gap"] + extra
        elif kind == "skill":
            pdf.setFillColor(BLACK)
            first = True
            for line in block["lines"]:
                if first:
                    label = f"{block['label']}:"
                    pdf.setFont(style["body_bold"], style["body_size"])
                    pdf.drawString(left, y - style["body_size"], label)
                    prefix = stringWidth(label + " ", style["body_bold"], style["body_size"])
                    pdf.setFont(style["body_font"], style["body_size"])
                    remainder = line[len(label):].lstrip()
                    pdf.drawString(left + prefix, y - style["body_size"], remainder)
                    first = False
                else:
                    pdf.setFont(style["body_font"], style["body_size"])
                    pdf.drawString(left, y - style["body_size"], line)
                y -= style["leading"]
            y -= style["gap"]
        elif kind == "role":
            pdf.setFillColor(BLACK)
            pdf.setFont(style["body_bold"], style["body_size"])
            for index, line in enumerate(block["title_lines"]):
                pdf.drawString(left, y - style["body_size"], line)
                if index == 0 and block["dates"]:
                    pdf.drawRightString(right, y - style["body_size"], block["dates"])
                y -= style["leading"]
            if block["location"]:
                pdf.setFont("Times-Italic", style["body_size"])
                pdf.drawString(left, y - style["body_size"], block["location"])
                y -= style["leading"]
            y -= style["role_gap"] + extra
        elif kind in {"bullet", "certification"}:
            pdf.setFillColor(BLACK)
            pdf.setFont(style["body_font"], style["body_size"])
            bullet_x = left + style["bullet_indent"]
            text_x = bullet_x + style["bullet_gap"]
            for index, line in enumerate(block["lines"]):
                if index == 0:
                    # Draw the marker instead of relying on a Unicode bullet in
                    # a base PDF font. This keeps the output self-contained and
                    # avoids font-substitution warnings on the VM.
                    pdf.circle(bullet_x + 2.2, y - style["body_size"] + 3.1, 1.25, stroke=0, fill=1)
                pdf.drawString(text_x, y - style["body_size"], line)
                y -= style["leading"]
            y -= style["gap"]
        elif kind == "education":
            pdf.setFillColor(BLACK)
            pdf.setFont(style["body_bold"], style["body_size"])
            for index, line in enumerate(block["left_lines"]):
                pdf.drawString(left, y - style["body_size"], line)
                if index == 0 and block["dates"]:
                    pdf.setFont(style["body_font"], style["body_size"])
                    pdf.drawRightString(right, y - style["body_size"], block["dates"])
                    pdf.setFont(style["body_bold"], style["body_size"])
                y -= style["leading"]
            y -= style["gap"] + extra
    pdf.showPage()


def render_pdf(data: dict, target_page_count: int) -> bytes:
    """Render a fixed-page, reference-inspired resume with ReportLab only."""
    if target_page_count < 1:
        raise ResumeLayoutError("The uploaded resume has no rendered pages to preserve.")
    variants = (
        {"margin": 34, "top_margin": 42, "bottom_margin": 32, "name_size": 23, "headline_size": 13, "contact_size": 10, "continued_size": 12, "section_size": 14, "section_height": 24, "body_font": "Times-Roman", "body_bold": "Times-Bold", "body_size": 10.2, "leading": 12.1, "gap": 2.0, "role_gap": 2.5, "bullet_indent": 2, "bullet_gap": 10, "max_spread": 5},
        {"margin": 31, "top_margin": 38, "bottom_margin": 29, "name_size": 21, "headline_size": 12, "contact_size": 9.5, "continued_size": 11, "section_size": 13, "section_height": 21, "body_font": "Times-Roman", "body_bold": "Times-Bold", "body_size": 9.4, "leading": 10.9, "gap": 1.5, "role_gap": 2.0, "bullet_indent": 2, "bullet_gap": 9, "max_spread": 4},
        {"margin": 28, "top_margin": 35, "bottom_margin": 27, "name_size": 20, "headline_size": 11.5, "contact_size": 9, "continued_size": 10.5, "section_size": 12.3, "section_height": 19, "body_font": "Times-Roman", "body_bold": "Times-Bold", "body_size": 8.8, "leading": 10.0, "gap": 1.2, "role_gap": 1.5, "bullet_indent": 1, "bullet_gap": 8, "max_spread": 3},
    )
    for base in variants:
        style = dict(base)
        style["width"] = letter[0] - 2 * style["margin"]
        header_height = style["top_margin"] + style["name_size"] + style["headline_size"] + style["contact_size"] + 20
        capacity = letter[1] - style["bottom_margin"] - header_height
        blocks = _blocks(data, style)
        pages = _partition(blocks, capacity, target_page_count)
        if pages is None:
            continue
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=letter, pageCompression=1)
        pdf.setTitle("Optimized Resume")
        pdf.setAuthor("Resume Optimizer")
        for page_number, page_blocks in enumerate(pages, 1):
            _draw_page(pdf, data, page_blocks, style, page_number)
        pdf.save()
        result = buffer.getvalue()
        if len(PdfReader(BytesIO(result)).pages) == target_page_count:
            return result
    raise ResumeLayoutError(
        f"The required content cannot fit within the uploaded resume's {target_page_count}-page limit at the minimum readable layout density."
    )
