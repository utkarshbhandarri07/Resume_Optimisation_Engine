"""Backward-compatible entry point for the fixed-page LaTeX renderer."""
from .resume_layout import render_pdf


def build_resume_pdf(template_data: dict, target_page_count: int) -> bytes:
    return render_pdf(template_data, target_page_count)
