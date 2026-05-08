from __future__ import annotations

import csv
import json
import secrets
import string
from io import StringIO
from html import unescape
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from .exceptions import PayloadValidationError


BUILDING_NAME_KEYS = ("building_name", "Building_Name", "Deal_Name", "deal_name", "name", "Name")
CITY_KEYS = ("city", "City", "Ville_de_l_immeuble", "ville_de_l_immeuble")
CRM_RECORD_ID_KEYS = ("crm_record_id", "CRM_Record_Id", "record_id", "Record_Id", "Fiche_Id", "fiche_id")
TEMPLATE_NAME_KEYS = ("template_name", "Template_Name")
WORKDRIVE_KEYS = (
    "workdrive_folder_id",
    "Workdrive_folder_id",
    "workdrive_folder",
    "Workdrive_folder",
    "WorkDrive_folder",
    "workdrive_url",
)
SSID_PREFIX_KEYS = ("ssid_prefix", "SSID_Prefix")
UNITS_KEYS = ("units", "Units", "unit_s", "Unit_s", "unit_list")
SSIDS_KEYS = ("ssids", "SSIDs", "ssid_list", "SSID_List", "SSID_s")
PASSWORDS_KEYS = ("passwords", "Passwords", "password_list", "Mots_de_passes", "PASSWORD_List")
UNIT_LABEL_KEYS = ("unit_labels", "Unit_Labels", "unit_label_list")
AUTH_TYPE_KEYS = ("auth_type", "AUTH_TYPE")
HIDDEN_KEYS = ("hidden", "Hidden")
PREDEFINED_KEYS = ("predefined", "Predefined", "Predfined", "predfined")

WORKDRIVE_QUERY_KEYS = ("id", "folder_id", "resource_id", "parent_id")
NUMERIC_IDENTIFIER_RE = re.compile(r"^\d+$")
PASSWORD_SPECIALS = "*!$@#"
SAFE_PASSWORD_LETTERS = "abcdefghjkmnopqrstuvwxyz"


def _get_first(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _get_first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> tuple[bool, Any]:
    for key in keys:
        if key in mapping:
            return True, mapping[key]
    return False, None


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _clean_scalar(value: Any) -> str | None:
    text = _stringify(value)
    if text is None:
        return None
    cleaned = normalize_rich_text(text).strip()
    return cleaned or None


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


def _load_json_list(text: str, field_name: str) -> list[str] | None:
    if not text.startswith("["):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PayloadValidationError(f"{field_name} looks like JSON but could not be parsed: {exc}") from exc
    if not isinstance(payload, list):
        raise PayloadValidationError(f"{field_name} JSON input must be an array.")
    return [_clean_csv_token(item, field_name) for item in payload if _clean_csv_token(item, field_name) is not None]


def _clean_csv_token(value: Any, field_name: str) -> str | None:
    text = _stringify(value)
    if text is None:
        return None
    cleaned = text.strip()
    if cleaned in {"", "null", "None"}:
        return None
    return cleaned


def _parse_delimited_string(text: str, field_name: str) -> list[str]:
    text = normalize_rich_text(text)
    json_list = _load_json_list(text, field_name)
    if json_list is not None:
        return json_list

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if normalized == "":
        return []

    if "\n" in normalized:
        return [token for line in normalized.split("\n") if (token := _clean_csv_token(line, field_name)) is not None]

    delimiter = ","
    if ";" in normalized and "," not in normalized:
        delimiter = ";"

    reader = csv.reader(StringIO(normalized), delimiter=delimiter, skipinitialspace=True)
    try:
        row = next(reader)
    except StopIteration:
        return []
    return [token for token in (_clean_csv_token(item, field_name) for item in row) if token is not None]


def parse_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [token for token in (_clean_csv_token(item, field_name) for item in value) if token is not None]

    text = _stringify(value)
    if text is None:
        return []
    return _parse_delimited_string(text, field_name)


def parse_bool_flag(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value

    text = _clean_scalar(value)
    if text is None:
        return None

    normalized = text.lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise PayloadValidationError(f"Boolean flag value '{text}' is not recognized.")


def parse_password_lists(mapping: dict[str, Any]) -> list[str]:
    combined: list[str] = []
    for index in range(1, 10):
        part_value = _get_password_part(mapping, index)
        if part_value is None:
            continue
        combined.extend(parse_string_list(part_value, f"passwords_{index}"))
    return combined


def _get_password_part(mapping: dict[str, Any], index: int) -> Any:
    if index == 1:
        return _get_first(mapping, PASSWORDS_KEYS)

    part_candidates: list[str] = []
    for key in PASSWORDS_KEYS:
        part_candidates.append(f"{key}_{index}")
        part_candidates.append(f"{key}{index}")
    return _get_first(mapping, tuple(part_candidates))


def normalize_ssid_prefix(mapping: dict[str, Any]) -> str:
    is_present, raw_value = _get_first_present(mapping, SSID_PREFIX_KEYS)
    if not is_present:
        return "app"

    text = _clean_scalar(raw_value)
    if text is None or text.lower() in {"empty", "null", "none", "nada"}:
        return ""
    return text


def generate_suffix(length: int = 2) -> str:
    return "".join(secrets.choice(string.ascii_lowercase) for _ in range(length))


def generate_password() -> str:
    first_digits = "".join(secrets.choice(string.digits) for _ in range(4))
    letters = "".join(secrets.choice(SAFE_PASSWORD_LETTERS) for _ in range(2))
    second_digits = "".join(secrets.choice(string.digits) for _ in range(4))
    specials = "".join(secrets.choice(PASSWORD_SPECIALS) for _ in range(2))
    return f"{first_digits}{letters}{second_digits}{specials}"


def generate_passwords(count: int) -> list[str]:
    return [generate_password() for _ in range(count)]


def has_numeric_identifiers(values: list[str]) -> bool:
    return bool(values) and all(NUMERIC_IDENTIFIER_RE.fullmatch(value) for value in values)


def extract_workdrive_folder_id(value: Any) -> str | None:
    text = _clean_scalar(value)
    if text is None:
        return None

    if "/" not in text and "?" not in text and "#" not in text:
        return text

    parsed = urlparse(text)
    query = parse_qs(parsed.query)
    for key in WORKDRIVE_QUERY_KEYS:
        values = query.get(key)
        if values:
            candidate = _clean_scalar(values[0])
            if candidate:
                return candidate

    fragment = parsed.fragment.strip("/")
    if fragment:
        fragment_parts = [part for part in fragment.split("/") if part]
        if fragment_parts:
            return fragment_parts[-1]

    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts:
        return path_parts[-1]

    raise PayloadValidationError(f"Could not extract a WorkDrive folder id from '{text}'.")


def _build_records_from_ssids(
    mapping: dict[str, Any],
    ssids: list[str],
    passwords: list[str],
    unit_labels: list[str],
) -> list[dict[str, Any]]:
    if not ssids:
        raise PayloadValidationError("No SSIDs were provided.")
    if len(ssids) != len(passwords):
        raise PayloadValidationError(
            f"SSID count ({len(ssids)}) does not match password count ({len(passwords)})."
        )
    if unit_labels and len(unit_labels) != len(ssids):
        raise PayloadValidationError(
            f"unit_labels count ({len(unit_labels)}) does not match SSID count ({len(ssids)})."
        )

    auth_type = _clean_scalar(_get_first(mapping, AUTH_TYPE_KEYS)) or "WPA"
    hidden_value = _get_first(mapping, HIDDEN_KEYS)
    hidden = bool(hidden_value) if isinstance(hidden_value, bool) else str(hidden_value).strip().lower() == "true"

    records: list[dict[str, Any]] = []
    for index, ssid in enumerate(ssids):
        record = {
            "ssid": ssid,
            "password": passwords[index],
            "auth_type": auth_type,
            "hidden": hidden,
        }
        if unit_labels:
            record["unit_label"] = unit_labels[index]
        records.append(record)
    return records


def _build_records_from_units(mapping: dict[str, Any], units: list[str], passwords: list[str]) -> list[dict[str, Any]]:
    if not units:
        raise PayloadValidationError("No units were provided.")
    if len(units) != len(passwords):
        raise PayloadValidationError(
            f"Unit count ({len(units)}) does not match password count ({len(passwords)})."
        )

    prefix = normalize_ssid_prefix(mapping)
    auth_type = _clean_scalar(_get_first(mapping, AUTH_TYPE_KEYS)) or "WPA"
    hidden_value = _get_first(mapping, HIDDEN_KEYS)
    hidden = bool(hidden_value) if isinstance(hidden_value, bool) else str(hidden_value).strip().lower() == "true"

    records: list[dict[str, Any]] = []
    for index, unit in enumerate(units):
        ssid = f"{prefix}{unit}_{generate_suffix()}" if prefix else unit
        records.append(
            {
                "ssid": ssid,
                "password": passwords[index],
                "auth_type": auth_type,
                "hidden": hidden,
                "unit_label": unit,
            }
        )
    return records


def normalize_payload(raw_payload: Any) -> dict[str, Any]:
    if isinstance(raw_payload, list):
        return {"building_name": "wifi-batch", "records": raw_payload}
    if not isinstance(raw_payload, dict):
        raise PayloadValidationError("Payload must be a JSON object or an array of records.")

    payload = dict(raw_payload)
    building_name = _clean_scalar(_get_first(payload, BUILDING_NAME_KEYS))
    city = _clean_scalar(_get_first(payload, CITY_KEYS))
    crm_record_id = _clean_scalar(_get_first(payload, CRM_RECORD_ID_KEYS))
    template_name = _clean_scalar(_get_first(payload, TEMPLATE_NAME_KEYS)) or "Opticable_Template_01"
    workdrive_folder_id = extract_workdrive_folder_id(_get_first(payload, WORKDRIVE_KEYS))

    if "records" in payload:
        normalized = dict(payload)
        if building_name is not None:
            normalized["building_name"] = building_name
        if workdrive_folder_id is not None:
            normalized["workdrive_folder_id"] = workdrive_folder_id
        if city is not None:
            normalized["city"] = city
        if crm_record_id is not None:
            normalized["crm_record_id"] = crm_record_id
        normalized["template_name"] = template_name
        return normalized

    ssids = parse_string_list(_get_first(payload, SSIDS_KEYS), "ssids")
    units = parse_string_list(_get_first(payload, UNITS_KEYS), "units")
    unit_labels = parse_string_list(_get_first(payload, UNIT_LABEL_KEYS), "unit_labels")
    predefined = parse_bool_flag(_get_first(payload, PREDEFINED_KEYS))

    if not building_name:
        raise PayloadValidationError("Missing building_name or Deal_Name.")

    record_count_source = ssids or units
    if not record_count_source:
        raise PayloadValidationError(
            "No SSIDs or units were provided. Send records, ssids/ssid_list, or units/Unit_s."
        )

    passwords = parse_password_lists(payload)
    passwords_generated = predefined is False or (predefined is None and not passwords)
    if passwords_generated:
        passwords = generate_passwords(len(record_count_source))
    elif not passwords:
        raise PayloadValidationError(
            "No passwords were provided. Send records, passwords, Mots_de_passes, or numbered password fields such as Mots_de_passes_2."
        )

    if ssids:
        if has_numeric_identifiers(ssids):
            records = _build_records_from_units(payload, ssids, passwords)
        else:
            records = _build_records_from_ssids(payload, ssids, passwords, unit_labels or units)
    else:
        records = _build_records_from_units(payload, units, passwords)

    normalized = {
        "building_name": building_name,
        "city": city,
        "crm_record_id": crm_record_id,
        "passwords_generated": passwords_generated,
        "template_name": template_name,
        "records": records,
    }
    if workdrive_folder_id is not None:
        normalized["workdrive_folder_id"] = workdrive_folder_id
    return normalized
