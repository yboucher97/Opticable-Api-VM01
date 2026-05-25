from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from .config import AppSettings
from .models import OmadaOperation, WorkflowBatchRequest, WorkflowRecord
from .omada_plan import build_omada_plan
from .workdrive import WorkflowWorkDriveClient, WorkflowWorkDriveError

SourcePreference = Literal["yaml_then_txt", "yaml_only", "txt_only"]
ResolvedSourceType = Literal["yaml", "txt"]


@dataclass(slots=True, frozen=True)
class ResolvedWorkDriveArtifact:
    source_type: ResolvedSourceType
    file_id: str
    file_name: str
    folder_id: str
    content: str


@dataclass(slots=True, frozen=True)
class ResolvedOmadaExecutionSource:
    source_type: ResolvedSourceType
    file_id: str
    file_name: str
    folder_id: str
    plan_file_name: str
    plan_text: str
    plan_dict: dict[str, Any]
    building_name: str
    site_name: str


def resolve_workdrive_execution_source(
    client: WorkflowWorkDriveClient,
    *,
    parent_folder_id: str,
    operation: OmadaOperation,
    source_preference: SourcePreference,
    settings: AppSettings,
    building_name: str | None = None,
    site_name: str | None = None,
    city: str | None = None,
    template_name: str = "Opticable_Template_01",
    omada_region: str | None = None,
    omada_timezone: str | None = None,
    omada_scenario: str | None = None,
) -> ResolvedOmadaExecutionSource:
    if operation == "get":
        raise ValueError("Operation 'get' uses the live snapshot endpoint, not WorkDrive execution.")

    artifact = _resolve_artifact(
        client,
        parent_folder_id=parent_folder_id,
        operation=operation,
        source_preference=source_preference,
    )

    if artifact.source_type == "yaml":
        try:
            plan_dict = yaml.safe_load(artifact.content)
        except yaml.YAMLError as exc:
            raise ValueError(f"WorkDrive YAML '{artifact.file_name}' could not be parsed: {exc}") from exc
        if not isinstance(plan_dict, dict):
            raise ValueError(f"WorkDrive YAML '{artifact.file_name}' must contain a YAML object at the root.")
        _set_plan_mutation_mode(plan_dict, operation)

        resolved_site_name = (
            site_name
            or _extract_yaml_site_name(plan_dict)
            or building_name
            or Path(artifact.file_name).stem
        )
        resolved_building_name = building_name or resolved_site_name

        return ResolvedOmadaExecutionSource(
            source_type="yaml",
            file_id=artifact.file_id,
            file_name=artifact.file_name,
            folder_id=artifact.folder_id,
            plan_file_name=artifact.file_name,
            plan_text=artifact.content,
            plan_dict=plan_dict,
            building_name=resolved_building_name,
            site_name=resolved_site_name,
        )

    resolved_site_name = site_name or building_name or _derive_site_name_from_artifact_name(artifact.file_name)
    resolved_building_name = building_name or resolved_site_name
    records = _parse_txt_records(artifact.content, artifact.file_name)
    batch = WorkflowBatchRequest(
        building_name=resolved_building_name,
        city=city,
        credential_mode="predefined",
        workflow_mode="site_only",
        template_name=template_name,
        site_name=resolved_site_name,
        omada_region=omada_region or settings.omada.region,
        omada_timezone=omada_timezone or settings.omada.timezone,
        omada_scenario=omada_scenario or settings.omada.scenario,
        records=records,
    )
    plan_dict = build_omada_plan(batch, settings)
    _set_plan_mutation_mode(plan_dict, operation)
    plan_text = yaml.safe_dump(plan_dict, sort_keys=False, allow_unicode=False)

    return ResolvedOmadaExecutionSource(
        source_type="txt",
        file_id=artifact.file_id,
        file_name=artifact.file_name,
        folder_id=artifact.folder_id,
        plan_file_name=f"{operation}.yaml",
        plan_text=plan_text,
        plan_dict=plan_dict,
        building_name=resolved_building_name,
        site_name=resolved_site_name,
    )


def build_live_snapshot(
    *,
    site: dict[str, Any],
    lans: list[dict[str, Any]],
    wlan_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "version": 1,
        "operation": "get",
        "source": "live_omada",
        "passwordsAvailable": False,
        "site": site,
        "lans": lans,
        "wlanGroups": wlan_groups,
    }


def _resolve_artifact(
    client: WorkflowWorkDriveClient,
    *,
    parent_folder_id: str,
    operation: OmadaOperation,
    source_preference: SourcePreference,
) -> ResolvedWorkDriveArtifact:
    listing = client.list_read_folder_entries(parent_folder_id)
    folder_id = str(listing["folder_id"])
    items = listing["items"]

    yaml_candidate = _find_first_artifact(items, _yaml_candidate_names(operation), {".yaml", ".yml"})
    txt_candidate = _find_first_artifact(items, (), {".txt"})

    if source_preference == "yaml_only":
        if yaml_candidate is None:
            raise WorkflowWorkDriveError("No YAML plan file was found in the WorkDrive folder.")
        return _download_candidate(client, folder_id, yaml_candidate, "yaml")

    if source_preference == "txt_only":
        if txt_candidate is None:
            raise WorkflowWorkDriveError("No TXT credential export was found in the WorkDrive folder.")
        return _download_candidate(client, folder_id, txt_candidate, "txt")

    if yaml_candidate is not None:
        return _download_candidate(client, folder_id, yaml_candidate, "yaml")
    if txt_candidate is not None:
        return _download_candidate(client, folder_id, txt_candidate, "txt")
    raise WorkflowWorkDriveError("No YAML plan or TXT credential export was found in the WorkDrive folder.")


def _download_candidate(
    client: WorkflowWorkDriveClient,
    folder_id: str,
    candidate: dict[str, str],
    source_type: ResolvedSourceType,
) -> ResolvedWorkDriveArtifact:
    content = client.download_text_file(candidate["id"])
    return ResolvedWorkDriveArtifact(
        source_type=source_type,
        file_id=candidate["id"],
        file_name=candidate["name"],
        folder_id=folder_id,
        content=content,
    )


def _yaml_candidate_names(operation: OmadaOperation) -> tuple[str, ...]:
    preferred = {
        "create": ("create.yaml", "create.yml", "omada-plan.yaml", "omada-plan.yml"),
        "upsert": ("upsert.yaml", "upsert.yml", "create.yaml", "create.yml", "omada-plan.yaml", "omada-plan.yml"),
        "update": ("update.yaml", "update.yml", "omada-plan.yaml", "omada-plan.yml"),
        "get": ("get.yaml", "get.yml", "snapshot.yaml", "snapshot.yml"),
    }
    return preferred[operation]


def _find_first_artifact(
    items: list[dict[str, Any]],
    preferred_names: tuple[str, ...],
    allowed_extensions: set[str],
) -> dict[str, str] | None:
    normalized_candidates: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        file_id = str(item.get("id", "")).strip()
        attributes = item.get("attributes")
        if not file_id or not isinstance(attributes, dict):
            continue
        if str(attributes.get("type", "")).strip().lower() == "folder":
            continue
        name = str(attributes.get("name", "")).strip()
        if not name:
            continue
        suffix = Path(name).suffix.lower()
        if suffix not in allowed_extensions:
            continue
        normalized_candidates.append({"id": file_id, "name": name})

    for preferred_name in preferred_names:
        for candidate in normalized_candidates:
            if candidate["name"].casefold() == preferred_name.casefold():
                return candidate

    return normalized_candidates[0] if normalized_candidates else None


def _parse_txt_records(content: str, file_name: str) -> list[WorkflowRecord]:
    records: list[WorkflowRecord] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.casefold()
        if "logement" in lower and "mot de passe" in lower:
            continue
        if "network" in lower and "password" in lower:
            continue
        if "ssid" in lower and "password" in lower:
            continue
        if set(line) <= {"-", " ", "\t"}:
            continue

        ssid, password = _split_txt_line(line, file_name)
        records.append(
            WorkflowRecord(
                SSID=ssid,
                PASSWORD=password,
            )
        )

    if not records:
        raise ValueError(f"TXT export '{file_name}' did not contain any SSID/password rows.")
    return records


def _split_txt_line(line: str, file_name: str) -> tuple[str, str]:
    if "\t" in line:
        left, right = line.split("\t", 1)
        ssid = left.strip()
        password = right.strip()
        if ssid and password:
            return ssid, password

    parts = [part.strip() for part in line.split() if part.strip()]
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])

    raise ValueError(f"TXT export '{file_name}' contains an unreadable row: {line!r}")


def _extract_yaml_site_name(plan_dict: dict[str, Any]) -> str | None:
    sites = plan_dict.get("sites")
    if not isinstance(sites, list) or not sites:
        return None
    first_site = sites[0]
    if not isinstance(first_site, dict):
        return None
    name = first_site.get("name")
    return str(name).strip() if name else None


def _derive_site_name_from_artifact_name(file_name: str) -> str:
    stem = Path(file_name).stem.strip()
    normalized = stem.removeprefix("Mot de passe ").removeprefix("MDP_Site_").removeprefix("MDP_Site ").strip()
    return normalized or "Omada Site"


def _set_plan_mutation_mode(plan_dict: dict[str, Any], operation: OmadaOperation) -> None:
    execution = plan_dict.get("execution")
    if not isinstance(execution, dict):
        execution = {}
        plan_dict["execution"] = execution
    execution["mutationMode"] = operation
