from __future__ import annotations

import json
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .config import ZohoOAuthSettings


class WorkflowWorkDriveError(RuntimeError):
    pass


class WorkflowWorkDriveClient:
    def __init__(
        self,
        oauth_settings: ZohoOAuthSettings,
        logger,
        target_folder_name: str = "Document/Controller",
        run_folder_name: str | None = None,
    ) -> None:
        self.oauth_settings = oauth_settings
        self.logger = logger
        self.target_folder_name = target_folder_name.strip()
        self.run_folder_name = (run_folder_name or "").strip() or datetime.now().strftime("%Y-%m-%d-%H-%M")
        self._access_token: str | None = None

    def upload_file(self, path: Path, parent_folder_id: str) -> dict[str, Any]:
        with path.open("rb") as handle:
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return self.upload_bytes(handle.read(), path.name, parent_folder_id, content_type=content_type)

    def upload_bytes(
        self,
        content: bytes,
        file_name: str,
        parent_folder_id: str,
        *,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(60.0, connect=20.0)
        with httpx.Client(timeout=timeout) as client:
            headers = self._get_auth_headers(client)
            folder_id = self._resolve_upload_folder_id(client, headers, parent_folder_id)
            params = {
                "parent_id": folder_id,
                "filename": file_name,
                "override-name-exist": "true",
            }
            response = client.post(
                f"{self._api_base_url()}/upload",
                headers=headers,
                params=params,
                files={"content": (file_name, content, content_type)},
            )

        if response.status_code >= 400:
            raise WorkflowWorkDriveError(
                f"WorkDrive upload failed for '{file_name}' with status {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = {"raw_response": response.text}

        self.logger.info("Uploaded workflow artifact '%s' to WorkDrive folder %s", file_name, folder_id)
        return {
            "filename": file_name,
            "folder_id": folder_id,
            "status_code": response.status_code,
            "response": payload,
        }

    def list_read_folder_entries(self, parent_folder_id: str) -> dict[str, Any]:
        timeout = httpx.Timeout(60.0, connect=20.0)
        with httpx.Client(timeout=timeout) as client:
            headers = self._get_auth_headers(client)
            folder_id = self._resolve_read_folder_id(client, headers, parent_folder_id)
            response = client.get(
                f"{self._api_base_url()}/files/{folder_id}/files",
                headers=headers,
                params={"page[limit]": 200},
            )

        if response.status_code >= 400:
            raise WorkflowWorkDriveError(
                f"WorkDrive folder listing failed for '{folder_id}' with status {response.status_code}: {response.text}"
            )

        payload = response.json()
        items = payload.get("data")
        if not isinstance(items, list):
            raise WorkflowWorkDriveError(f"Unexpected WorkDrive listing response for folder '{folder_id}': {payload}")

        return {
            "folder_id": folder_id,
            "items": items,
        }

    def download_text_file(self, file_id: str) -> str:
        timeout = httpx.Timeout(60.0, connect=20.0)
        with httpx.Client(timeout=timeout) as client:
            headers = self._get_auth_headers(client)
            response = client.get(
                f"{self._api_base_url()}/download",
                headers=headers,
                params={"resource_id": file_id},
            )

        if response.status_code >= 400:
            raise WorkflowWorkDriveError(
                f"WorkDrive download failed for file '{file_id}' with status {response.status_code}: {response.text}"
            )

        return response.text

    def _resolve_upload_folder_id(self, client: httpx.Client, headers: dict[str, str], parent_folder_id: str) -> str:
        if not self.target_folder_name:
            return parent_folder_id

        return self._prepare_rotated_upload_folder_id(client, headers, parent_folder_id)

    def _resolve_read_folder_id(self, client: httpx.Client, headers: dict[str, str], parent_folder_id: str) -> str:
        if not self.target_folder_name:
            return parent_folder_id

        folder_id = parent_folder_id
        folder_parts = self._target_folder_parts()
        for folder_name in folder_parts[:-1]:
            child_id = self._find_child_folder_id(client, headers, folder_id, folder_name)
            if not child_id:
                return parent_folder_id
            folder_id = child_id

        if not folder_parts:
            return folder_id
        base_folder_name = folder_parts[-1]
        folders = [
            folder
            for folder in self._list_child_folders(client, headers, folder_id)
            if self._is_rotated_target_folder(folder["name"], base_folder_name)
        ]
        if not folders:
            return parent_folder_id
        folders.sort(key=lambda folder: folder["name"])
        return folders[-1]["id"]

    def _target_folder_parts(self) -> list[str]:
        return [part.strip() for part in self.target_folder_name.split("/") if part.strip()]

    def _prepare_rotated_upload_folder_id(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
    ) -> str:
        parts = self._target_folder_parts()
        if not parts:
            return parent_folder_id

        container_folder_id = parent_folder_id
        for folder_name in parts[:-1]:
            container_folder_id = self._find_or_create_child_folder_id(client, headers, container_folder_id, folder_name)

        base_folder_name = parts[-1]
        archive_folder_id = self._find_or_create_child_folder_id(client, headers, container_folder_id, "Archive")
        stale_folder_ids = [
            folder["id"]
            for folder in self._list_child_folders(client, headers, container_folder_id)
            if folder["id"] != archive_folder_id
            and self._is_rotated_target_folder(folder["name"], base_folder_name)
        ]
        if stale_folder_ids:
            self._move_items_to_folder(client, headers, stale_folder_ids, archive_folder_id)

        current_folder_name = f"{base_folder_name} {self.run_folder_name}"
        return self._find_or_create_child_folder_id(client, headers, container_folder_id, current_folder_name)

    def _find_or_create_child_folder_id(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
        target_folder_name: str,
    ) -> str:
        child_id = self._find_child_folder_id(client, headers, parent_folder_id, target_folder_name)
        if child_id:
            return child_id
        self.logger.info(
            "Workflow WorkDrive child folder '%s' was missing inside parent %s. Creating it now.",
            target_folder_name,
            parent_folder_id,
        )
        return self._create_child_folder_id(client, headers, parent_folder_id, target_folder_name)

    def _is_rotated_target_folder(self, folder_name: str, base_folder_name: str) -> bool:
        normalized = folder_name.strip().casefold()
        base = base_folder_name.strip().casefold()
        return normalized == base or normalized.startswith(f"{base} ")

    def _list_child_folders(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
    ) -> list[dict[str, str]]:
        response = client.get(
            f"{self._api_base_url()}/files/{parent_folder_id}/files",
            headers=headers,
            params={"filter[type]": "folder", "page[limit]": 200},
        )
        if response.status_code >= 400:
            raise WorkflowWorkDriveError(
                f"WorkDrive folder lookup failed for parent '{parent_folder_id}' with status {response.status_code}: {response.text}"
            )

        folders: list[dict[str, str]] = []
        payload = response.json()
        for item in payload.get("data", []):
            attributes = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(attributes, dict):
                continue
            folder_id = item.get("id")
            name = str(attributes.get("name", "")).strip()
            if folder_id and name:
                folders.append({"id": str(folder_id), "name": name})
        return folders

    def _move_items_to_folder(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        item_ids: list[str],
        destination_folder_id: str,
    ) -> None:
        response = client.patch(
            f"{self._api_base_url()}/files",
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
            raise WorkflowWorkDriveError(
                f"WorkDrive archive move failed for {len(item_ids)} item(s) into '{destination_folder_id}' "
                f"with status {response.status_code}: {response.text}"
            )

        self.logger.info("Moved %d WorkDrive folder(s) into Archive folder %s", len(item_ids), destination_folder_id)

    def _find_child_folder_id(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
        target_folder_name: str,
    ) -> str | None:
        response = client.get(
            f"{self._api_base_url()}/files/{parent_folder_id}/files",
            headers=headers,
            params={"filter[type]": "folder", "page[limit]": 200},
        )
        if response.status_code >= 400:
            raise WorkflowWorkDriveError(
                f"WorkDrive folder lookup failed for parent '{parent_folder_id}' with status {response.status_code}: {response.text}"
            )

        payload = response.json()
        for item in payload.get("data", []):
            attributes = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(attributes, dict):
                continue
            if str(attributes.get("name", "")).strip().casefold() == target_folder_name.casefold():
                folder_id = item.get("id")
                if folder_id:
                    return str(folder_id)
        return None

    def _create_child_folder_id(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
        target_folder_name: str,
    ) -> str:
        response = client.post(
            f"{self._api_base_url()}/files",
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
            raise WorkflowWorkDriveError(
                f"WorkDrive child folder creation failed for parent '{parent_folder_id}' with status {response.status_code}: {response.text}"
            )

        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, dict) or not data.get("id"):
            raise WorkflowWorkDriveError(
                f"WorkDrive child folder creation returned an unexpected payload: {payload}"
            )
        return str(data["id"])

    def _get_auth_headers(self, client: httpx.Client) -> dict[str, str]:
        access_token = self._get_access_token(client)
        return {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Accept": "application/vnd.api+json",
        }

    def _get_access_token(self, client: httpx.Client) -> str:
        if self._access_token:
            return self._access_token

        credentials = self._load_credentials()
        refresh_token = credentials.get("refresh_token")
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        if refresh_token and client_id and client_secret:
            response = client.post(
                f"{self.oauth_settings.accounts_base_url}/oauth/v2/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
            if response.status_code >= 400:
                raise WorkflowWorkDriveError(
                    f"Zoho OAuth refresh failed with status {response.status_code}: {response.text}"
                )
            payload = response.json()
            access_token = payload.get("access_token")
            if not access_token:
                raise WorkflowWorkDriveError(f"Zoho OAuth refresh did not return an access token: {payload}")
            self._access_token = str(access_token)
            return self._access_token

        direct_token = credentials.get("access_token")
        if direct_token:
            self._access_token = str(direct_token)
            return self._access_token

        raise WorkflowWorkDriveError(
            "Missing Zoho OAuth credentials. Complete the server-side Zoho OAuth flow and "
            "ensure ZOHO_OAUTH_CREDENTIALS_PATH points at the generated credential file."
        )

    def _load_credentials(self) -> dict[str, Any]:
        path = self.oauth_settings.credentials_path
        if not path.exists():
            raise WorkflowWorkDriveError(
                "Zoho OAuth credentials file is missing. Complete the server-side Zoho OAuth flow first."
            )

        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise WorkflowWorkDriveError(f"Unexpected Zoho credential file format at {path}")
        return payload

    def _api_base_url(self) -> str:
        credentials = self._load_credentials()
        api_domain = str(credentials.get("api_domain", "")).strip().rstrip("/")
        if api_domain:
            return f"{api_domain}/workdrive/api/v1"
        accounts_base = self.oauth_settings.accounts_base_url.rstrip("/")
        accounts_to_api = {
            "https://accounts.zoho.com": "https://www.zohoapis.com",
            "https://accounts.zoho.eu": "https://www.zohoapis.eu",
            "https://accounts.zoho.in": "https://www.zohoapis.in",
            "https://accounts.zoho.com.au": "https://www.zohoapis.com.au",
        }
        api_domain = accounts_to_api.get(accounts_base, "https://www.zohoapis.com")
        return f"{api_domain}/workdrive/api/v1"
