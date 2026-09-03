from io import BytesIO
from pathlib import Path
import re
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

def parse_resume(data: bytes, filename: str):
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)
    elif suffix == ".docx":
        text = "\n".join(p.text for p in Document(BytesIO(data)).paragraphs)
    else:
        raise ValueError("Only PDF and DOCX resumes are supported")
    text = text.strip()
    if not text:
        raise ValueError("The resume contains no extractable text")
    sections = _sections(text)
    exp = next((s["content"] for s in sections if s["heading"].lower().strip() in HEADINGS), "")
    if not exp:
        raise ValueError("Could not identify an Experience section")
    return text, exp, sections
