"""
PDF and TXT export generation using ReportLab.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

import config


def _styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="TitleCustom",
            parent=styles["Title"],
            fontSize=22,
            textColor=colors.HexColor("#4F46E5"),
            spaceAfter=12,
            alignment=TA_CENTER,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeader",
            parent=styles["Heading2"],
            fontSize=14,
            textColor=colors.HexColor("#312E81"),
            spaceBefore=16,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyCustom",
            parent=styles["BodyText"],
            fontSize=11,
            leading=15,
            spaceAfter=6,
        )
    )
    return styles


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _add_section(story: list, styles, title: str, content: str) -> None:
    story.append(Paragraph(_escape(title), styles["SectionHeader"]))
    story.append(Paragraph(_escape(content), styles["BodyCustom"]))
    story.append(Spacer(1, 0.15 * inch))


def _add_bullet_section(story: list, styles, title: str, items: List[str]) -> None:
    story.append(Paragraph(_escape(title), styles["SectionHeader"]))
    if not items:
        story.append(Paragraph("None recorded.", styles["BodyCustom"]))
    else:
        for item in items:
            story.append(Paragraph(f"• {_escape(item)}", styles["BodyCustom"]))
    story.append(Spacer(1, 0.15 * inch))


def generate_pdf(summary: Dict[str, Any], session_id: str) -> Path:
    """Create PDF export and return file path."""
    export_dir = config.EXPORT_FOLDER / session_id
    export_dir.mkdir(parents=True, exist_ok=True)
    filename = f"meeting_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = export_dir / filename

    doc = SimpleDocTemplate(
        str(filepath),
        pagesize=letter,
        rightMargin=54,
        leftMargin=54,
        topMargin=54,
        bottomMargin=54,
    )
    styles = _styles()
    story: list = []

    story.append(Paragraph("AI Meeting Notes and Summary Generator", styles["TitleCustom"]))
    story.append(
        Paragraph(
            f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}",
            styles["BodyCustom"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    _add_section(story, styles, "Meeting Overview", summary.get("overview", ""))
    _add_bullet_section(story, styles, "Discussion Points", summary.get("discussion_points", []))
    _add_bullet_section(story, styles, "Key Decisions", summary.get("decisions", []))
    _add_bullet_section(story, styles, "Action Items", summary.get("action_items", []))
    _add_section(story, styles, "Final Conclusion", summary.get("final_conclusion", ""))

    def _footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.grey)
        page_num = canvas.getPageNumber()
        canvas.drawCentredString(letter[0] / 2, 30, f"Page {page_num}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return filepath


def generate_txt(summary: Dict[str, Any], session_id: str) -> Path:
    """Create plain text export and return file path."""
    export_dir = config.EXPORT_FOLDER / session_id
    export_dir.mkdir(parents=True, exist_ok=True)
    filename = f"meeting_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    filepath = export_dir / filename

    lines = [
        "AI Meeting Notes and Summary Generator",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "=" * 60,
        "MEETING OVERVIEW",
        "=" * 60,
        summary.get("overview", ""),
        "",
        "DISCUSSION POINTS",
        "-" * 40,
    ]
    for point in summary.get("discussion_points", []):
        lines.append(f"• {point}")

    lines.extend(["", "KEY DECISIONS", "-" * 40])
    for decision in summary.get("decisions", []):
        lines.append(f"• {decision}")

    lines.extend(["", "ACTION ITEMS", "-" * 40])
    for action in summary.get("action_items", []):
        lines.append(f"• {action}")

    lines.extend(
        [
            "",
            "FINAL CONCLUSION",
            "-" * 40,
            summary.get("final_conclusion", ""),
            "",
        ]
    )

    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath
