from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from html import unescape
from typing import Any


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sanitize_filename(value: str, default: str = "artifact") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    cleaned = cleaned.strip("-.")
    return cleaned or default


def get_first(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def clean_scalar(value: Any) -> str | None:
    if value is None:
        return None
    text = normalize_rich_text(str(value)).strip()
    return text or None


def normalize_rich_text(value: str) -> str:
    text = unescape(value)
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
    text = re.sub(r"(?i)</\s*(div|p|li|tr|td|th|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?s)<[^>]*>", "", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def parse_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [token for token in (clean_scalar(item) for item in value) if token is not None]

    text = clean_scalar(value)
    if text is None:
        return []

    if text.startswith("["):
        try:
            raw_list = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} looks like JSON but could not be parsed: {exc}") from exc
        if not isinstance(raw_list, list):
            raise ValueError(f"{field_name} JSON input must be an array.")
        return [token for token in (clean_scalar(item) for item in raw_list) if token is not None]

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" in normalized:
        return [line.strip() for line in normalized.split("\n") if line.strip()]

    delimiter = ";" if ";" in normalized and "," not in normalized else ","
    tokens = [token.strip() for token in normalized.split(delimiter)]
    parsed = [token for token in tokens if token]
    if not parsed:
        raise ValueError(f"{field_name} did not contain any usable values.")
    return parsed
