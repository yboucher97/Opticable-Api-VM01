from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.pdfgen.canvas import Canvas

from ..models import WifiRecord
from .common import (
    EN_ITEMS,
    EN_TITLE,
    FR_ITEMS,
    FR_TITLE,
    KEEP_LINE,
    draw_bullet_list,
    draw_card,
    draw_label_value_panel,
    draw_logo,
    draw_paragraph,
    draw_qr,
    fit_font_size,
)


OPTICABLE_TEMPLATE_01_THEME = {
    "page_background": colors.HexColor("#F7FBF8"),
    "header_background": colors.white,
    "header_rule": colors.HexColor("#56B980"),
    "panel_background": colors.white,
    "panel_border": colors.HexColor("#D6E8DD"),
    "label_band": colors.HexColor("#2E8A67"),
    "label_text": colors.white,
    "value_text": colors.HexColor("#222328"),
    "section_background": colors.white,
    "section_border": colors.HexColor("#D6E8DD"),
    "section_title_text": colors.HexColor("#274035"),
    "body_text": colors.HexColor("#2F3338"),
    "bullet": colors.HexColor("#2E8A67"),
    "note_background": colors.HexColor("#EEF5F1"),
    "note_text": colors.HexColor("#274035"),
    "support_background": colors.white,
    "support_border": colors.HexColor("#D6E8DD"),
    "footer_background": colors.HexColor("#2E8A67"),
    "footer_text": colors.white,
    "qr_border": colors.HexColor("#D6E8DD"),
    "meta_background": colors.HexColor("#F1F6F3"),
    "meta_text": colors.HexColor("#355446"),
}

SUPPORT_TITLE = "Support technique | Technical support"
SUPPORT_ITEMS = [
    "www.opticable.ca",
    "support@opticable.ca",
    "514-316-7236 #2",
]
FOOTER_LINE = "Opticable | support@opticable.ca | 514-316-7236 #2"


def _draw_section_title(
    canvas: Canvas,
    x: float,
    y: float,
    width: float,
    title: str,
    fonts: dict[str, str],
) -> None:
    canvas.setFillColor(OPTICABLE_TEMPLATE_01_THEME["section_title_text"])
    canvas.setFont(fonts["bold"], 10)
    canvas.drawString(x, y, title)
    canvas.setStrokeColor(OPTICABLE_TEMPLATE_01_THEME["section_border"])
    canvas.setLineWidth(0.9)
    canvas.line(x, y - 5, x + width, y - 5)


def draw_opticable_template_01(
    canvas: Canvas,
    record: WifiRecord,
    building_name: str,
    qr_path: Path,
    settings: Any,
    fonts: dict[str, str],
    sheet_number: int,
    sheet_total: int,
) -> None:
    theme = OPTICABLE_TEMPLATE_01_THEME
    page_width, page_height = canvas._pagesize
    margin = 24
    radius = 13
    header_height = 88
    header_bottom = page_height - header_height
    panel_width = page_width - (2 * margin)
    label_width = 224
    column_gap = 14
    column_width = (panel_width - column_gap) / 2
    header_qr_width = 92
    header_qr_gap = 12
    instruction_height = 236
    support_height = 122
    support_qr_card = 100
    location_label = building_name
    if record.unit_label:
        location_label = f"{building_name} - {record.unit_label}"

    canvas.setTitle(f"{location_label} - {record.ssid}")
    canvas.setAuthor(settings.branding.brand_name)
    canvas.setFillColor(theme["page_background"])
    canvas.rect(0, 0, page_width, page_height, fill=1, stroke=0)

    canvas.setFillColor(theme["header_background"])
    canvas.rect(0, header_bottom, page_width, header_height, fill=1, stroke=0)
    header_qr_x = page_width - margin - header_qr_width
    canvas.setFillColor(theme["header_rule"])
    canvas.rect(margin, header_bottom + 10, header_qr_x - margin - header_qr_gap, 6, fill=1, stroke=0)
    draw_logo(canvas, settings.branding.logo_path, margin, header_bottom + 32, 220, 34)

    draw_card(
        canvas,
        header_qr_x,
        header_bottom + 8,
        header_qr_width,
        70,
        colors.white,
        14,
        theme["qr_border"],
    )
    draw_qr(canvas, qr_path, header_qr_x + 12, header_bottom + 14, 66, 58)

    info_y = header_bottom - 110
    canvas.setFillColor(theme["meta_text"])
    location_font_size = fit_font_size(location_label, fonts["bold"], panel_width - 24, 11, 8)
    canvas.setFont(fonts["bold"], location_font_size)
    canvas.drawCentredString(page_width / 2, info_y + 92, location_label)
    draw_label_value_panel(
        canvas,
        margin,
        info_y,
        panel_width,
        78,
        radius,
        label_width,
        fonts,
        theme,
        record.ssid,
        record.password or "",
        label_font_size=9.8,
        ssid_start_size=18,
        ssid_min_size=12,
        password_start_size=18,
        password_min_size=12,
        center_values=True,
    )

    qr_note_y = info_y - 56
    draw_card(canvas, margin, qr_note_y, panel_width, 44, theme["note_background"], 12, theme["panel_border"])
    canvas.setFillColor(theme["note_text"])
    draw_paragraph(
        canvas,
        "Scannez le code QR ou utilisez les identifiants ci-dessus pour vous connecter.<br/>"
        "Scan the QR code or use the credentials above to connect.",
        margin + 12,
        qr_note_y + 32,
        panel_width - 24,
        fonts["regular"],
        9.0,
        theme["note_text"],
        leading=10.0,
        bold_fragments=True,
    )

    instructions_y = qr_note_y - 254
    for column_index, (title, items) in enumerate(((FR_TITLE, FR_ITEMS), (EN_TITLE, EN_ITEMS))):
        box_x = margin + (column_index * (column_width + column_gap))
        draw_card(canvas, box_x, instructions_y, column_width, instruction_height, theme["section_background"], radius, theme["section_border"])
        _draw_section_title(canvas, box_x + 14, instructions_y + instruction_height - 20, column_width - 28, title, fonts)
        draw_bullet_list(
            canvas,
            items,
            box_x + 16,
            instructions_y + instruction_height - 40,
            column_width - 32,
            fonts["regular"],
            9.35,
            theme["body_text"],
            theme["bullet"],
            leading=11.8,
            gap=3.8,
        )

    keep_y = instructions_y - 30
    draw_card(canvas, margin, keep_y, panel_width, 24, theme["note_background"], 12)
    canvas.setFillColor(theme["note_text"])
    canvas.setFont(fonts["bold"], 9.1)
    canvas.drawCentredString(margin + (panel_width / 2), keep_y + 8, KEEP_LINE)

    support_y = keep_y - 126
    draw_card(canvas, margin, support_y, panel_width, support_height, theme["support_background"], radius, theme["support_border"])
    support_content_x = margin + 36
    support_qr_x = margin + panel_width - support_qr_card - 36
    support_qr_y = support_y + 11
    support_content_width = support_qr_x - support_content_x
    _draw_section_title(canvas, support_content_x, support_y + support_height - 18, support_content_width, SUPPORT_TITLE, fonts)
    draw_bullet_list(
        canvas,
        SUPPORT_ITEMS,
        support_content_x,
        support_y + support_height - 40,
        support_content_width,
        fonts["regular"],
        10.8,
        theme["body_text"],
        theme["bullet"],
        leading=12.8,
        gap=6.2,
    )
    draw_card(canvas, support_qr_x, support_qr_y, support_qr_card, support_qr_card, colors.white, 14, theme["panel_border"])
    draw_qr(canvas, qr_path, support_qr_x + 10, support_qr_y + 10, support_qr_card - 20, support_qr_card - 20)

    footer_y = support_y - 34
    draw_card(canvas, margin, footer_y, panel_width, 24, theme["footer_background"], 12)
    canvas.setFillColor(theme["footer_text"])
    canvas.setFont(fonts["bold"], 8.8)
    canvas.drawCentredString(margin + (panel_width / 2), footer_y + 8, FOOTER_LINE)
