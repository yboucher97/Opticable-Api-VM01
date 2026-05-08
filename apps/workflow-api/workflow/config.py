from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw.strip())


@dataclass(frozen=True)
class ApiSettings:
    api_key_env: str
    bind_host: str
    bind_port: int


@dataclass(frozen=True)
class OutputSettings:
    root_dir: Path
    jobs_dir: Path


@dataclass(frozen=True)
class DownstreamPdfSettings:
    base_url: str
    api_key: str | None
    poll_interval_seconds: int
    timeout_seconds: int


@dataclass(frozen=True)
class DownstreamOmadaSettings:
    base_url: str
    webhook_token: str
    poll_interval_seconds: int
    timeout_seconds: int
    organization_name: str
    cloud_base_url: str
    browser_channel: str
    headless: bool
    region: str
    timezone: str
    scenario: str
    device_username: str | None
    device_password: str | None


@dataclass(frozen=True)
class NamingSettings:
    ssid_prefix: str
    ssid_template: str
    ssid_suffix_length: int
    password_specials: str


@dataclass(frozen=True)
class ZohoOAuthSettings:
    enabled: bool
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    accounts_base_url: str
    scopes: tuple[str, ...]
    credentials_path: Path
    state_secret: str
    state_ttl_seconds: int


@dataclass(frozen=True)
class AppSettings:
    api: ApiSettings
    output: OutputSettings
    pdf: DownstreamPdfSettings
    omada: DownstreamOmadaSettings
    naming: NamingSettings
    zoho_oauth: ZohoOAuthSettings


def load_settings() -> AppSettings:
    output_root = Path(os.getenv("SITE_WORKFLOW_OUTPUT_ROOT", PROJECT_ROOT / "output" / "site_workflow")).resolve()
    api_key_env = os.getenv("SITE_WORKFLOW_API_KEY_ENV", "SITE_WORKFLOW_API_KEY")
    api_key_value = os.getenv(api_key_env, "")
    zoho_scopes_raw = os.getenv(
        "ZOHO_OAUTH_SCOPES",
        "WorkDrive.files.READ,WorkDrive.files.CREATE,WorkDrive.files.UPDATE",
    )
    zoho_scopes = tuple(scope.strip() for scope in zoho_scopes_raw.split(",") if scope.strip())
    zoho_credentials_path = Path(
        os.getenv("ZOHO_OAUTH_CREDENTIALS_PATH", output_root / "integrations" / "zoho-oauth.json")
    ).resolve()
    zoho_client_id = os.getenv("ZOHO_OAUTH_CLIENT_ID")
    zoho_client_secret = os.getenv("ZOHO_OAUTH_CLIENT_SECRET")
    zoho_redirect_uri = os.getenv("ZOHO_OAUTH_REDIRECT_URI")
    zoho_accounts_base_url = os.getenv("ZOHO_OAUTH_ACCOUNTS_BASE_URL", "https://accounts.zoho.com").rstrip("/")
    zoho_state_secret = os.getenv("ZOHO_OAUTH_STATE_SECRET") or api_key_value or "workflow-api"

    return AppSettings(
        api=ApiSettings(
            api_key_env=api_key_env,
            bind_host=os.getenv("SITE_WORKFLOW_HOST", "127.0.0.1"),
            bind_port=_env_int("SITE_WORKFLOW_PORT", 8100),
        ),
        output=OutputSettings(
            root_dir=output_root,
            jobs_dir=output_root / "jobs",
        ),
        pdf=DownstreamPdfSettings(
            base_url=os.getenv("PASSWORD_PDF_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            api_key=os.getenv("PASSWORD_PDF_API_KEY"),
            poll_interval_seconds=_env_int("PASSWORD_PDF_POLL_INTERVAL_SECONDS", 2),
            timeout_seconds=_env_int("PASSWORD_PDF_TIMEOUT_SECONDS", 600),
        ),
        omada=DownstreamOmadaSettings(
            base_url=os.getenv("OMADA_SITE_CREATOR_BASE_URL", "http://127.0.0.1:3210").rstrip("/"),
            webhook_token=os.getenv("OMADA_SITE_CREATOR_WEBHOOK_TOKEN", ""),
            poll_interval_seconds=_env_int("OMADA_SITE_CREATOR_POLL_INTERVAL_SECONDS", 2),
            timeout_seconds=_env_int("OMADA_SITE_CREATOR_TIMEOUT_SECONDS", 900),
            organization_name=os.getenv("OMADA_ORGANIZATION_NAME", "Opticable"),
            cloud_base_url=os.getenv("OMADA_CLOUD_BASE_URL", "https://use1-omada-cloud.tplinkcloud.com/"),
            browser_channel=os.getenv("OMADA_BROWSER_CHANNEL", "chromium"),
            headless=_env_bool("OMADA_HEADLESS", True),
            region=os.getenv("OMADA_DEFAULT_REGION", "Canada"),
            timezone=os.getenv("OMADA_DEFAULT_TIMEZONE", "America/Toronto"),
            scenario=os.getenv("OMADA_DEFAULT_SCENARIO", "Office"),
            device_username=os.getenv("OMADA_DEVICE_USERNAME"),
            device_password=os.getenv("OMADA_DEVICE_PASSWORD"),
        ),
        naming=NamingSettings(
            ssid_prefix=os.getenv("SITE_WORKFLOW_SSID_PREFIX", "APT_"),
            ssid_template=os.getenv("SITE_WORKFLOW_SSID_TEMPLATE", "{prefix}{identifier}_{suffix}"),
            ssid_suffix_length=_env_int("SITE_WORKFLOW_SSID_SUFFIX_LENGTH", 2),
            password_specials=os.getenv("SITE_WORKFLOW_PASSWORD_SPECIALS", "*!$@#"),
        ),
        zoho_oauth=ZohoOAuthSettings(
            enabled=bool(zoho_client_id and zoho_client_secret and zoho_redirect_uri),
            client_id=zoho_client_id,
            client_secret=zoho_client_secret,
            redirect_uri=zoho_redirect_uri,
            accounts_base_url=zoho_accounts_base_url,
            scopes=zoho_scopes,
            credentials_path=zoho_credentials_path,
            state_secret=zoho_state_secret,
            state_ttl_seconds=_env_int("ZOHO_OAUTH_STATE_TTL_SECONDS", 900),
        ),
    )
