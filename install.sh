#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Opticable-Api-VM01"
REPO_URL="${SITE_AND_PASSWORD_CREATOR_REPO_URL:-https://github.com/yboucher97/Opticable-Api-VM01.git}"
REPO_REF="${SITE_AND_PASSWORD_CREATOR_REPO_REF:-main}"
INSTALL_DIR="${SITE_AND_PASSWORD_CREATOR_INSTALL_DIR:-/opt/opticable-api-platform}"

PUBLIC_API_HOST="${SITE_AND_PASSWORD_API_HOST:-}"
SHARED_GROUP="${SITE_AND_PASSWORD_SHARED_GROUP:-siteandpassword}"
SHARED_DATA_DIR="${SITE_AND_PASSWORD_SHARED_DATA_DIR:-/var/lib/opticable-api-platform/shared}"
ZOHO_OAUTH_CREDENTIALS_PATH="${ZOHO_OAUTH_CREDENTIALS_PATH:-${SHARED_DATA_DIR}/zoho-oauth.json}"
INSTALL_RUNTIME_SNAPSHOT="${INSTALL_RUNTIME_SNAPSHOT:-/root/opticable-api-platform.generated.env}"

PDF_APP_DIR="${INSTALL_DIR}/apps/password-pdf-service"
PDF_SERVICE_NAME="${PASSWORD_PDF_SERVICE_NAME:-opticable-password-pdf}"
PDF_SERVICE_USER="${PASSWORD_PDF_SERVICE_USER:-opticable-password-pdf}"
PDF_DATA_DIR="${PASSWORD_PDF_DATA_DIR:-/var/lib/opticable-password-pdf}"
PDF_CONFIG_DIR="${PASSWORD_PDF_CONFIG_DIR:-/etc/opticable-password-pdf}"
PDF_CONFIG_PATH="${PDF_CONFIG_DIR}/brand_settings.json"
PDF_ENV_FILE="${PASSWORD_PDF_ENV_FILE:-/etc/opticable-password-pdf.env}"
PDF_PORT="${PASSWORD_PDF_PORT:-8000}"
PDF_HOST="${PASSWORD_PDF_HOST:-}"

OMADA_APP_DIR="${INSTALL_DIR}/apps/omada-site-service"
OMADA_SERVICE_NAME="${OMADA_SITE_CREATOR_SERVICE_NAME:-opticable-omada-site}"
OMADA_SERVICE_USER="${OMADA_SITE_CREATOR_USER:-opticable-omada-site}"
OMADA_DATA_DIR="${OMADA_SITE_CREATOR_DATA_DIR:-/var/lib/opticable-omada-site}"
OMADA_ENV_FILE="${OMADA_SITE_CREATOR_ENV_FILE:-/etc/opticable-omada-site.env}"
OMADA_PORT="${OMADA_SITE_CREATOR_PORT:-3210}"
OMADA_HOST="${OMADA_SITE_CREATOR_PUBLIC_HOST:-}"
OMADA_PLAYWRIGHT_BROWSERS_PATH="${OMADA_SITE_CREATOR_PLAYWRIGHT_BROWSERS_PATH:-${OMADA_DATA_DIR}/ms-playwright}"

WORKFLOW_APP_DIR="${INSTALL_DIR}/apps/workflow-api"
WORKFLOW_SERVICE_NAME="${SITE_AND_PASSWORD_WORKFLOW_SERVICE_NAME:-opticable-workflow-api}"
WORKFLOW_SERVICE_USER="${SITE_AND_PASSWORD_WORKFLOW_USER:-opticable-workflow-api}"
WORKFLOW_DATA_DIR="${SITE_AND_PASSWORD_WORKFLOW_DATA_DIR:-/var/lib/opticable-workflow-api}"
WORKFLOW_ENV_FILE="${SITE_AND_PASSWORD_WORKFLOW_ENV_FILE:-/etc/opticable-workflow-api.env}"
WORKFLOW_PORT="${SITE_AND_PASSWORD_WORKFLOW_PORT:-8100}"
WORKFLOW_HOST="${SITE_AND_PASSWORD_WORKFLOW_PUBLIC_HOST:-}"

PASSWORD_PDF_API_KEY="${PASSWORD_PDF_API_KEY:-${WIFI_PDF_API_KEY:-}}"
OMADA_SITE_CREATOR_WEBHOOK_TOKEN="${OMADA_SITE_CREATOR_WEBHOOK_TOKEN:-}"
SITE_AND_PASSWORD_WORKFLOW_API_KEY="${SITE_AND_PASSWORD_WORKFLOW_API_KEY:-${SITE_WORKFLOW_API_KEY:-}}"
PASSWORD_PDF_ENABLE_WORKDRIVE="${PASSWORD_PDF_ENABLE_WORKDRIVE:-true}"
PASSWORD_PDF_ZOHO_REGION="${PASSWORD_PDF_ZOHO_REGION:-com}"
ZOHO_OAUTH_CLIENT_ID="${ZOHO_OAUTH_CLIENT_ID:-}"
ZOHO_OAUTH_CLIENT_SECRET="${ZOHO_OAUTH_CLIENT_SECRET:-}"
ZOHO_OAUTH_ACCOUNTS_BASE_URL="${ZOHO_OAUTH_ACCOUNTS_BASE_URL:-}"
ZOHO_OAUTH_REDIRECT_URI="${ZOHO_OAUTH_REDIRECT_URI:-}"
ZOHO_OAUTH_SCOPES="${ZOHO_OAUTH_SCOPES:-WorkDrive.files.READ,WorkDrive.files.CREATE,WorkDrive.files.UPDATE}"
AUTO_SWAP_ENABLED="${AUTO_SWAP_ENABLED:-true}"
AUTO_SWAP_SIZE_GB="${AUTO_SWAP_SIZE_GB:-4}"
AUTO_SWAP_PATH="${AUTO_SWAP_PATH:-/swapfile}"

LEGACY_PDF_SERVICE_NAME="password-pdf-generator"
LEGACY_PDF_SERVICE_USER="passwordpdf"
LEGACY_PDF_DATA_DIR="/var/lib/password-pdf-generator"
LEGACY_PDF_CONFIG_DIR="/etc/password-pdf-generator"
LEGACY_PDF_ENV_FILE="/etc/password-pdf-generator.env"

LEGACY_OMADA_SERVICE_NAME="omada-site-creator"
LEGACY_OMADA_SERVICE_USER="omada-site-creator"
LEGACY_OMADA_DATA_DIR="/var/lib/omada-site-creator"
LEGACY_OMADA_ENV_FILE="/etc/omada-site-creator.env"

LEGACY_WORKFLOW_SERVICE_NAME="site-and-password-workflow"
LEGACY_WORKFLOW_SERVICE_USER="sitepasswordworkflow"
LEGACY_WORKFLOW_DATA_DIR="/var/lib/site-and-password-workflow"
LEGACY_WORKFLOW_ENV_FILE="/etc/site-and-password-workflow.env"

log() {
  printf '[%s] %s\n' "${APP_NAME}" "$*"
}

fail() {
  printf '[%s] ERROR: %s\n' "${APP_NAME}" "$*" >&2
  exit 1
}

generate_secret() {
  od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
}

resolve_zoho_accounts_base() {
  case "${PASSWORD_PDF_ZOHO_REGION}" in
    com)
      printf '%s' "https://accounts.zoho.com"
      ;;
    eu)
      printf '%s' "https://accounts.zoho.eu"
      ;;
    in)
      printf '%s' "https://accounts.zoho.in"
      ;;
    com.au)
      printf '%s' "https://accounts.zoho.com.au"
      ;;
    *)
      fail "Unsupported PASSWORD_PDF_ZOHO_REGION: ${PASSWORD_PDF_ZOHO_REGION}"
      ;;
  esac
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    fail "Run this installer as root. Example: sudo bash <(curl -fsSL https://raw.githubusercontent.com/yboucher97/Opticable-Api-VM01/main/install.sh)"
  fi
}

ensure_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y git curl ca-certificates openssl python3 python3-venv python3-pip caddy ufw build-essential unzip

  local node_major=""
  if command -v node >/dev/null 2>&1; then
    node_major="$(node -p 'process.versions.node.split(\".\")[0]' 2>/dev/null || true)"
  fi

  if [[ -z "${node_major}" || "${node_major}" -lt 22 ]]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y nodejs
  fi
}

ensure_swap() {
  if [[ "${AUTO_SWAP_ENABLED,,}" != "true" ]]; then
    return
  fi

  local mem_kb
  mem_kb="$(awk '/MemTotal/ { print $2 }' /proc/meminfo)"
  if [[ -z "${mem_kb}" ]]; then
    return
  fi

  if swapon --show=NAME --noheadings 2>/dev/null | grep -q .; then
    return
  fi

  # Small cloud VMs are unstable under Playwright without swap.
  if (( mem_kb > 2097152 )); then
    return
  fi

  if [[ -f "${AUTO_SWAP_PATH}" ]]; then
    chmod 600 "${AUTO_SWAP_PATH}"
    mkswap "${AUTO_SWAP_PATH}" >/dev/null 2>&1 || true
    swapon "${AUTO_SWAP_PATH}" >/dev/null 2>&1 || true
  else
    fallocate -l "${AUTO_SWAP_SIZE_GB}G" "${AUTO_SWAP_PATH}"
    chmod 600 "${AUTO_SWAP_PATH}"
    mkswap "${AUTO_SWAP_PATH}" >/dev/null
    swapon "${AUTO_SWAP_PATH}"
  fi

  if ! grep -Fq "${AUTO_SWAP_PATH} none swap sw 0 0" /etc/fstab; then
    echo "${AUTO_SWAP_PATH} none swap sw 0 0" >> /etc/fstab
  fi
}

ensure_secrets() {
  if [[ -z "${PASSWORD_PDF_API_KEY}" ]]; then
    PASSWORD_PDF_API_KEY="$(generate_secret)"
  fi
  if [[ -z "${OMADA_SITE_CREATOR_WEBHOOK_TOKEN}" ]]; then
    OMADA_SITE_CREATOR_WEBHOOK_TOKEN="$(generate_secret)"
  fi
  if [[ -z "${SITE_AND_PASSWORD_WORKFLOW_API_KEY}" ]]; then
    SITE_AND_PASSWORD_WORKFLOW_API_KEY="$(generate_secret)"
  fi
}

stop_service_if_present() {
  local service_name="$1"
  if systemctl is-active --quiet "${service_name}" 2>/dev/null; then
    systemctl stop "${service_name}" || true
  fi
  if systemctl is-enabled --quiet "${service_name}" 2>/dev/null; then
    systemctl disable "${service_name}" || true
  fi
}

migrate_file_if_needed() {
  local legacy_path="$1"
  local new_path="$2"
  if [[ "${legacy_path}" == "${new_path}" || ! -f "${legacy_path}" ]]; then
    return
  fi

  mkdir -p "$(dirname "${new_path}")"
  if [[ ! -e "${new_path}" ]]; then
    mv "${legacy_path}" "${new_path}"
    return
  fi

  if cmp -s "${legacy_path}" "${new_path}"; then
    rm -f "${legacy_path}"
    return
  fi

  cp -f "${legacy_path}" "${new_path}.legacy.bak"
  rm -f "${legacy_path}"
}

migrate_dir_if_needed() {
  local legacy_path="$1"
  local new_path="$2"
  if [[ "${legacy_path}" == "${new_path}" || ! -d "${legacy_path}" ]]; then
    return
  fi

  mkdir -p "$(dirname "${new_path}")"
  if [[ ! -e "${new_path}" ]]; then
    mv "${legacy_path}" "${new_path}"
    return
  fi

  cp -a "${legacy_path}/." "${new_path}/"
  rm -rf "${legacy_path}"
}

migrate_legacy_runtime_artifacts() {
  if [[ "${PDF_SERVICE_NAME}" != "${LEGACY_PDF_SERVICE_NAME}" ]]; then
    stop_service_if_present "${LEGACY_PDF_SERVICE_NAME}"
    migrate_file_if_needed "${LEGACY_PDF_ENV_FILE}" "${PDF_ENV_FILE}"
    migrate_dir_if_needed "${LEGACY_PDF_CONFIG_DIR}" "${PDF_CONFIG_DIR}"
    migrate_dir_if_needed "${LEGACY_PDF_DATA_DIR}" "${PDF_DATA_DIR}"
  fi

  if [[ "${OMADA_SERVICE_NAME}" != "${LEGACY_OMADA_SERVICE_NAME}" ]]; then
    stop_service_if_present "${LEGACY_OMADA_SERVICE_NAME}"
    migrate_file_if_needed "${LEGACY_OMADA_ENV_FILE}" "${OMADA_ENV_FILE}"
    migrate_dir_if_needed "${LEGACY_OMADA_DATA_DIR}" "${OMADA_DATA_DIR}"
  fi

  if [[ "${WORKFLOW_SERVICE_NAME}" != "${LEGACY_WORKFLOW_SERVICE_NAME}" ]]; then
    stop_service_if_present "${LEGACY_WORKFLOW_SERVICE_NAME}"
    migrate_file_if_needed "${LEGACY_WORKFLOW_ENV_FILE}" "${WORKFLOW_ENV_FILE}"
    migrate_dir_if_needed "${LEGACY_WORKFLOW_DATA_DIR}" "${WORKFLOW_DATA_DIR}"
  fi
}

cleanup_legacy_runtime_artifacts() {
  local removed_systemd_units=0
  local removed_caddy_files=0
  local legacy_files=(
    "/etc/systemd/system/${LEGACY_PDF_SERVICE_NAME}.service"
    "/etc/systemd/system/${LEGACY_OMADA_SERVICE_NAME}.service"
    "/etc/systemd/system/${LEGACY_WORKFLOW_SERVICE_NAME}.service"
    "/etc/caddy/conf.d/${LEGACY_PDF_SERVICE_NAME}.caddy"
    "/etc/caddy/conf.d/${LEGACY_OMADA_SERVICE_NAME}.caddy"
    "/etc/caddy/conf.d/${LEGACY_WORKFLOW_SERVICE_NAME}.caddy"
    "${LEGACY_PDF_ENV_FILE}"
    "${LEGACY_OMADA_ENV_FILE}"
    "${LEGACY_WORKFLOW_ENV_FILE}"
  )

  local legacy_dirs=(
    "${LEGACY_PDF_DATA_DIR}"
    "${LEGACY_PDF_CONFIG_DIR}"
    "${LEGACY_OMADA_DATA_DIR}"
    "${LEGACY_WORKFLOW_DATA_DIR}"
  )

  for path in "${legacy_files[@]}"; do
    if [[ -e "${path}" ]]; then
      case "${path}" in
        /etc/systemd/system/*.service)
          removed_systemd_units=1
          ;;
        /etc/caddy/conf.d/*.caddy)
          removed_caddy_files=1
          ;;
      esac
      rm -f "${path}"
    fi
  done

  for path in "${legacy_dirs[@]}"; do
    if [[ -d "${path}" ]]; then
      rmdir "${path}" 2>/dev/null || true
    fi
  done

  systemctl reset-failed "${LEGACY_PDF_SERVICE_NAME}" "${LEGACY_OMADA_SERVICE_NAME}" "${LEGACY_WORKFLOW_SERVICE_NAME}" 2>/dev/null || true
  if (( removed_systemd_units )); then
    systemctl daemon-reload
  fi
  if (( removed_caddy_files )) && systemctl is-active --quiet caddy 2>/dev/null; then
    caddy validate --config /etc/caddy/Caddyfile
    systemctl reload caddy
  fi
}

ensure_users_and_dirs() {
  if ! getent group "${SHARED_GROUP}" >/dev/null 2>&1; then
    groupadd --system "${SHARED_GROUP}"
  fi

  if ! id -u "${PDF_SERVICE_USER}" >/dev/null 2>&1; then
    useradd --system --create-home --home "${PDF_DATA_DIR}" --shell /usr/sbin/nologin "${PDF_SERVICE_USER}"
  fi
  if ! id -u "${OMADA_SERVICE_USER}" >/dev/null 2>&1; then
    useradd --system --create-home --home "${OMADA_DATA_DIR}" --shell /usr/sbin/nologin "${OMADA_SERVICE_USER}"
  fi
  if ! id -u "${WORKFLOW_SERVICE_USER}" >/dev/null 2>&1; then
    useradd --system --create-home --home "${WORKFLOW_DATA_DIR}" --shell /usr/sbin/nologin "${WORKFLOW_SERVICE_USER}"
  fi

  usermod -a -G "${SHARED_GROUP}" "${PDF_SERVICE_USER}"
  usermod -a -G "${SHARED_GROUP}" "${WORKFLOW_SERVICE_USER}"

  mkdir -p "${PDF_DATA_DIR}" "${PDF_CONFIG_DIR}" "${OMADA_DATA_DIR}" "${WORKFLOW_DATA_DIR}"
  install -d -m 2770 -o root -g "${SHARED_GROUP}" "${SHARED_DATA_DIR}"
  chown -R "${PDF_SERVICE_USER}:${PDF_SERVICE_USER}" "${PDF_DATA_DIR}"
  chown -R "${OMADA_SERVICE_USER}:${OMADA_SERVICE_USER}" "${OMADA_DATA_DIR}"
  chown -R "${WORKFLOW_SERVICE_USER}:${WORKFLOW_SERVICE_USER}" "${WORKFLOW_DATA_DIR}"
}

sync_repo() {
  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    git -C "${INSTALL_DIR}" fetch --tags origin
    git -C "${INSTALL_DIR}" checkout "${REPO_REF}"
    git -C "${INSTALL_DIR}" pull --ff-only origin "${REPO_REF}"
  else
    rm -rf "${INSTALL_DIR}"
    git clone --branch "${REPO_REF}" "${REPO_URL}" "${INSTALL_DIR}"
  fi
}

configure_pdf_json() {
  local workdrive_api_base
  local workdrive_accounts_base
  local crm_api_base

  case "${PASSWORD_PDF_ZOHO_REGION}" in
    com)
      workdrive_api_base="https://www.zohoapis.com/workdrive/api/v1"
      workdrive_accounts_base="https://accounts.zoho.com/oauth/v2/token"
      crm_api_base="https://www.zohoapis.com/crm/v7"
      ;;
    eu)
      workdrive_api_base="https://www.zohoapis.eu/workdrive/api/v1"
      workdrive_accounts_base="https://accounts.zoho.eu/oauth/v2/token"
      crm_api_base="https://www.zohoapis.eu/crm/v7"
      ;;
    in)
      workdrive_api_base="https://www.zohoapis.in/workdrive/api/v1"
      workdrive_accounts_base="https://accounts.zoho.in/oauth/v2/token"
      crm_api_base="https://www.zohoapis.in/crm/v7"
      ;;
    com.au)
      workdrive_api_base="https://www.zohoapis.com.au/workdrive/api/v1"
      workdrive_accounts_base="https://accounts.zoho.com.au/oauth/v2/token"
      crm_api_base="https://www.zohoapis.com.au/crm/v7"
      ;;
    *)
      fail "Unsupported PASSWORD_PDF_ZOHO_REGION: ${PASSWORD_PDF_ZOHO_REGION}"
      ;;
  esac

  if [[ ! -f "${PDF_CONFIG_PATH}" ]]; then
    cp "${PDF_APP_DIR}/config/wifi_pdf/brand_settings.json" "${PDF_CONFIG_PATH}"
  fi

  PDF_CONFIG_PATH="${PDF_CONFIG_PATH}" \
  PDF_OUTPUT_DIR="${PDF_DATA_DIR}/output/pdf/wifi" \
  PASSWORD_PDF_ENABLE_WORKDRIVE="${PASSWORD_PDF_ENABLE_WORKDRIVE}" \
  WORKDRIVE_API_BASE="${workdrive_api_base}" \
  WORKDRIVE_ACCOUNTS_BASE="${workdrive_accounts_base}" \
  CRM_API_BASE="${crm_api_base}" \
  ZOHO_WORKDRIVE_PARENT_FOLDER_ID="${ZOHO_WORKDRIVE_PARENT_FOLDER_ID:-}" \
  python3 - <<'PY'
import json
import os
from pathlib import Path

config_path = Path(os.environ["PDF_CONFIG_PATH"])
payload = json.loads(config_path.read_text(encoding="utf-8"))
payload["output"]["root_dir"] = os.environ["PDF_OUTPUT_DIR"]
payload["workdrive"]["enabled"] = os.environ["PASSWORD_PDF_ENABLE_WORKDRIVE"].lower() == "true"
payload["workdrive"]["api_base_url"] = os.environ["WORKDRIVE_API_BASE"]
payload["workdrive"]["accounts_base_url"] = os.environ["WORKDRIVE_ACCOUNTS_BASE"]
payload.setdefault("crm", {})
payload["crm"]["api_base_url"] = os.environ["CRM_API_BASE"]

folder_id = os.environ.get("ZOHO_WORKDRIVE_PARENT_FOLDER_ID", "").strip()
if folder_id:
    payload["workdrive"]["parent_folder_id"] = folder_id

config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

  chmod 644 "${PDF_CONFIG_PATH}"
}

write_pdf_env() {
  PDF_ENV_FILE="${PDF_ENV_FILE}" \
  PASSWORD_PDF_API_KEY="${PASSWORD_PDF_API_KEY}" \
  ZOHO_WORKDRIVE_PARENT_FOLDER_ID="${ZOHO_WORKDRIVE_PARENT_FOLDER_ID:-}" \
  ZOHO_OAUTH_CREDENTIALS_PATH="${ZOHO_OAUTH_CREDENTIALS_PATH}" \
  python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["PDF_ENV_FILE"])
existing = {}
if path.exists():
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        existing[key] = value

for key in [
    "PASSWORD_PDF_API_KEY",
    "ZOHO_WORKDRIVE_PARENT_FOLDER_ID",
    "ZOHO_OAUTH_CREDENTIALS_PATH",
]:
    value = os.environ.get(key, "")
    if value:
        existing[key] = value

existing["WIFI_PDF_API_KEY"] = os.environ["PASSWORD_PDF_API_KEY"]

ordered = [
    "WIFI_PDF_API_KEY",
    "ZOHO_WORKDRIVE_PARENT_FOLDER_ID",
    "ZOHO_OAUTH_CREDENTIALS_PATH",
]
path.write_text("\n".join(f"{key}={existing.get(key, '')}" for key in ordered) + "\n", encoding="utf-8")
PY

  chmod 600 "${PDF_ENV_FILE}"
}

install_pdf_app() {
  python3 -m venv "${PDF_APP_DIR}/.venv"
  "${PDF_APP_DIR}/.venv/bin/pip" install --no-cache-dir --upgrade pip
  "${PDF_APP_DIR}/.venv/bin/pip" install --no-cache-dir -r "${PDF_APP_DIR}/requirements.txt"
  configure_pdf_json
  write_pdf_env
}

write_pdf_service() {
  cat >"/etc/systemd/system/${PDF_SERVICE_NAME}.service" <<EOF
[Unit]
Description=Password PDF Generator API
After=network.target

[Service]
User=${PDF_SERVICE_USER}
Group=${PDF_SERVICE_USER}
WorkingDirectory=${PDF_APP_DIR}
EnvironmentFile=${PDF_ENV_FILE}
Environment=WIFI_PDF_CONFIG_PATH=${PDF_CONFIG_PATH}
Environment=PATH=${PDF_APP_DIR}/.venv/bin
ExecStart=${PDF_APP_DIR}/.venv/bin/uvicorn wifi_pdf.api:app --host 127.0.0.1 --port ${PDF_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
}

write_omada_env() {
  OMADA_ENV_FILE="${OMADA_ENV_FILE}" \
  OMADA_PORT="${OMADA_PORT}" \
  OMADA_DATA_DIR="${OMADA_DATA_DIR}" \
  OMADA_PLAYWRIGHT_BROWSERS_PATH="${OMADA_PLAYWRIGHT_BROWSERS_PATH}" \
  OMADA_SITE_CREATOR_WEBHOOK_TOKEN="${OMADA_SITE_CREATOR_WEBHOOK_TOKEN}" \
  OMADA_ORGANIZATION_NAME="${OMADA_ORGANIZATION_NAME:-Opticable}" \
  OMADA_SITE_CREATOR_CLOUD_EMAIL="${OMADA_SITE_CREATOR_CLOUD_EMAIL:-}" \
  OMADA_SITE_CREATOR_CLOUD_PASSWORD="${OMADA_SITE_CREATOR_CLOUD_PASSWORD:-}" \
  OMADA_SITE_CREATOR_DEVICE_USERNAME="${OMADA_SITE_CREATOR_DEVICE_USERNAME:-}" \
  OMADA_SITE_CREATOR_DEVICE_PASSWORD="${OMADA_SITE_CREATOR_DEVICE_PASSWORD:-}" \
  OMADA_ORGANIZATION_NAME="${OMADA_ORGANIZATION_NAME:-Opticable}" \
  python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["OMADA_ENV_FILE"])
existing = {}
if path.exists():
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        existing[key] = value

defaults = {
    "NODE_ENV": "production",
    "OMADA_SITE_CREATOR_HOST": "127.0.0.1",
    "OMADA_SITE_CREATOR_PORT": os.environ["OMADA_PORT"],
    "OMADA_SITE_CREATOR_DATA_DIR": f"{os.environ['OMADA_DATA_DIR']}/data",
    "PLAYWRIGHT_BROWSERS_PATH": os.environ["OMADA_PLAYWRIGHT_BROWSERS_PATH"],
    "OMADA_SITE_CREATOR_WEBHOOK_TOKEN": os.environ["OMADA_SITE_CREATOR_WEBHOOK_TOKEN"],
    "OMADA_SITE_CREATOR_HEADLESS": "true",
    "OMADA_SITE_CREATOR_BROWSER_CHANNEL": "chromium",
    "OMADA_ORGANIZATION_NAME": os.environ["OMADA_ORGANIZATION_NAME"],
}

for key, value in defaults.items():
    existing.setdefault(key, value)

legacy_data_dir = "/var/lib/omada-site-creator/data"
legacy_browsers_path = "/var/lib/omada-site-creator/ms-playwright"
if existing.get("OMADA_SITE_CREATOR_DATA_DIR", "").strip() in {"", legacy_data_dir}:
    existing["OMADA_SITE_CREATOR_DATA_DIR"] = defaults["OMADA_SITE_CREATOR_DATA_DIR"]
if existing.get("PLAYWRIGHT_BROWSERS_PATH", "").strip() in {"", legacy_browsers_path}:
    existing["PLAYWRIGHT_BROWSERS_PATH"] = defaults["PLAYWRIGHT_BROWSERS_PATH"]

for key in [
    "OMADA_SITE_CREATOR_WEBHOOK_TOKEN",
    "OMADA_SITE_CREATOR_CLOUD_EMAIL",
    "OMADA_SITE_CREATOR_CLOUD_PASSWORD",
    "OMADA_SITE_CREATOR_DEVICE_USERNAME",
    "OMADA_SITE_CREATOR_DEVICE_PASSWORD",
]:
    value = os.environ.get(key, "").strip()
    if value:
        existing[key] = value

ordered = [
    "NODE_ENV",
    "OMADA_SITE_CREATOR_HOST",
    "OMADA_SITE_CREATOR_PORT",
    "OMADA_SITE_CREATOR_DATA_DIR",
    "PLAYWRIGHT_BROWSERS_PATH",
    "OMADA_SITE_CREATOR_WEBHOOK_TOKEN",
    "OMADA_SITE_CREATOR_HEADLESS",
    "OMADA_SITE_CREATOR_BROWSER_CHANNEL",
    "OMADA_ORGANIZATION_NAME",
    "OMADA_SITE_CREATOR_CLOUD_EMAIL",
    "OMADA_SITE_CREATOR_CLOUD_PASSWORD",
    "OMADA_SITE_CREATOR_DEVICE_USERNAME",
    "OMADA_SITE_CREATOR_DEVICE_PASSWORD",
]

lines = []
for key in ordered:
    if key in existing:
        lines.append(f"{key}={existing[key]}")

path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

  chmod 600 "${OMADA_ENV_FILE}"
}

install_omada_app() {
  pushd "${OMADA_APP_DIR}" >/dev/null
  npm ci --omit=optional
  npm run build
  npm prune --omit=dev --omit=optional
  PLAYWRIGHT_BROWSERS_PATH="${OMADA_PLAYWRIGHT_BROWSERS_PATH}" npx playwright install chromium --with-deps
  npm cache clean --force >/dev/null 2>&1 || true
  popd >/dev/null
  mkdir -p "${OMADA_PLAYWRIGHT_BROWSERS_PATH}"
  chown -R "${OMADA_SERVICE_USER}:${OMADA_SERVICE_USER}" "${OMADA_PLAYWRIGHT_BROWSERS_PATH}"
  write_omada_env
}

write_omada_service() {
  cat >"/etc/systemd/system/${OMADA_SERVICE_NAME}.service" <<EOF
[Unit]
Description=Omada Site Creator
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${OMADA_SERVICE_USER}
Group=${OMADA_SERVICE_USER}
WorkingDirectory=${OMADA_APP_DIR}
EnvironmentFile=${OMADA_ENV_FILE}
Environment=HOME=${OMADA_DATA_DIR}
ExecStart=/usr/bin/node ${OMADA_APP_DIR}/dist/server.js
Restart=always
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF
}

write_workflow_env() {
  local zoho_accounts_base="${ZOHO_OAUTH_ACCOUNTS_BASE_URL:-$(resolve_zoho_accounts_base)}"
  local zoho_redirect_uri="${ZOHO_OAUTH_REDIRECT_URI:-}"
  if [[ -z "${zoho_redirect_uri}" && -n "${PUBLIC_API_HOST}" ]]; then
    zoho_redirect_uri="https://${PUBLIC_API_HOST}/v1/integrations/zoho/oauth/callback"
  fi

  WORKFLOW_ENV_FILE="${WORKFLOW_ENV_FILE}" \
  WORKFLOW_PORT="${WORKFLOW_PORT}" \
  WORKFLOW_DATA_DIR="${WORKFLOW_DATA_DIR}" \
  SITE_AND_PASSWORD_WORKFLOW_API_KEY="${SITE_AND_PASSWORD_WORKFLOW_API_KEY}" \
  PASSWORD_PDF_API_KEY="${PASSWORD_PDF_API_KEY}" \
  OMADA_SITE_CREATOR_WEBHOOK_TOKEN="${OMADA_SITE_CREATOR_WEBHOOK_TOKEN}" \
  OMADA_SITE_CREATOR_CLOUD_EMAIL="${OMADA_SITE_CREATOR_CLOUD_EMAIL:-}" \
  OMADA_SITE_CREATOR_CLOUD_PASSWORD="${OMADA_SITE_CREATOR_CLOUD_PASSWORD:-}" \
  OMADA_SITE_CREATOR_DEVICE_USERNAME="${OMADA_SITE_CREATOR_DEVICE_USERNAME:-}" \
  OMADA_SITE_CREATOR_DEVICE_PASSWORD="${OMADA_SITE_CREATOR_DEVICE_PASSWORD:-}" \
  OMADA_ORGANIZATION_NAME="${OMADA_ORGANIZATION_NAME:-Opticable}" \
  ZOHO_OAUTH_CLIENT_ID="${ZOHO_OAUTH_CLIENT_ID:-}" \
  ZOHO_OAUTH_CLIENT_SECRET="${ZOHO_OAUTH_CLIENT_SECRET:-}" \
  ZOHO_OAUTH_SCOPES="${ZOHO_OAUTH_SCOPES}" \
  ZOHO_OAUTH_ACCOUNTS_BASE_URL="${zoho_accounts_base}" \
  ZOHO_OAUTH_REDIRECT_URI="${zoho_redirect_uri}" \
  ZOHO_OAUTH_CREDENTIALS_PATH="${ZOHO_OAUTH_CREDENTIALS_PATH}" \
  python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["WORKFLOW_ENV_FILE"])
existing = {}
if path.exists():
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        existing[key] = value

defaults = {
    "SITE_WORKFLOW_API_KEY": os.environ["SITE_AND_PASSWORD_WORKFLOW_API_KEY"],
    "SITE_WORKFLOW_HOST": "127.0.0.1",
    "SITE_WORKFLOW_PORT": os.environ["WORKFLOW_PORT"],
    "SITE_WORKFLOW_OUTPUT_ROOT": f"{os.environ['WORKFLOW_DATA_DIR']}/output",
    "SITE_WORKFLOW_SSID_PREFIX": "APT_",
    "SITE_WORKFLOW_SSID_TEMPLATE": "{prefix}{identifier}_{suffix}",
    "SITE_WORKFLOW_SSID_SUFFIX_LENGTH": "2",
    "SITE_WORKFLOW_PASSWORD_SPECIALS": "*!$@#",
    "PASSWORD_PDF_BASE_URL": "http://127.0.0.1:8000",
    "PASSWORD_PDF_API_KEY": os.environ["PASSWORD_PDF_API_KEY"],
    "PASSWORD_PDF_TIMEOUT_SECONDS": "600",
    "OMADA_SITE_CREATOR_BASE_URL": "http://127.0.0.1:3210",
    "OMADA_SITE_CREATOR_WEBHOOK_TOKEN": os.environ["OMADA_SITE_CREATOR_WEBHOOK_TOKEN"],
    "OMADA_SITE_CREATOR_TIMEOUT_SECONDS": "900",
    "OMADA_ORGANIZATION_NAME": os.environ["OMADA_ORGANIZATION_NAME"],
    "OMADA_CLOUD_BASE_URL": "https://use1-omada-cloud.tplinkcloud.com/",
    "OMADA_BROWSER_CHANNEL": "chromium",
    "OMADA_HEADLESS": "true",
    "OMADA_DEFAULT_REGION": "Canada",
    "OMADA_DEFAULT_TIMEZONE": "America/Toronto",
    "OMADA_DEFAULT_SCENARIO": "Office",
    "ZOHO_OAUTH_ACCOUNTS_BASE_URL": os.environ["ZOHO_OAUTH_ACCOUNTS_BASE_URL"],
    "ZOHO_OAUTH_REDIRECT_URI": os.environ["ZOHO_OAUTH_REDIRECT_URI"],
    "ZOHO_OAUTH_SCOPES": os.environ["ZOHO_OAUTH_SCOPES"],
    "ZOHO_OAUTH_CREDENTIALS_PATH": os.environ["ZOHO_OAUTH_CREDENTIALS_PATH"],
}

for key, value in defaults.items():
    existing.setdefault(key, value)

legacy_output_root = "/var/lib/site-and-password-workflow/output"
if existing.get("SITE_WORKFLOW_OUTPUT_ROOT", "").strip() in {"", legacy_output_root}:
    existing["SITE_WORKFLOW_OUTPUT_ROOT"] = defaults["SITE_WORKFLOW_OUTPUT_ROOT"]

for key in [
    "SITE_WORKFLOW_API_KEY",
    "PASSWORD_PDF_API_KEY",
    "OMADA_SITE_CREATOR_WEBHOOK_TOKEN",
    "OMADA_SITE_CREATOR_CLOUD_EMAIL",
    "OMADA_SITE_CREATOR_CLOUD_PASSWORD",
    "OMADA_SITE_CREATOR_DEVICE_USERNAME",
    "OMADA_SITE_CREATOR_DEVICE_PASSWORD",
    "ZOHO_OAUTH_CLIENT_ID",
    "ZOHO_OAUTH_CLIENT_SECRET",
]:
    value = os.environ.get(key, "").strip()
    if value:
        existing[key] = value

ordered = [
    "SITE_WORKFLOW_API_KEY",
    "SITE_WORKFLOW_HOST",
    "SITE_WORKFLOW_PORT",
    "SITE_WORKFLOW_OUTPUT_ROOT",
    "SITE_WORKFLOW_SSID_PREFIX",
    "SITE_WORKFLOW_SSID_TEMPLATE",
    "SITE_WORKFLOW_SSID_SUFFIX_LENGTH",
    "SITE_WORKFLOW_PASSWORD_SPECIALS",
    "PASSWORD_PDF_BASE_URL",
    "PASSWORD_PDF_API_KEY",
    "PASSWORD_PDF_TIMEOUT_SECONDS",
    "OMADA_SITE_CREATOR_BASE_URL",
    "OMADA_SITE_CREATOR_WEBHOOK_TOKEN",
    "OMADA_SITE_CREATOR_TIMEOUT_SECONDS",
    "OMADA_ORGANIZATION_NAME",
    "OMADA_CLOUD_BASE_URL",
    "OMADA_BROWSER_CHANNEL",
    "OMADA_HEADLESS",
    "OMADA_DEFAULT_REGION",
    "OMADA_DEFAULT_TIMEZONE",
    "OMADA_DEFAULT_SCENARIO",
    "ZOHO_OAUTH_CLIENT_ID",
    "ZOHO_OAUTH_CLIENT_SECRET",
    "ZOHO_OAUTH_ACCOUNTS_BASE_URL",
    "ZOHO_OAUTH_REDIRECT_URI",
    "ZOHO_OAUTH_SCOPES",
    "ZOHO_OAUTH_CREDENTIALS_PATH",
    "OMADA_SITE_CREATOR_CLOUD_EMAIL",
    "OMADA_SITE_CREATOR_CLOUD_PASSWORD",
    "OMADA_SITE_CREATOR_DEVICE_USERNAME",
    "OMADA_SITE_CREATOR_DEVICE_PASSWORD",
]
path.write_text("\n".join(f"{key}={existing.get(key, '')}" for key in ordered) + "\n", encoding="utf-8")
PY

  chmod 600 "${WORKFLOW_ENV_FILE}"
}

install_workflow_app() {
  python3 -m venv "${WORKFLOW_APP_DIR}/.venv"
  "${WORKFLOW_APP_DIR}/.venv/bin/pip" install --no-cache-dir --upgrade pip
  "${WORKFLOW_APP_DIR}/.venv/bin/pip" install --no-cache-dir -r "${WORKFLOW_APP_DIR}/requirements.txt"
  write_workflow_env
}

write_workflow_service() {
  cat >"/etc/systemd/system/${WORKFLOW_SERVICE_NAME}.service" <<EOF
[Unit]
Description=Site And Password Workflow
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${WORKFLOW_SERVICE_USER}
Group=${WORKFLOW_SERVICE_USER}
WorkingDirectory=${WORKFLOW_APP_DIR}
EnvironmentFile=${WORKFLOW_ENV_FILE}
Environment=PATH=${WORKFLOW_APP_DIR}/.venv/bin
ExecStart=${WORKFLOW_APP_DIR}/.venv/bin/uvicorn workflow.api:app --host 127.0.0.1 --port ${WORKFLOW_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
}

write_runtime_snapshot() {
  local zoho_accounts_base="${ZOHO_OAUTH_ACCOUNTS_BASE_URL:-$(resolve_zoho_accounts_base)}"
  local zoho_redirect_uri="${ZOHO_OAUTH_REDIRECT_URI:-}"
  if [[ -z "${zoho_redirect_uri}" && -n "${PUBLIC_API_HOST}" ]]; then
    zoho_redirect_uri="https://${PUBLIC_API_HOST}/v1/integrations/zoho/oauth/callback"
  fi

  cat >"${INSTALL_RUNTIME_SNAPSHOT}" <<EOF
SITE_AND_PASSWORD_API_HOST=${PUBLIC_API_HOST}
SITE_AND_PASSWORD_WORKFLOW_API_KEY=${SITE_AND_PASSWORD_WORKFLOW_API_KEY}
PASSWORD_PDF_API_KEY=${PASSWORD_PDF_API_KEY}
OMADA_SITE_CREATOR_WEBHOOK_TOKEN=${OMADA_SITE_CREATOR_WEBHOOK_TOKEN}
ZOHO_OAUTH_CLIENT_ID=${ZOHO_OAUTH_CLIENT_ID}
ZOHO_OAUTH_ACCOUNTS_BASE_URL=${zoho_accounts_base}
ZOHO_OAUTH_REDIRECT_URI=${zoho_redirect_uri}
ZOHO_OAUTH_SCOPES=${ZOHO_OAUTH_SCOPES}
ZOHO_OAUTH_CREDENTIALS_PATH=${ZOHO_OAUTH_CREDENTIALS_PATH}
WORKFLOW_ENV_FILE=${WORKFLOW_ENV_FILE}
PDF_ENV_FILE=${PDF_ENV_FILE}
OMADA_ENV_FILE=${OMADA_ENV_FILE}
EOF
  chmod 600 "${INSTALL_RUNTIME_SNAPSHOT}"
}

configure_caddy() {
  if [[ -z "${PUBLIC_API_HOST}" && -z "${PDF_HOST}" && -z "${OMADA_HOST}" && -z "${WORKFLOW_HOST}" ]]; then
    return
  fi

  mkdir -p /etc/caddy/conf.d
  if [[ ! -f /etc/caddy/Caddyfile ]] || grep -Fq '/usr/share/caddy' /etc/caddy/Caddyfile; then
    cat >/etc/caddy/Caddyfile <<'EOF'
import /etc/caddy/conf.d/*.caddy
EOF
  elif ! grep -Fq 'import /etc/caddy/conf.d/*.caddy' /etc/caddy/Caddyfile; then
    printf '\nimport /etc/caddy/conf.d/*.caddy\n' >> /etc/caddy/Caddyfile
  fi

  if [[ -n "${PUBLIC_API_HOST}" ]]; then
    cat >"/etc/caddy/conf.d/${APP_NAME}.caddy" <<EOF
${PUBLIC_API_HOST} {
    @pdfRoot path /pdf
    redir @pdfRoot /pdf/ 308
    @omadaRoot path /omada
    redir @omadaRoot /omada/ 308
    @workflowRoot path /workflow
    redir @workflowRoot /workflow/ 308

    handle_path /pdf/* {
        reverse_proxy 127.0.0.1:${PDF_PORT}
    }

    handle_path /omada/* {
        reverse_proxy 127.0.0.1:${OMADA_PORT}
    }

    handle_path /workflow/* {
        reverse_proxy 127.0.0.1:${WORKFLOW_PORT}
    }

    reverse_proxy 127.0.0.1:${WORKFLOW_PORT}
}
EOF
    caddy fmt --overwrite "/etc/caddy/conf.d/${APP_NAME}.caddy" >/dev/null
  else
    if [[ -n "${PDF_HOST}" ]]; then
      cat >"/etc/caddy/conf.d/${PDF_SERVICE_NAME}.caddy" <<EOF
${PDF_HOST} {
    reverse_proxy 127.0.0.1:${PDF_PORT}
}
EOF
      caddy fmt --overwrite "/etc/caddy/conf.d/${PDF_SERVICE_NAME}.caddy" >/dev/null
    fi

    if [[ -n "${OMADA_HOST}" ]]; then
      cat >"/etc/caddy/conf.d/${OMADA_SERVICE_NAME}.caddy" <<EOF
${OMADA_HOST} {
    reverse_proxy 127.0.0.1:${OMADA_PORT}
}
EOF
      caddy fmt --overwrite "/etc/caddy/conf.d/${OMADA_SERVICE_NAME}.caddy" >/dev/null
    fi

    if [[ -n "${WORKFLOW_HOST}" ]]; then
      cat >"/etc/caddy/conf.d/${WORKFLOW_SERVICE_NAME}.caddy" <<EOF
${WORKFLOW_HOST} {
    reverse_proxy 127.0.0.1:${WORKFLOW_PORT}
}
EOF
      caddy fmt --overwrite "/etc/caddy/conf.d/${WORKFLOW_SERVICE_NAME}.caddy" >/dev/null
    fi
  fi

  caddy fmt --overwrite /etc/caddy/Caddyfile >/dev/null
  caddy validate --config /etc/caddy/Caddyfile
  systemctl enable --now caddy
  systemctl reload caddy
}

configure_ufw() {
  ufw allow OpenSSH >/dev/null 2>&1 || true
  if [[ -n "${PUBLIC_API_HOST}" || -n "${PDF_HOST}" || -n "${OMADA_HOST}" || -n "${WORKFLOW_HOST}" ]]; then
    ufw allow 80/tcp >/dev/null 2>&1 || true
    ufw allow 443/tcp >/dev/null 2>&1 || true
  fi
  ufw --force enable >/dev/null 2>&1 || true
}

start_services() {
  systemctl daemon-reload
  systemctl enable --now "${PDF_SERVICE_NAME}"
  systemctl enable --now "${OMADA_SERVICE_NAME}"
  systemctl enable --now "${WORKFLOW_SERVICE_NAME}"
}

print_summary() {
  echo
  echo "Combined install complete."
  echo "Code directory:  ${INSTALL_DIR}"
  echo "PDF config:      ${PDF_CONFIG_PATH}"
  echo "PDF env:         ${PDF_ENV_FILE}"
  echo "Omada env:       ${OMADA_ENV_FILE}"
  echo "Workflow env:    ${WORKFLOW_ENV_FILE}"
  echo "Zoho OAuth file: ${ZOHO_OAUTH_CREDENTIALS_PATH}"
  echo "Runtime snapshot:${INSTALL_RUNTIME_SNAPSHOT}"
  echo "Services:"
  echo "  - ${PDF_SERVICE_NAME}"
  echo "  - ${OMADA_SERVICE_NAME}"
  echo "  - ${WORKFLOW_SERVICE_NAME}"
  if swapon --show=NAME --noheadings 2>/dev/null | grep -q .; then
    echo "Swap:"
    swapon --show=NAME,SIZE --noheadings | sed 's/^/  - /'
  fi
  echo
  echo "Local checks:"
  echo "  - curl http://127.0.0.1:${PDF_PORT}/health"
  echo "  - curl http://127.0.0.1:${OMADA_PORT}/api/health"
  echo "  - curl http://127.0.0.1:${WORKFLOW_PORT}/health"
  if [[ -n "${PUBLIC_API_HOST}" ]]; then
    echo
    echo "Public base URL: https://${PUBLIC_API_HOST}"
    echo "Docs:            https://${PUBLIC_API_HOST}/docs"
    echo "OpenAPI JSON:    https://${PUBLIC_API_HOST}/openapi.json"
    echo "Catalog:         https://${PUBLIC_API_HOST}/v1/system/catalog"
    echo "Workflow create:  https://${PUBLIC_API_HOST}/v1/workflows/site-and-password"
    echo "Workflow jobs:    https://${PUBLIC_API_HOST}/v1/workflows/site-and-password/jobs/{job_id}"
    echo "Workflow health:  https://${PUBLIC_API_HOST}/v1/system/health"
    echo "Zoho OAuth start: https://${PUBLIC_API_HOST}/v1/integrations/zoho/oauth/start"
    echo "Zoho OAuth status: https://${PUBLIC_API_HOST}/v1/integrations/zoho/oauth/status"
    echo "PDF health:       https://${PUBLIC_API_HOST}/pdf/health"
    echo "Omada health:     https://${PUBLIC_API_HOST}/omada/api/health"
    echo
    echo "Next step:"
    echo "  1. Open Zoho OAuth start URL in a browser once."
    echo "  2. Approve access."
    echo "  3. Check status at https://${PUBLIC_API_HOST}/v1/integrations/zoho/oauth/status"
  fi
}

main() {
  require_root
  ensure_packages
  ensure_swap
  ensure_secrets
  sync_repo
  migrate_legacy_runtime_artifacts
  ensure_users_and_dirs
  install_pdf_app
  write_pdf_service
  install_omada_app
  write_omada_service
  install_workflow_app
  write_workflow_service
  write_runtime_snapshot
  configure_caddy
  configure_ufw
  start_services
  cleanup_legacy_runtime_artifacts
  print_summary
}

main "$@"
