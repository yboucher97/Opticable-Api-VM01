from __future__ import annotations

import json
import mimetypes
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .config import WorkDriveSettings
from .exceptions import ConfigurationError, WorkDriveError
from .zoho_credentials import load_zoho_credentials


class ZohoWorkDriveClient:
    def __init__(self, settings: WorkDriveSettings, logger) -> None:
        self.settings = settings
        self.logger = logger
        self._access_token: str | None = None

    def resolve_folder_id(self, request_folder_id: str | None) -> str:
        folder_id = (
            request_folder_id
            or os.getenv("ZOHO_WORKDRIVE_PARENT_FOLDER_ID")
            or self.settings.parent_folder_id
        )
        if not folder_id:
            raise ConfigurationError(
                "WorkDrive upload is enabled but no folder id was provided. "
                "Send workdrive_folder_id in JSON or set ZOHO_WORKDRIVE_PARENT_FOLDER_ID."
            )
        return folder_id

    def resolve_upload_folder_id(self, request_folder_id: str | None, run_folder_name: str | None = None) -> str:
        parent_folder_id = self.resolve_folder_id(request_folder_id)
        target_folder_name = self.settings.target_folder_name.strip()
        if not target_folder_name:
            return parent_folder_id
        run_stamp = self._workdrive_run_stamp(run_folder_name)

        timeout = httpx.Timeout(60.0, connect=20.0)
        with httpx.Client(timeout=timeout) as client:
            headers = self._get_auth_headers(client)
            child_folder_id = self._prepare_rotated_upload_folder_id(
                client,
                headers,
                parent_folder_id,
                target_folder_name,
                run_stamp,
            )

        self.logger.info(
            "Resolved WorkDrive upload folder path '%s %s' inside parent %s -> %s",
            self._target_folder_parts(target_folder_name)[-1],
            run_stamp,
            parent_folder_id,
            child_folder_id,
        )
        return child_folder_id

    def _workdrive_run_stamp(self, value: str | None = None) -> str:
        return (value or "").strip() or datetime.now().strftime("%Y-%m-%d-%H-%M")

    def _get_auth_headers(self, client: httpx.Client) -> dict[str, str]:
        access_token = self._get_access_token(client)
        return {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Accept": "application/vnd.api+json",
        }

    def _get_access_token(self, client: httpx.Client) -> str:
        if self._access_token:
            return self._access_token

        credentials = load_zoho_credentials()
        refresh_token = credentials.get("refresh_token")
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        if refresh_token and client_id and client_secret:
            response = client.post(
                self.settings.accounts_base_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
            if response.status_code >= 400:
                raise WorkDriveError(
                    f"Zoho OAuth refresh failed with status {response.status_code}: {response.text}"
                )

            payload = response.json()
            access_token = payload.get("access_token")
            if not access_token:
                raise WorkDriveError(f"Zoho OAuth refresh did not return an access token: {payload}")
            self._access_token = access_token
            return access_token

        direct_token = credentials.get("access_token")
        if direct_token:
            self._access_token = str(direct_token)
            return str(direct_token)

        raise ConfigurationError(
            "Missing Zoho OAuth credentials. Complete the server-side Zoho OAuth flow and "
            "ensure ZOHO_OAUTH_CREDENTIALS_PATH points at the generated credential file."
        )

    def upload_file(self, path: Path, folder_id: str) -> dict[str, Any]:
        timeout = httpx.Timeout(60.0, connect=20.0)
        with httpx.Client(timeout=timeout) as client:
            headers = self._get_auth_headers(client)
            params = {
                "parent_id": folder_id,
                "filename": path.name,
                "override-name-exist": "true" if self.settings.overwrite_existing_files else "false",
            }

            with path.open("rb") as file_handle:
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                response = client.post(
                    f"{self.settings.api_base_url}/upload",
                    headers=headers,
                    params=params,
                    files={self.settings.upload_field_name: (path.name, file_handle, content_type)},
                )

        if response.status_code >= 400:
            raise WorkDriveError(
                f"WorkDrive upload failed for '{path.name}' with status {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = {"raw_response": response.text}

        data = payload.get("data")
        file_id = None
        permalink = None
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                file_id = first.get("id")
                attributes = first.get("attributes")
                if isinstance(attributes, dict):
                    permalink = attributes.get("permalink")
        elif isinstance(data, dict):
            file_id = data.get("id")
            attributes = data.get("attributes")
            if isinstance(attributes, dict):
                permalink = attributes.get("permalink")

        self.logger.info("Uploaded '%s' to WorkDrive folder %s", path.name, folder_id)
        return {
            "filename": path.name,
            "folder_id": folder_id,
            "file_id": file_id,
            "permalink": permalink,
            "status_code": response.status_code,
        }

    def _find_or_create_child_folder_id(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
        target_folder_name: str,
    ) -> str:
        child_folder_id = self._find_child_folder_id(
            client=client,
            headers=headers,
            parent_folder_id=parent_folder_id,
            target_folder_name=target_folder_name,
        )
        if child_folder_id:
            return child_folder_id

        self.logger.info(
            "WorkDrive child folder '%s' was missing inside parent %s. Creating it now.",
            target_folder_name,
            parent_folder_id,
        )
        return self._create_child_folder_id(
            client=client,
            headers=headers,
            parent_folder_id=parent_folder_id,
            target_folder_name=target_folder_name,
        )

    def _find_child_folder_id(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
        target_folder_name: str,
    ) -> str | None:
        offset = 0
        limit = 50
        target_name = target_folder_name.strip().casefold()

        while True:
            response = client.get(
                f"{self.settings.api_base_url}/files/{parent_folder_id}/files",
                headers=headers,
                params={"page[limit]": limit, "page[offset]": offset},
            )
            if response.status_code >= 400:
                raise WorkDriveError(
                    f"WorkDrive folder lookup failed for parent '{parent_folder_id}' with status "
                    f"{response.status_code}: {response.text}"
                )

            payload = response.json()
            data = payload.get("data")
            if not isinstance(data, list):
                raise WorkDriveError(
                    f"Unexpected WorkDrive folder lookup response for parent '{parent_folder_id}': {payload}"
                )

            for entry in data:
                if not isinstance(entry, dict):
                    continue
                attributes = entry.get("attributes")
                if not isinstance(attributes, dict):
                    continue
                if str(attributes.get("type", "")).lower() != "folder":
                    continue
                name = str(attributes.get("name", "")).strip()
                if name.casefold() == target_name:
                    folder_id = entry.get("id")
                    if not folder_id:
                        raise WorkDriveError(
                            f"WorkDrive folder '{target_folder_name}' was found inside '{parent_folder_id}' but had no id."
                        )
                    return str(folder_id)

            if len(data) < limit:
                break
            offset += limit

        return None

    def _list_child_folders(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
    ) -> list[dict[str, str]]:
        offset = 0
        limit = 50
        folders: list[dict[str, str]] = []

        while True:
            response = client.get(
                f"{self.settings.api_base_url}/files/{parent_folder_id}/files",
                headers=headers,
                params={"page[limit]": limit, "page[offset]": offset},
            )
            if response.status_code >= 400:
                raise WorkDriveError(
                    f"WorkDrive folder lookup failed for parent '{parent_folder_id}' with status "
                    f"{response.status_code}: {response.text}"
                )

            payload = response.json()
            data = payload.get("data")
            if not isinstance(data, list):
                raise WorkDriveError(
                    f"Unexpected WorkDrive folder lookup response for parent '{parent_folder_id}': {payload}"
                )

            for entry in data:
                if not isinstance(entry, dict):
                    continue
                attributes = entry.get("attributes")
                if not isinstance(attributes, dict):
                    continue
                if str(attributes.get("type", "")).lower() != "folder":
                    continue
                folder_id = entry.get("id")
                name = str(attributes.get("name", "")).strip()
                if folder_id and name:
                    folders.append({"id": str(folder_id), "name": name})

            if len(data) < limit:
                break
            offset += limit

        return folders

    def _find_or_create_folder_path_id(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
        target_folder_path: str,
    ) -> str:
        folder_id = parent_folder_id
        for target_folder_name in self._target_folder_parts(target_folder_path):
            folder_id = self._find_or_create_child_folder_id(
                client=client,
                headers=headers,
                parent_folder_id=folder_id,
                target_folder_name=target_folder_name,
            )
        return folder_id

    def _prepare_rotated_upload_folder_id(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
        target_folder_path: str,
        run_stamp: str,
    ) -> str:
        target_parts = self._target_folder_parts(target_folder_path)
        if not target_parts:
            return parent_folder_id

        container_folder_id = parent_folder_id
        if len(target_parts) > 1:
            container_folder_id = self._find_or_create_folder_path_id(
                client,
                headers,
                parent_folder_id,
                "/".join(target_parts[:-1]),
            )

        base_folder_name = target_parts[-1]
        archive_folder_id = self._find_or_create_child_folder_id(
            client=client,
            headers=headers,
            parent_folder_id=container_folder_id,
            target_folder_name="Archive",
        )
        current_folder_name = f"{base_folder_name} {run_stamp}"
        stale_folder_ids = [
            folder["id"]
            for folder in self._list_child_folders(client, headers, container_folder_id)
            if folder["id"] != archive_folder_id
            and self._is_rotated_target_folder(folder["name"], base_folder_name)
        ]
        if stale_folder_ids:
            self._move_items_to_folder(client, headers, stale_folder_ids, archive_folder_id)

        return self._find_or_create_child_folder_id(
            client=client,
            headers=headers,
            parent_folder_id=container_folder_id,
            target_folder_name=current_folder_name,
        )

    def _target_folder_parts(self, target_folder_path: str) -> list[str]:
        return [part.strip() for part in target_folder_path.split("/") if part.strip()]

    def _is_rotated_target_folder(self, folder_name: str, base_folder_name: str) -> bool:
        normalized = folder_name.strip().casefold()
        base = base_folder_name.strip().casefold()
        return normalized == base or normalized.startswith(f"{base} ")

    def _move_items_to_folder(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        item_ids: list[str],
        destination_folder_id: str,
    ) -> None:
        response = client.patch(
            f"{self.settings.api_base_url}/files",
            headers={**headers, "Content-Type": "application/vnd.api+json"},
            json={
                "data": [
                    {
                        "type": "files",
                        "id": item_id,
                        "attributes": {"parent_id": destination_folder_id},
                    }
                    for item_id in item_ids
                ]
            },
        )
        if response.status_code >= 400:
            raise WorkDriveError(
                f"WorkDrive archive move failed for {len(item_ids)} item(s) into '{destination_folder_id}' "
                f"with status {response.status_code}: {response.text}"
            )

        self.logger.info("Moved %d WorkDrive folder(s) into Archive folder %s", len(item_ids), destination_folder_id)

    def _create_child_folder_id(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
        target_folder_name: str,
    ) -> str:
        response = client.post(
            f"{self.settings.api_base_url}/files",
            headers={**headers, "Content-Type": "application/vnd.api+json"},
            json={
                "data": {
                    "type": "files",
                    "attributes": {
                        "name": target_folder_name,
                        "parent_id": parent_folder_id,
                    },
                }
            },
        )
        if response.status_code >= 400:
            raise WorkDriveError(
                f"WorkDrive folder creation failed for '{target_folder_name}' inside '{parent_folder_id}' "
                f"with status {response.status_code}: {response.text}"
            )

        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, dict):
            raise WorkDriveError(
                f"Unexpected WorkDrive folder creation response for '{target_folder_name}': {payload}"
            )

        folder_id = data.get("id")
        if not folder_id:
            raise WorkDriveError(
                f"WorkDrive created folder '{target_folder_name}' inside '{parent_folder_id}' but returned no id."
            )

        self.logger.info(
            "Created WorkDrive child folder '%s' inside parent %s -> %s",
            target_folder_name,
            parent_folder_id,
            folder_id,
        )
        return str(folder_id)
