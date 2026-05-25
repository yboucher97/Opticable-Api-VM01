from __future__ import annotations

import secrets
import string
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import AppSettings
from .utils import clean_scalar, get_first, parse_string_list


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
SSIDS_KEYS = ("ssids", "SSIDs", "ssid_list", "SSID_List", "SSID_s")
PASSWORDS_KEYS = ("passwords", "Passwords", "password_list", "Mots_de_passes", "PASSWORD_List", "MDP")
UNITS_KEYS = ("units", "Units", "unit_s", "Unit_s", "unit_list", "ssid_identifiers", "SSID_Identifiers")
UNIT_LABEL_KEYS = ("unit_labels", "Unit_Labels", "unit_label_list")
VLAN_KEYS = ("vlans", "VLANs", "vlan_ids", "VLAN_List", "VLAN_s")
SITE_NAME_KEYS = ("site_name", "Site_Name", "omada_site_name")
REGION_KEYS = ("omada_region", "region", "Region")
TIMEZONE_KEYS = ("omada_timezone", "timezone", "Timezone")
SCENARIO_KEYS = ("omada_scenario", "scenario", "Scenario")
OMADA_OPERATION_KEYS = ("omada_operation", "omada_mutation_mode", "Omada_Operation", "Omada_Mutation_Mode")
HIDDEN_KEYS = ("hidden", "Hidden")
SSID_PREFIX_KEYS = ("ssid_prefix", "SSID_Prefix")
SSID_TEMPLATE_KEYS = ("ssid_template", "SSID_Template")
SSID_SUFFIX_LENGTH_KEYS = ("ssid_suffix_length", "SSID_Suffix_Length")
PASSWORD_SPECIALS_KEYS = ("password_specials", "PASSWORD_SPECIALS")
WORKDRIVE_QUERY_KEYS = ("id", "folder_id", "resource_id", "parent_id")
WORKFLOW_MODE_KEYS = ("workflow_mode", "Workflow_Mode")
CREDENTIAL_MODE_KEYS = ("credential_mode", "Credential_Mode")
UPLOAD_OMADA_PLAN_KEYS = ("upload_omada_plan", "Upload_Omada_Plan")
UPLOAD_INDIVIDUAL_PDFS_KEYS = ("upload_individual_pdfs", "Upload_Individual_PDFs")
UPLOAD_MERGED_PDF_KEYS = ("upload_merged_pdf", "Upload_Merged_PDF")
UPLOAD_TXT_EXPORT_KEYS = ("upload_txt_export", "Upload_TXT_Export")
UPLOAD_ZIP_EXPORT_KEYS = ("upload_zip_export", "Upload_ZIP_Export")
UPLOAD_YA_EXPORT_KEYS = ("upload_ya_export", "Upload_YA_Export")
SAFE_PASSWORD_LETTERS = "abcdefghjkmnopqrstuvwxyz"

CredentialMode = Literal["generated", "predefined"]
WorkflowMode = Literal["pdf_only", "pdf_and_site", "site_only"]
OmadaOperation = Literal["ensure", "create", "upsert", "update"]


class WorkflowRecord(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ssid: str = Field(alias="SSID", min_length=1, max_length=128)
    password: str = Field(alias="PASSWORD", min_length=1)
    hidden: bool = False
    unit_label: str | None = None
    vlan_id: int | None = None

    @field_validator("ssid")
    @classmethod
    def validate_ssid(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("SSID cannot be blank.")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("password cannot be blank.")
        return normalized

    @field_validator("unit_label")
    @classmethod
    def validate_unit_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("vlan_id")
    @classmethod
    def validate_vlan(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if not 1 <= value <= 4094:
            raise ValueError("vlan_id must be between 1 and 4094.")
        return value


class WorkflowBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    building_name: str
    city: str | None = None
    crm_record_id: str | None = None
    credential_mode: CredentialMode
    workflow_mode: WorkflowMode = "pdf_and_site"
    passwords_generated: bool = False
    ssids_generated: bool = False
    template_name: str = "Opticable_Template_01"
    workdrive_folder_id: str | None = None
    site_name: str | None = None
    omada_region: str | None = None
    omada_timezone: str | None = None
    omada_scenario: str | None = None
    omada_operation: OmadaOperation = "ensure"
    upload_omada_plan: bool = False
    upload_individual_pdfs: bool | None = None
    upload_merged_pdf: bool | None = None
    upload_txt_export: bool | None = None
    upload_zip_export: bool | None = None
    upload_ya_export: bool | None = None
    records: list[WorkflowRecord] = Field(min_length=1)

    @field_validator("building_name")
    @classmethod
    def validate_building_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("building_name cannot be blank.")
        return normalized

    @field_validator(
        "city",
        "crm_record_id",
        "template_name",
        "workdrive_folder_id",
        "site_name",
        "omada_region",
        "omada_timezone",
        "omada_scenario",
        "omada_operation",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def apply_default_vlans(self) -> "WorkflowBatchRequest":
        used_vlans: set[int] = set()
        next_vlan = 10
        updated_records: list[WorkflowRecord] = []

        for record in self.records:
            vlan_id = record.vlan_id
            if vlan_id is None:
                while next_vlan in used_vlans:
                    next_vlan += 10
                vlan_id = next_vlan
                next_vlan += 10
            elif vlan_id in used_vlans:
                raise ValueError(f"Duplicate vlan_id '{vlan_id}' is not allowed in one workflow batch.")

            used_vlans.add(vlan_id)
            updated_records.append(record.model_copy(update={"vlan_id": vlan_id}))

        self.records = updated_records
        return self

    def to_pdf_payload(self, workdrive_run_stamp: str | None = None) -> dict[str, Any]:
        includes_omada = self.workflow_mode in {"pdf_and_site", "site_only"}
        payload: dict[str, Any] = {
            "building_name": self.building_name,
            "template_name": self.template_name,
            "passwords_generated": self.passwords_generated,
            "upload_individual_pdfs": True,
            "upload_merged_pdf": True,
            "upload_txt_export": True,
            "upload_zip_export": True,
            "upload_ya_export": includes_omada,
            "workdrive_run_stamp": workdrive_run_stamp,
            "records": [
                {
                    "SSID": record.ssid,
                    "PASSWORD": record.password,
                    "AUTH_TYPE": "WPA",
                    "hidden": record.hidden,
                    "unit_label": record.unit_label,
                }
                for record in self.records
            ],
        }

        if self.city:
            payload["city"] = self.city
        if self.crm_record_id:
            payload["crm_record_id"] = self.crm_record_id
        if self.workdrive_folder_id:
            payload["workdrive_folder_id"] = self.workdrive_folder_id

        return payload


def _parse_bool_flag(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value

    text = clean_scalar(value)
    if text is None:
        return None

    normalized = text.lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise ValueError(f"Boolean flag value '{text}' is not recognized.")


def _parse_bool_with_default(value: Any, default: bool) -> bool:
    parsed = _parse_bool_flag(value)
    return default if parsed is None else parsed


def _get_password_parts(payload: dict[str, Any], index: int) -> list[tuple[str, Any]]:
    if index == 1:
        return [(key, payload[key]) for key in PASSWORDS_KEYS if key in payload]

    parts: list[tuple[str, Any]] = []
    for key in PASSWORDS_KEYS:
        for candidate in (f"{key}_{index}", f"{key}{index}"):
            if candidate in payload:
                parts.append((candidate, payload[candidate]))
    return parts


def _parse_password_lists(payload: dict[str, Any]) -> list[str]:
    passwords: list[str] = []
    seen_keys: set[str] = set()
    for index in range(1, 10):
        for key, part in _get_password_parts(payload, index):
            if key in seen_keys:
                continue
            seen_keys.add(key)
            passwords.extend(parse_string_list(part, f"passwords_{index}"))
    return passwords


def _parse_workflow_mode(value: Any) -> WorkflowMode:
    text = clean_scalar(value)
    if text is None:
        return "pdf_and_site"

    normalized = text.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in {"pdf_only", "pdf_and_site", "site_only"}:
        raise ValueError("workflow_mode must be 'pdf_only', 'pdf_and_site', or 'site_only'.")
    return normalized  # type: ignore[return-value]


def _parse_requested_credential_mode(value: Any) -> CredentialMode | None:
    text = clean_scalar(value)
    if text is None:
        return None

    normalized = text.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in {"generated", "predefined"}:
        raise ValueError("credential_mode must be 'generated' or 'predefined'.")
    return normalized  # type: ignore[return-value]


def _parse_omada_operation(value: Any) -> OmadaOperation:
    text = clean_scalar(value)
    if text is None:
        return "ensure"

    normalized = text.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in {"ensure", "create", "upsert", "update"}:
        raise ValueError("omada_operation must be 'ensure', 'create', 'upsert', or 'update'.")
    return normalized  # type: ignore[return-value]


def _has_numeric_identifiers(values: list[str]) -> bool:
    return bool(values) and all(value.isdigit() for value in values)


def _build_building_slug(building_name: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in building_name)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "site"


def _generate_suffix(length: int) -> str:
    return "".join(secrets.choice(string.ascii_uppercase) for _ in range(length))


def _generate_password(specials: str) -> str:
    first_digits = "".join(secrets.choice(string.digits) for _ in range(4))
    letters = "".join(secrets.choice(SAFE_PASSWORD_LETTERS) for _ in range(2))
    second_digits = "".join(secrets.choice(string.digits) for _ in range(4))
    special_pool = specials or "*!$@#"
    special_chars = "".join(secrets.choice(special_pool) for _ in range(2))
    return f"{first_digits}{letters}{second_digits}{special_chars}"


def _extract_workdrive_folder_id(value: Any) -> str | None:
    text = clean_scalar(value)
    if text is None:
        return None

    if "/" not in text and "?" not in text and "#" not in text:
        return text

    parsed = urlparse(text)
    query = parse_qs(parsed.query)
    for key in WORKDRIVE_QUERY_KEYS:
        values = query.get(key)
        if values:
            candidate = clean_scalar(values[0])
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

    raise ValueError(f"Could not extract a WorkDrive folder id from '{text}'.")


def _get_ssid_template(payload: dict[str, Any], settings: AppSettings) -> str:
    template = clean_scalar(get_first(payload, SSID_TEMPLATE_KEYS))
    return template or settings.naming.ssid_template


def _get_ssid_prefix(payload: dict[str, Any], settings: AppSettings) -> str:
    prefix = clean_scalar(get_first(payload, SSID_PREFIX_KEYS))
    if prefix is None:
        return settings.naming.ssid_prefix
    if prefix.lower() in {"empty", "null", "none"}:
        return ""
    return prefix


def _get_ssid_suffix_length(payload: dict[str, Any], settings: AppSettings) -> int:
    raw_value = get_first(payload, SSID_SUFFIX_LENGTH_KEYS)
    if raw_value is None:
        return settings.naming.ssid_suffix_length
    try:
        length = int(str(raw_value).strip())
    except ValueError as exc:
        raise ValueError("ssid_suffix_length must be an integer.") from exc
    if length < 0:
        raise ValueError("ssid_suffix_length cannot be negative.")
    return length


def _get_password_specials(payload: dict[str, Any], settings: AppSettings) -> str:
    value = clean_scalar(get_first(payload, PASSWORD_SPECIALS_KEYS))
    return value or settings.naming.password_specials


def _generate_ssid(
    *,
    identifier: str,
    index: int,
    building_name: str,
    payload: dict[str, Any],
    settings: AppSettings,
) -> str:
    prefix = _get_ssid_prefix(payload, settings)
    suffix_length = _get_ssid_suffix_length(payload, settings)
    suffix = _generate_suffix(suffix_length) if suffix_length else ""
    template = _get_ssid_template(payload, settings)

    try:
        ssid = template.format(
            prefix=prefix,
            identifier=identifier,
            suffix=suffix,
            index=index,
            building=building_name,
            building_slug=_build_building_slug(building_name),
        )
    except KeyError as exc:
        placeholder = str(exc).strip("'")
        raise ValueError(
            "ssid_template uses an unsupported placeholder. "
            "Allowed placeholders: {prefix}, {identifier}, {suffix}, {index}, {building}, {building_slug}."
        ) from exc

    normalized = clean_scalar(ssid)
    if not normalized:
        raise ValueError("Generated SSID is blank. Check ssid_template and ssid_prefix.")
    if len(normalized) > 128:
        raise ValueError(f"Generated SSID '{normalized}' exceeds the 128 character limit.")
    return normalized


def _resolve_password(
    explicit_password: str | None,
    *,
    payload: dict[str, Any],
    settings: AppSettings,
) -> tuple[str, bool]:
    if explicit_password:
        return explicit_password, False
    return _generate_password(_get_password_specials(payload, settings)), True


def _normalize_record(
    raw_record: dict[str, Any],
    *,
    index: int,
    payload: dict[str, Any],
    settings: AppSettings,
    building_name: str,
    default_hidden: bool,
    requested_credential_mode: CredentialMode | None,
) -> tuple[dict[str, Any], bool, bool]:
    explicit_ssid = clean_scalar(raw_record.get("ssid") or raw_record.get("SSID"))
    explicit_password = clean_scalar(raw_record.get("password") or raw_record.get("PASSWORD"))
    unit_label = clean_scalar(
        raw_record.get("unit_label")
        or raw_record.get("tenant_name")
        or raw_record.get("Unit_Label")
        or raw_record.get("label")
    )
    identifier = clean_scalar(
        raw_record.get("identifier")
        or raw_record.get("ssid_identifier")
        or raw_record.get("unit")
        or raw_record.get("unit_number")
        or raw_record.get("suite")
        or raw_record.get("apartment")
        or unit_label
    )
    hidden = _parse_bool_flag(raw_record.get("hidden"))
    vlan_value = raw_record.get("vlan_id") or raw_record.get("vlanId") or raw_record.get("VLAN")
    ssid_was_generated = False

    if requested_credential_mode == "predefined" and (explicit_ssid is None or explicit_password is None):
        raise ValueError(f"Record {index} must include both SSID and PASSWORD when credential_mode is predefined.")

    if explicit_ssid is None:
        if identifier is None:
            raise ValueError(f"Record {index} is missing an SSID or identifier/unit.")
        explicit_ssid = _generate_ssid(
            identifier=identifier,
            index=index,
            building_name=building_name,
            payload=payload,
            settings=settings,
        )
        ssid_was_generated = True

    password, password_was_generated = _resolve_password(
        explicit_password,
        payload=payload,
        settings=settings,
    )

    normalized: dict[str, Any] = {
        "SSID": explicit_ssid,
        "PASSWORD": password,
        "hidden": default_hidden if hidden is None else hidden,
        "unit_label": unit_label or identifier,
    }

    if vlan_value is not None:
        normalized["vlan_id"] = int(vlan_value)

    return normalized, ssid_was_generated, password_was_generated


def parse_payload(raw_payload: Any, settings: AppSettings) -> WorkflowBatchRequest:
    if not isinstance(raw_payload, dict):
        raise ValueError("Payload must be a JSON object.")

    payload = dict(raw_payload)
    building_name = clean_scalar(get_first(payload, BUILDING_NAME_KEYS))
    if not building_name:
        raise ValueError("Missing building_name or Deal_Name.")

    city = clean_scalar(get_first(payload, CITY_KEYS))
    crm_record_id = clean_scalar(get_first(payload, CRM_RECORD_ID_KEYS))
    template_name = clean_scalar(get_first(payload, TEMPLATE_NAME_KEYS)) or "Opticable_Template_01"
    workdrive_folder_id = _extract_workdrive_folder_id(get_first(payload, WORKDRIVE_KEYS))
    site_name = clean_scalar(get_first(payload, SITE_NAME_KEYS))
    omada_region = clean_scalar(get_first(payload, REGION_KEYS))
    omada_timezone = clean_scalar(get_first(payload, TIMEZONE_KEYS))
    omada_scenario = clean_scalar(get_first(payload, SCENARIO_KEYS))
    omada_operation = _parse_omada_operation(get_first(payload, OMADA_OPERATION_KEYS))
    default_hidden = _parse_bool_flag(get_first(payload, HIDDEN_KEYS)) or False
    workflow_mode = _parse_workflow_mode(get_first(payload, WORKFLOW_MODE_KEYS))
    requested_credential_mode = _parse_requested_credential_mode(get_first(payload, CREDENTIAL_MODE_KEYS))
    includes_pdf = workflow_mode in {"pdf_only", "pdf_and_site"}
    includes_omada = workflow_mode in {"pdf_and_site", "site_only"}
    upload_omada_plan = includes_omada
    upload_individual_pdfs = True if includes_pdf else None
    upload_merged_pdf = True if includes_pdf else None
    upload_txt_export = True if includes_pdf else None
    upload_zip_export = True if includes_pdf else None
    upload_ya_export = True if includes_pdf and includes_omada else None

    passwords_generated = False
    ssids_generated = False
    normalized_records: list[dict[str, Any]] = []

    if "records" in payload:
        raw_records = payload["records"]
        if not isinstance(raw_records, list) or not raw_records:
            raise ValueError("records must be a non-empty array.")
        for index, raw_record in enumerate(raw_records, start=1):
            if not isinstance(raw_record, dict):
                raise ValueError(f"records[{index - 1}] must be an object.")
            normalized_record, ssid_generated, password_generated = _normalize_record(
                raw_record,
                index=index,
                payload=payload,
                settings=settings,
                building_name=building_name,
                default_hidden=default_hidden,
                requested_credential_mode=requested_credential_mode,
            )
            normalized_records.append(normalized_record)
            ssids_generated = ssids_generated or ssid_generated
            passwords_generated = passwords_generated or password_generated
        resolved_credential_mode: CredentialMode = (
            requested_credential_mode
            or ("generated" if passwords_generated or ssids_generated else "predefined")
        )
    else:
        raw_ssids = parse_string_list(get_first(payload, SSIDS_KEYS), "ssids")
        identifiers = parse_string_list(get_first(payload, UNITS_KEYS), "units")
        passwords = _parse_password_lists(payload)
        unit_labels = parse_string_list(get_first(payload, UNIT_LABEL_KEYS), "unit_labels")
        vlan_values = parse_string_list(get_first(payload, VLAN_KEYS), "vlans")

        should_generate_ssids = bool(identifiers)
        if not should_generate_ssids and raw_ssids and _has_numeric_identifiers(raw_ssids):
            identifiers = raw_ssids
            raw_ssids = []
            should_generate_ssids = True

        if requested_credential_mode == "predefined":
            should_generate_ssids = False

        count_source = identifiers if should_generate_ssids else raw_ssids
        if not count_source:
            raise ValueError(
                "No SSIDs or identifiers were provided. Send records, ssids/SSID_List, or units/Unit_s."
            )
        if passwords and len(passwords) > len(count_source):
            raise ValueError(f"Password count ({len(passwords)}) exceeds record count ({len(count_source)}).")
        if unit_labels and len(unit_labels) != len(count_source):
            raise ValueError(f"unit label count ({len(unit_labels)}) does not match record count ({len(count_source)}).")
        if vlan_values and len(vlan_values) != len(count_source):
            raise ValueError(f"VLAN count ({len(vlan_values)}) does not match record count ({len(count_source)}).")
        if requested_credential_mode == "predefined" and len(passwords) != len(count_source):
            raise ValueError(
                "credential_mode 'predefined' requires one explicit password for every record."
            )

        for index, count_value in enumerate(count_source, start=1):
            explicit_password = passwords[index - 1] if index <= len(passwords) else None
            if requested_credential_mode == "predefined" and explicit_password is None:
                raise ValueError(
                    f"Record {index} is missing a password. credential_mode 'predefined' requires explicit passwords."
                )
            password, password_generated = _resolve_password(
                explicit_password,
                payload=payload,
                settings=settings,
            )
            passwords_generated = passwords_generated or password_generated

            identifier = identifiers[index - 1] if should_generate_ssids else None
            unit_label = unit_labels[index - 1] if unit_labels else (identifier if should_generate_ssids else None)
            if should_generate_ssids:
                ssid = _generate_ssid(
                    identifier=identifier or count_value,
                    index=index,
                    building_name=building_name,
                    payload=payload,
                    settings=settings,
                )
                ssids_generated = True
            else:
                ssid = raw_ssids[index - 1]

            record: dict[str, Any] = {
                "SSID": ssid,
                "PASSWORD": password,
                "hidden": default_hidden,
                "unit_label": unit_label,
            }
            if vlan_values:
                record["vlan_id"] = int(vlan_values[index - 1])
            normalized_records.append(record)

        resolved_credential_mode = requested_credential_mode or (
            "generated" if passwords_generated or ssids_generated else "predefined"
        )

    return WorkflowBatchRequest.model_validate(
        {
            "building_name": building_name,
            "city": city,
            "crm_record_id": crm_record_id,
            "credential_mode": resolved_credential_mode,
            "workflow_mode": workflow_mode,
            "passwords_generated": passwords_generated,
            "ssids_generated": ssids_generated,
            "template_name": template_name,
            "workdrive_folder_id": workdrive_folder_id,
            "site_name": site_name,
            "omada_region": omada_region,
            "omada_timezone": omada_timezone,
            "omada_scenario": omada_scenario,
            "omada_operation": omada_operation,
            "upload_omada_plan": upload_omada_plan,
            "upload_individual_pdfs": upload_individual_pdfs,
            "upload_merged_pdf": upload_merged_pdf,
            "upload_txt_export": upload_txt_export,
            "upload_zip_export": upload_zip_export,
            "upload_ya_export": upload_ya_export,
            "records": normalized_records,
        }
    )
