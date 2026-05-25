from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from ..models import WifiRecord
from ..utils import resolve_repo_path
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


COTRECK_LOGO_PATH = resolve_repo_path("assets/wifi_pdf/corteck/logo.png")

COTRECK_TEMPLATE_01_THEME = {
    "page_background": colors.HexColor("#F5F9FF"),
    "header_background": colors.white,
    "header_rule": colors.HexColor("#004FB6"),
    "panel_background": colors.white,
    "panel_border": colors.HexColor("#C8D8EE"),
    "label_band": colors.HexColor("#004FB6"),
    "label_text": colors.white,
    "value_text": colors.HexColor("#101820"),
    "section_background": colors.white,
    "section_border": colors.HexColor("#C8D8EE"),
    "section_title_text": colors.HexColor("#101820"),
    "body_text": colors.HexColor("#2D3640"),
    "bullet": colors.HexColor("#004FB6"),
    "note_background": colors.HexColor("#EAF2FC"),
    "note_text": colors.HexColor("#101820"),
    "support_background": colors.white,
    "support_border": colors.HexColor("#C8D8EE"),
    "footer_background": colors.HexColor("#004FB6"),
    "footer_text": colors.white,
    "qr_border": colors.HexColor("#C8D8EE"),
    "meta_background": colors.HexColor("#EAF2FC"),
    "meta_text": colors.HexColor("#263B55"),
}

SUPPORT_TITLE = "Support technique | Technical support"
SUPPORT_ITEMS = [
    "www.corteck.ca",
    "support@corteck.ca",
    "514.316.9302 #2",
]
FOOTER_LINE = "Corteck | support@corteck.ca | 514.316.9302 #2"
FR_ITEMS_WITHOUT_TERMS = [
    item for item in FR_ITEMS if "termes et conditions" not in item and "opticable.ca/internet/termes" not in item
]
EN_ITEMS_WITHOUT_TERMS = [
    item for item in EN_ITEMS if "terms and conditions" not in item and "opticable.ca/internet/terms" not in item
]


def _draw_section_title(
    canvas: Canvas,
    x: float,
    y: float,
    width: float,
    title: str,
    fonts: dict[str, str],
) -> None:
    canvas.setFillColor(COTRECK_TEMPLATE_01_THEME["section_title_text"])
    canvas.setFont(fonts["bold"], 10)
    canvas.drawString(x, y, title)
    canvas.setStrokeColor(COTRECK_TEMPLATE_01_THEME["section_border"])
    canvas.setLineWidth(0.9)
    canvas.line(x, y - 5, x + width, y - 5)


def _paragraph_height(
    text: str,
    width: float,
    font_name: str,
    font_size: float,
    leading: float,
) -> float:
    style = ParagraphStyle(
        name=f"height-{font_name}-{font_size}-{leading}",
        fontName=font_name,
        fontSize=font_size,
        leading=leading,
        spaceAfter=0,
        spaceBefore=0,
    )
    paragraph = Paragraph(text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)
    _, height = paragraph.wrap(width, 10_000)
    return height


def _centered_bullet_start_y(
    items: list[str],
    available_top: float,
    available_bottom: float,
    width: float,
    font_name: str,
    font_size: float,
    leading: float,
    gap: float,
) -> float:
    text_width = width - 12
    list_height = sum(_paragraph_height(item, text_width, font_name, font_size, leading) for item in items)
    list_height += gap * max(len(items) - 1, 0)
    available_height = available_top - available_bottom
    return available_top - max((available_height - list_height) / 2, 0)


def _draw_cotreck_bullet_list(
    canvas: Canvas,
    items: list[str],
    x: float,
    y_top: float,
    width: float,
    font_name: str,
    font_size: float,
    text_color: colors.Color,
    bullet_color: colors.Color,
    leading: float,
    gap: float,
) -> float:
    current_top = y_top
    for item in items:
        canvas.saveState()
        canvas.setFillColor(bullet_color)
        canvas.circle(x + 3, current_top - 7.5, 1.35, stroke=0, fill=1)
        canvas.restoreState()
        height = draw_paragraph(
            canvas,
            item,
            x + 12,
            current_top,
            width - 12,
            font_name,
            font_size,
            text_color,
            leading=leading,
        )
        current_top -= height + gap
    return current_top


def draw_cotreck_basic01(
    canvas: Canvas,
    record: WifiRecord,
    building_name: str,
    qr_path: Path,
    settings: Any,
    fonts: dict[str, str],
    sheet_number: int,
    sheet_total: int,
) -> None:
    theme = COTRECK_TEMPLATE_01_THEME
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
    instruction_height = 208
    support_height = 122
    support_qr_card = 100
    location_label = record.unit_label or building_name

    canvas.setTitle(f"{location_label} - {record.ssid}")
    canvas.setAuthor("Corteck")
    canvas.setFillColor(theme["page_background"])
    canvas.rect(0, 0, page_width, page_height, fill=1, stroke=0)

    canvas.setFillColor(theme["header_background"])
    canvas.rect(0, header_bottom, page_width, header_height, fill=1, stroke=0)
    header_qr_x = page_width - margin - header_qr_width
    canvas.setFillColor(theme["header_rule"])
    canvas.rect(margin, header_bottom + 10, header_qr_x - margin - header_qr_gap, 6, fill=1, stroke=0)
    draw_logo(canvas, COTRECK_LOGO_PATH, margin, header_bottom + 30, 220, 38)

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

    instructions_y = qr_note_y - 226
    for column_index, (title, items) in enumerate(
        ((FR_TITLE, FR_ITEMS_WITHOUT_TERMS), (EN_TITLE, EN_ITEMS_WITHOUT_TERMS))
    ):
        box_x = margin + (column_index * (column_width + column_gap))
        draw_card(canvas, box_x, instructions_y, column_width, instruction_height, theme["section_background"], radius, theme["section_border"])
        _draw_section_title(canvas, box_x + 14, instructions_y + instruction_height - 20, column_width - 28, title, fonts)
        bullet_font_size = 9.35
        bullet_leading = 11.2
        bullet_gap = 2.8
        bullet_width = column_width - 32
        bullet_y = _centered_bullet_start_y(
            items,
            instructions_y + instruction_height - 40,
            instructions_y + 14,
            bullet_width,
            fonts["regular"],
            bullet_font_size,
            bullet_leading,
            bullet_gap,
        ) + 9
        _draw_cotreck_bullet_list(
            canvas,
            items,
            box_x + 16,
            bullet_y,
            bullet_width,
            fonts["regular"],
            bullet_font_size,
            theme["body_text"],
            theme["bullet"],
            leading=bullet_leading,
            gap=bullet_gap,
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
