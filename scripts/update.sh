#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Opticable-Api-VM01"
REPO_URL="${SITE_AND_PASSWORD_CREATOR_REPO_URL:-https://github.com/yboucher97/Opticable-Api-VM01.git}"
REPO_REF="${SITE_AND_PASSWORD_CREATOR_REPO_REF:-main}"
INSTALL_DIR="${SITE_AND_PASSWORD_CREATOR_INSTALL_DIR:-/opt/opticable-api-platform}"

log() {
  printf '[%s update] %s\n' "${APP_NAME}" "$*"
}

fail() {
  printf '[%s update] ERROR: %s\n' "${APP_NAME}" "$*" >&2
  exit 1
}

if [[ "${EUID}" -ne 0 ]]; then
  fail "Run as root. Example: sudo bash <(curl -fsSL https://raw.githubusercontent.com/yboucher97/Opticable-Api-VM01/main/scripts/update.sh)"
fi

if [[ ! -d "${INSTALL_DIR}/.git" ]]; then
  log "Install directory is missing. Running first install instead."
  SITE_AND_PASSWORD_CREATOR_REPO_URL="${REPO_URL}" \
  SITE_AND_PASSWORD_CREATOR_REPO_REF="${REPO_REF}" \
  SITE_AND_PASSWORD_CREATOR_INSTALL_DIR="${INSTALL_DIR}" \
  bash <(curl -fsSL "https://raw.githubusercontent.com/yboucher97/Opticable-Api-VM01/${REPO_REF}/install.sh")
  exit 0
fi

if [[ -n "$(git -C "${INSTALL_DIR}" status --porcelain)" ]]; then
  fail "Local source tree has uncommitted changes in ${INSTALL_DIR}. Commit, stash, or remove them before updating from GitHub."
fi

log "Fetching ${REPO_URL} (${REPO_REF})."
git -C "${INSTALL_DIR}" remote set-url origin "${REPO_URL}"
git -C "${INSTALL_DIR}" fetch --tags origin
git -C "${INSTALL_DIR}" checkout "${REPO_REF}"
git -C "${INSTALL_DIR}" pull --ff-only origin "${REPO_REF}"

log "Re-running installer to rebuild dependencies, runtime files, systemd units, and Caddy."
SITE_AND_PASSWORD_CREATOR_REPO_URL="${REPO_URL}" \
SITE_AND_PASSWORD_CREATOR_REPO_REF="${REPO_REF}" \
SITE_AND_PASSWORD_CREATOR_INSTALL_DIR="${INSTALL_DIR}" \
"${INSTALL_DIR}/install.sh"

log "Update complete."
