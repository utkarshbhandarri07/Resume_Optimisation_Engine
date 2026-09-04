"""Safe fixed-page LaTeX resume rendering and template-data validation."""
from __future__ import annotations

from copy import deepcopy
from importlib.resources import files
from io import BytesIO
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from string import Template

from pypdf import PdfReader


class ResumeLayoutError(RuntimeError):
    """The selected resume cannot be rendered within its original page count."""


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _latex(value: object) -> str:
    """Escape all model/user text; the template is the only source of TeX."""
    text = _clean(value)
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(replacements.get(char, char) for char in text)


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
    metadata = lines[:4]
    bullets, current = [], []
    for line in raw_experience_lines[4:]:
        is_marker = not re.search(r"[A-Za-z0-9]", line) or line.startswith(("•", "-", "*"))
        if is_marker:
            if current: bullets.append(_clean(" ".join(current))); current = []
            continue
        current.append(line.strip(" \t•-*�"))
    if current: bullets.append(_clean(" ".join(current)))
    # Documents without explicit bullet glyphs still preserve their post-metadata
    # content as one bullet per logical line rather than silently dropping it.
    if not bullets: bullets = [_clean(line) for line in lines[4:]]
    role = {"title": metadata[0] if metadata else "", "company": metadata[2] if len(metadata) > 2 else "", "dates": metadata[1] if len(metadata) > 1 else "", "location": metadata[3] if len(metadata) > 3 else "", "bullets": bullets}
    education = [{"institution": line, "details": "", "dates": ""} for line in education_text.splitlines() if line.strip()]
    certifications = [_clean(line.lstrip("•-* ")) for line in certification_text.splitlines() if _clean(line.lstrip("•-* "))]
    return {"header": _header(original_resume), "summary": _clean(summary), "skills": skill_rows, "experience": [role] if role["title"] else [], "education": education, "certifications": certifications}


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
    lines += ["EDUCATION", *[" | ".join(filter(None, (item.get("institution", ""), item.get("details", ""), item.get("dates", "")))) for item in data.get("education", [])], "CERTIFICATIONS", *[f"• {item}" for item in data.get("certifications", [])]]
    return "\n".join(line for line in lines if line)


def _body(data: dict) -> str:
    chunks = [r"\ResumeSection{SUMMARY}", _latex(data["summary"]), r"\ResumeSection{SKILLS}", r"\begin{tabularx}{\linewidth}{@{}p{1.55in}X@{}}"]
    for row in data.get("skills", []): chunks.append(rf"\textbf{{{_latex(row.get('label', ''))}}} & {_latex(', '.join(row.get('items', [])))}\\[-0.1em]")
    chunks += [r"\end{tabularx}", r"\ResumeSection{EXPERIENCE}"]
    for role in data.get("experience", []):
        chunks += [rf"\ResumeEntry{{{_latex(role['title'])}}}{{{_latex(role['company'])}}}{{{_latex(role['dates'])}}}{{{_latex(role['location'])}}}", r"\begin{itemize}[leftmargin=1.1em,itemsep=0.12em,topsep=0.2em]", *[rf"\ResumeBullet{{{_latex(bullet)}}}" for bullet in role["bullets"]], r"\end{itemize}"]
    chunks.append(r"\ResumeSection{EDUCATION}")
    chunks += [rf"\ResumeEntry{{{_latex(item.get('institution', ''))}}}{{{_latex(item.get('details', ''))}}}{{{_latex(item.get('dates', ''))}}}{{}}" for item in data.get("education", [])]
    chunks += [r"\ResumeSection{CERTIFICATIONS}", r"\begin{itemize}[leftmargin=1.1em,itemsep=0.12em,topsep=0.2em]", *[rf"\ResumeBullet{{{_latex(item)}}}" for item in data.get("certifications", [])], r"\end{itemize}"]
    return "\n".join(chunks)


def render_pdf(data: dict, target_page_count: int) -> bytes:
    pinned_binary = Path("/usr/local/bin/tectonic")
    executable = shutil.which("tectonic") or (str(pinned_binary) if pinned_binary.is_file() and pinned_binary.stat().st_mode & 0o111 else None)
    if not executable: raise ResumeLayoutError("LaTeX renderer is not installed. Contact the administrator to complete the Tectonic deployment.")
    template = Template(files("app").joinpath("resume_template.tex").read_text(encoding="utf-8"))
    tex = template.substitute(name=_latex(data["header"].get("name", "")), headline=_latex(data["header"].get("headline", "")), contact=_latex(data["header"].get("contact", "")), body=_body(data))
    with tempfile.TemporaryDirectory(prefix="resume-latex-") as directory:
        work = Path(directory); source = work / "resume.tex"; source.write_text(tex, encoding="utf-8")
        result = subprocess.run([executable, "-X", "compile", "--outdir", str(work), str(source)], capture_output=True, text=True, timeout=60, check=False)
        output = work / "resume.pdf"
        if result.returncode or not output.exists(): raise ResumeLayoutError("LaTeX could not render this resume template.")
        pdf = output.read_bytes(); pages = len(PdfReader(BytesIO(pdf)).pages)
    if pages != target_page_count: raise ResumeLayoutError(f"Resume layout requires {pages} page(s), but the uploaded resume requires exactly {target_page_count} page(s).")
    return pdf
