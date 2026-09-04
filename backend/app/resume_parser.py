from io import BytesIO
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from pypdf import PdfReader
from docx import Document

HEADINGS = {"experience", "work experience", "professional experience", "employment history"}

def _sections(text: str) -> list[dict[str, str]]:
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
    sections, current = [], {"heading": "", "content": []}
    for line in lines:
        normalized = re.sub(r"[^a-z ]", "", line.lower()).strip()
        heading = normalized in HEADINGS or (len(line) < 55 and line.upper() == line and len(line.split()) <= 6)
        if heading and current["heading"]:
            sections.append({"heading": current["heading"], "content": "\n".join(current["content"]).strip()})
            current = {"heading": line, "content": []}
        elif heading:
            current["heading"] = line
        else:
            current["content"].append(line)
    if current["heading"] or current["content"]:
        sections.append({"heading": current["heading"] or "Resume", "content": "\n".join(current["content"]).strip()})
    return sections

def _docx_page_count(data: bytes, filename: str) -> int:
    """Use LibreOffice's rendered PDF, not DOCX metadata, as the page baseline."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise ValueError("DOCX page preservation requires the server's LibreOffice renderer.")
    with tempfile.TemporaryDirectory(prefix="resume-docx-") as directory:
        source = Path(directory) / (Path(filename).stem + ".docx")
        source.write_bytes(data)
        result = subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", directory, str(source)], capture_output=True, text=True, timeout=60, check=False)
        rendered = source.with_suffix(".pdf")
        if result.returncode or not rendered.exists():
            raise ValueError("Could not render the DOCX to determine its page count.")
        return len(PdfReader(BytesIO(rendered.read_bytes())).pages)


def parse_resume(data: bytes, filename: str):
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        pdf = PdfReader(BytesIO(data)); text = "\n".join(page.extract_text() or "" for page in pdf.pages); target_page_count = len(pdf.pages)
    elif suffix == ".docx":
        text = "\n".join(p.text for p in Document(BytesIO(data)).paragraphs); target_page_count = _docx_page_count(data, filename)
    else:
        raise ValueError("Only PDF and DOCX resumes are supported")
    text = text.strip()
    if not text:
        raise ValueError("The resume contains no extractable text")
    sections = _sections(text)
    exp = next((s["content"] for s in sections if s["heading"].lower().strip() in HEADINGS), "")
    if not exp:
        raise ValueError("Could not identify an Experience section")
    return text, exp, sections, target_page_count
