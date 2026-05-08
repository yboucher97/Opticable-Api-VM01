from __future__ import annotations

from typing import Any

import httpx

from .config import CrmSettings, WorkDriveSettings
from .exceptions import ConfigurationError, WorkDriveError
from .zoho_credentials import load_zoho_credentials


class ZohoCrmClient:
    def __init__(self, crm_settings: CrmSettings, auth_settings: WorkDriveSettings, logger) -> None:
        self.crm_settings = crm_settings
        self.auth_settings = auth_settings
        self.logger = logger
        self._access_token: str | None = None

    def update_generated_password_fields(self, record_id: str, passwords: list[str], ssids: list[str] | None = None) -> dict[str, Any]:
        if not record_id:
            raise ConfigurationError("CRM update requested but no crm_record_id was provided.")

        primary_limit = self.crm_settings.primary_password_limit
        primary_values = passwords[:primary_limit]
        overflow_values = passwords[primary_limit:]

        update_fields = {
            self.crm_settings.primary_password_field: ",".join(primary_values),
        }
        if self.crm_settings.generated_ssids_field and ssids:
            update_fields[self.crm_settings.generated_ssids_field] = ",".join(ssids)
        if self.crm_settings.overflow_password_field and overflow_values:
            update_fields[self.crm_settings.overflow_password_field] = ",".join(overflow_values)

        payload = {
            "data": [update_fields]
        }

        timeout = httpx.Timeout(60.0, connect=20.0)
        with httpx.Client(timeout=timeout) as client:
            access_token = self._get_access_token(client)
            headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
            response = client.put(
                f"{self.crm_settings.api_base_url}/{self.crm_settings.module_api_name}/{record_id}",
                headers=headers,
                json=payload,
            )

        if response.status_code >= 400:
            raise WorkDriveError(
                f"Zoho CRM update failed for record '{record_id}' with status {response.status_code}: {response.text}"
            )

        data = response.json()
        self.logger.info(
            "Updated CRM record %s with %s generated passwords (%s primary, %s overflow)",
            record_id,
            len(passwords),
            len(primary_values),
            len(overflow_values),
        )
        return {
            "record_id": record_id,
            "status_code": response.status_code,
            "primary_count": len(primary_values),
            "overflow_count": len(overflow_values),
            "ssid_count": len(ssids or []),
            "response": data,
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
                self.auth_settings.accounts_base_url,
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
