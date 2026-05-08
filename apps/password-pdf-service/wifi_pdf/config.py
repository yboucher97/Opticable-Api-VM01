from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .exceptions import ConfigurationError
from .utils import PROJECT_ROOT, resolve_repo_path


DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "wifi_pdf" / "brand_settings.json"
CONFIG_PATH_ENV = "WIFI_PDF_CONFIG_PATH"


@dataclass(slots=True)
class BrandingSettings:
    brand_name: str
    logo_path: Path | None
    support_email: str | None
    support_phone: str | None
    primary_color: str
    secondary_color: str
    accent_color: str
    text_color: str
    muted_text_color: str


@dataclass(slots=True)
class FontSettings:
    regular_name: str
    bold_name: str
    regular_path: Path | None
    bold_path: Path | None
    fallback_regular: str
    fallback_bold: str


@dataclass(slots=True)
class LayoutSettings:
    page_size: str
    margin_points: int
    header_height_points: int
    card_corner_radius: int


@dataclass(slots=True)
class OutputSettings:
    root_dir: Path
    manifest_filename: str
    keep_qr_images: bool


@dataclass(slots=True)
class ApiSettings:
    api_key_env: str


@dataclass(slots=True)
class CrmSettings:
    enabled: bool
    api_base_url: str
    module_api_name: str
    primary_password_field: str
    generated_ssids_field: str
    overflow_password_field: str
    primary_password_limit: int


@dataclass(slots=True)
class WorkDriveSettings:
    enabled: bool
    api_base_url: str
    accounts_base_url: str
    parent_folder_id: str | None
    target_folder_name: str
    overwrite_existing_files: bool
    cleanup_local_after_upload: bool
    upload_individual_pdfs: bool
    upload_merged_pdf: bool
    upload_txt_export: bool
    upload_zip_export: bool
    upload_ya_export: bool
    upload_field_name: str


@dataclass(slots=True)
class AppSettings:
    config_path: Path
    branding: BrandingSettings
    fonts: FontSettings
    layout: LayoutSettings
    output: OutputSettings
    api: ApiSettings
    crm: CrmSettings
    workdrive: WorkDriveSettings


def _require_dict(payload: object, section_name: str) -> dict:
    if not isinstance(payload, dict):
        raise ConfigurationError(f"Config section '{section_name}' must be an object.")
    return payload


def load_settings(config_path: str | Path | None = None) -> AppSettings:
    configured_path = config_path or os.getenv(CONFIG_PATH_ENV)
    target = resolve_repo_path(configured_path) if configured_path else DEFAULT_CONFIG_PATH
    if not target or not target.exists():
        raise ConfigurationError(f"Config file not found: {target}")

    payload = json.loads(target.read_text(encoding="utf-8"))
    branding = _require_dict(payload.get("branding"), "branding")
    fonts = _require_dict(payload.get("fonts"), "fonts")
    layout = _require_dict(payload.get("layout"), "layout")
    output = _require_dict(payload.get("output"), "output")
    api = _require_dict(payload.get("api"), "api")
    crm = _require_dict(payload.get("crm") or {}, "crm")
    workdrive = _require_dict(payload.get("workdrive"), "workdrive")

    return AppSettings(
        config_path=target,
        branding=BrandingSettings(
            brand_name=str(branding["brand_name"]),
            logo_path=resolve_repo_path(branding.get("logo_path")),
            support_email=branding.get("support_email"),
            support_phone=branding.get("support_phone"),
            primary_color=str(branding["primary_color"]),
            secondary_color=str(branding["secondary_color"]),
            accent_color=str(branding["accent_color"]),
            text_color=str(branding["text_color"]),
            muted_text_color=str(branding["muted_text_color"]),
        ),
        fonts=FontSettings(
            regular_name=str(fonts["regular_name"]),
            bold_name=str(fonts["bold_name"]),
            regular_path=resolve_repo_path(fonts.get("regular_path")),
            bold_path=resolve_repo_path(fonts.get("bold_path")),
            fallback_regular=str(fonts["fallback_regular"]),
            fallback_bold=str(fonts["fallback_bold"]),
        ),
        layout=LayoutSettings(
            page_size=str(layout["page_size"]),
            margin_points=int(layout["margin_points"]),
            header_height_points=int(layout["header_height_points"]),
            card_corner_radius=int(layout["card_corner_radius"]),
        ),
        output=OutputSettings(
            root_dir=resolve_repo_path(output["root_dir"]) or PROJECT_ROOT / "output" / "pdf" / "wifi",
            manifest_filename=str(output["manifest_filename"]),
            keep_qr_images=bool(output["keep_qr_images"]),
        ),
        api=ApiSettings(api_key_env=str(api["api_key_env"])),
        crm=CrmSettings(
            enabled=bool(crm.get("enabled", True)),
            api_base_url=str(crm.get("api_base_url", "https://www.zohoapis.com/crm/v7")).rstrip("/"),
            module_api_name=str(crm.get("module_api_name", "Services")),
            primary_password_field=str(crm.get("primary_password_field", "Passwords")),
            generated_ssids_field=str(crm.get("generated_ssids_field", "SSIDs")),
            overflow_password_field=str(crm.get("overflow_password_field", "")),
            primary_password_limit=int(crm.get("primary_password_limit", 150)),
        ),
        workdrive=WorkDriveSettings(
            enabled=bool(workdrive["enabled"]),
            api_base_url=str(workdrive["api_base_url"]).rstrip("/"),
            accounts_base_url=str(workdrive["accounts_base_url"]).rstrip("/"),
            parent_folder_id=workdrive.get("parent_folder_id"),
            target_folder_name=str(workdrive.get("target_folder_name", "Document/Passwords")).strip(),
            overwrite_existing_files=bool(workdrive.get("overwrite_existing_files", True)),
            cleanup_local_after_upload=bool(workdrive["cleanup_local_after_upload"]),
            upload_individual_pdfs=bool(workdrive["upload_individual_pdfs"]),
            upload_merged_pdf=bool(workdrive["upload_merged_pdf"]),
            upload_txt_export=bool(workdrive.get("upload_txt_export", True)),
            upload_zip_export=bool(workdrive.get("upload_zip_export", True)),
            upload_ya_export=bool(workdrive.get("upload_ya_export", True)),
            upload_field_name=str(workdrive["upload_field_name"]),
        ),
    )
