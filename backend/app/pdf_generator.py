from io import BytesIO
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

def build_resume_pdf(sections, rewritten_experience: str) -> bytes:
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=LETTER, rightMargin=.7*inch, leftMargin=.7*inch, topMargin=.6*inch, bottomMargin=.6*inch)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=18, spaceAfter=5)
    heading = ParagraphStyle("Heading", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor="#183B56", spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontName="Helvetica", fontSize=9, leading=12, spaceAfter=3)
    story = []
    for section in sections:
        h = section.get("heading") or "Resume"
        story.append(Paragraph(h, title if len(story) == 0 else heading))
        story.append(HRFlowable(width="100%", thickness=.5, color="#A7C4D4", spaceAfter=5))
        content = rewritten_experience if rewritten_experience is not None and h.lower().strip() in {"experience", "work experience", "professional experience", "employment history"} else section.get("content", "")
        for line in content.splitlines():
            line = line.strip()
            if line:
                safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                story.append(Paragraph(safe, body))
    doc.build(story)
    return output.getvalue()
