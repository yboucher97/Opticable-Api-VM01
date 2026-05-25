from __future__ import annotations

import logging
from pathlib import Path

from reportlab.lib.pagesizes import A4, LETTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .config import AppSettings
from .exceptions import RenderingError
from .models import WifiRecord
from .templates import draw_cotreck_basic01, draw_opticable_template_01
from .utils import resolve_repo_path


PAGE_SIZE_MAP = {
    "A4": A4,
    "LETTER": LETTER,
}

ACTIVE_TEMPLATE_NAME = "Opticable Template Basic 01"
TEMPLATE_RENDERERS = {
    "Opticable Template Basic 01": draw_opticable_template_01,
    "Corteck Template Basic 01": draw_cotreck_basic01,
}
COTRECK_TEMPLATE_FONTS = {
    "regular": ("CotreckOpenSans", "assets/wifi_pdf/corteck/OpenSans-Regular.ttf"),
    "bold": ("CotreckOpenSans-Bold", "assets/wifi_pdf/corteck/OpenSans-Bold.ttf"),
}

SYSTEM_FONT_PATHS = {
    "regular": [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ],
    "bold": [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    ],
}


class PdfRenderer:
    def __init__(self, settings: AppSettings, logger: logging.Logger) -> None:
        self.settings = settings
        self.logger = logger
        self.fonts = self._register_fonts()

    def _register_font(self, internal_name: str, font_path: Path | None) -> bool:
        if not font_path or not font_path.exists():
            return False
        if internal_name in pdfmetrics.getRegisteredFontNames():
            return True
        pdfmetrics.registerFont(TTFont(internal_name, str(font_path)))
        return True

    def _find_system_font(self, kind: str) -> Path | None:
        for path in SYSTEM_FONT_PATHS[kind]:
            if path.exists():
                return path
        return None

    def _register_fonts(self) -> dict[str, str]:
        regular_name = self.settings.fonts.regular_name
        bold_name = self.settings.fonts.bold_name

        try:
            regular_ok = self._register_font(regular_name, self.settings.fonts.regular_path)
            bold_ok = self._register_font(bold_name, self.settings.fonts.bold_path)
            if not regular_ok:
                regular_ok = self._register_font(regular_name, self._find_system_font("regular"))
            if not bold_ok:
                bold_ok = self._register_font(bold_name, self._find_system_font("bold"))
        except Exception as exc:  # pragma: no cover - font loader failures depend on host fonts
            self.logger.warning("Falling back to built-in fonts because custom font loading failed: %s", exc)
            regular_ok = False
            bold_ok = False

        if not regular_ok:
            regular_name = self.settings.fonts.fallback_regular
        if not bold_ok:
            bold_name = self.settings.fonts.fallback_bold

        return {"regular": regular_name, "bold": bold_name}

    def _fonts_for_template(self, template_name: str) -> dict[str, str]:
        if template_name != "Corteck Template Basic 01":
            return self.fonts

        template_fonts: dict[str, str] = {}
        for kind, (internal_name, relative_path) in COTRECK_TEMPLATE_FONTS.items():
            if not self._register_font(internal_name, resolve_repo_path(relative_path)):
                return self.fonts
            template_fonts[kind] = internal_name
        return template_fonts

    def render(
        self,
        record: WifiRecord,
        building_name: str,
        qr_path: Path,
        output_path: Path,
        template_name: str,
        sheet_number: int,
        sheet_total: int,
    ) -> Path:
        page_size = PAGE_SIZE_MAP.get(self.settings.layout.page_size.upper(), LETTER)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        template_renderer = TEMPLATE_RENDERERS.get(template_name)
        if template_renderer is None:
            expected = "', '".join(TEMPLATE_RENDERERS)
            raise RenderingError(f"Unknown template_name '{template_name}'. Expected one of: '{expected}'.")

        try:
            pdf = canvas.Canvas(str(output_path), pagesize=page_size)
            template_renderer(
                pdf,
                record=record,
                building_name=building_name,
                qr_path=qr_path,
                settings=self.settings,
                fonts=self._fonts_for_template(template_name),
                sheet_number=sheet_number,
                sheet_total=sheet_total,
            )
            pdf.showPage()
            pdf.save()
        except Exception as exc:  # pragma: no cover - reportlab internals are not deterministic to unit test here
            raise RenderingError(f"Failed to render PDF for SSID '{record.ssid}': {exc}") from exc

        return output_path
