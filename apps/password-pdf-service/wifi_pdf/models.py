from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .exceptions import PayloadValidationError
from .payload_parser import normalize_payload, normalize_template_name


AuthType = Literal["WPA", "WEP", "nopass"]
TemplateName = Literal["Opticable Template Basic 01", "Corteck Template Basic 01"]


class WifiRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ssid: str = Field(min_length=1, max_length=128, alias="SSID")
    password: str | None = Field(default=None, alias="PASSWORD")
    auth_type: str = Field(default="WPA", alias="AUTH_TYPE")
    hidden: bool = False
    tenant_name: str | None = None
    unit_label: str | None = None
    notes_fr: str | None = None
    notes_en: str | None = None

    @field_validator("ssid")
    @classmethod
    def validate_ssid(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("SSID cannot be blank.")
        return normalized

    @field_validator("auth_type")
    @classmethod
    def normalize_auth_type(cls, value: str) -> AuthType:
        normalized = value.strip().upper()
        if normalized in {"WPA2", "WPA/WPA2", "WPA-PSK"}:
            return "WPA"
        if normalized in {"WPA", "WEP"}:
            return normalized
        if normalized in {"", "OPEN", "NOPASS", "NONE"}:
            return "nopass"
        raise ValueError("auth_type must be WPA, WEP, or nopass.")

    @field_validator("password")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_password_requirement(self) -> "WifiRecord":
        if self.auth_type != "nopass" and not self.password:
            raise ValueError("password is required when auth_type is not 'nopass'.")
        if self.auth_type == "nopass":
            self.password = None
        return self


class WifiBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    building_name: str = Field(min_length=1, max_length=200)
    city: str | None = None
    crm_record_id: str | None = None
    passwords_generated: bool = False
    workdrive_folder_id: str | None = None
    workdrive_run_stamp: str | None = None
    template_name: TemplateName = "Opticable Template Basic 01"
    upload_individual_pdfs: bool | None = None
    upload_merged_pdf: bool | None = None
    upload_txt_export: bool | None = None
    upload_zip_export: bool | None = None
    upload_ya_export: bool | None = None
    records: list[WifiRecord] = Field(min_length=1)

    @field_validator("building_name")
    @classmethod
    def validate_building_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("building_name cannot be blank.")
        return normalized

    @field_validator("city")
    @classmethod
    def validate_city(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("crm_record_id")
    @classmethod
    def validate_record_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("workdrive_run_stamp")
    @classmethod
    def validate_workdrive_run_stamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("template_name", mode="before")
    @classmethod
    def validate_template_name(cls, value: str | None) -> str:
        return normalize_template_name(value)


def parse_payload(raw_payload: Any) -> WifiBatchRequest:
    try:
        return WifiBatchRequest.model_validate(normalize_payload(raw_payload))
    except PayloadValidationError:
        raise
    except Exception as exc:  # pragma: no cover - pydantic error formatting is runtime-driven
        raise PayloadValidationError(str(exc)) from exc
