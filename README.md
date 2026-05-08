# Opticable-Api-VM01

Production VM stack for Opticable automation.

This repository installs and runs three local services on one Linux VM:

- `workflow-api`: public FastAPI webhook/API gateway for Zoho-triggered workflows.
- `password-pdf-service`: WiFi credential PDF/TXT/ZIP/YA generator with Zoho WorkDrive and CRM updates.
- `omada-site-service`: TP-Link Omada site/LAN/WLAN/SSID automation service.

The normal production path is:

Zoho CRM Service contract signed -> Workflow API -> Password/PDF service -> WorkDrive -> Omada service -> WorkDrive live snapshot.

## Quick Install

Run this on a fresh Ubuntu/Debian VM:

```bash
sudo SITE_AND_PASSWORD_API_HOST=api01.opticable.ca \
bash <(curl -fsSL https://raw.githubusercontent.com/yboucher97/Opticable-Api-VM01/main/install.sh)
```

The installer is idempotent. It can be run again after changing env variables or pulling new code.

## Quick Update

After GitHub has new changes, update an installed VM with:

```bash
sudo bash <(curl -fsSL https://raw.githubusercontent.com/yboucher97/Opticable-Api-VM01/main/scripts/update.sh)
```

The update command pulls `main` from GitHub and reruns the installer so Python packages, Node packages, built assets, systemd units, Caddy config, and runtime folders match the repository.

## Dumbed-Down Version

- This VM receives Zoho webhooks.
- It checks the Service payload.
- If the service is WiFi, it generates SSIDs and passwords.
- It creates tenant WiFi PDFs and password files.
- It uploads PDF/TXT/ZIP/YA files into WorkDrive under `Document/Passwords`.
- It creates/uploads Omada controller files under `Document/Controller`.
- It signs into Omada and creates or updates the site, VLANs, WLAN groups, and SSIDs.
- It writes generated SSIDs/passwords back to the Zoho CRM Service record.
- GitHub `main` is the source of truth.
- `install.sh` installs everything.
- `scripts/update.sh` updates everything.

## Runtime Layout

Code:

- `/opt/opticable-api-platform`

Shared credentials:

- `/var/lib/opticable-api-platform/shared/zoho-oauth.json`

PDF service:

- service: `opticable-password-pdf`
- code: `/opt/opticable-api-platform/apps/password-pdf-service`
- env: `/etc/opticable-password-pdf.env`
- config: `/etc/opticable-password-pdf/brand_settings.json`
- data: `/var/lib/opticable-password-pdf`
- local health: `http://127.0.0.1:8000/health`

Omada service:

- service: `opticable-omada-site`
- code: `/opt/opticable-api-platform/apps/omada-site-service`
- env: `/etc/opticable-omada-site.env`
- data: `/var/lib/opticable-omada-site`
- local health: `http://127.0.0.1:3210/api/health`

Workflow service:

- service: `opticable-workflow-api`
- code: `/opt/opticable-api-platform/apps/workflow-api`
- env: `/etc/opticable-workflow-api.env`
- data: `/var/lib/opticable-workflow-api`
- local health: `http://127.0.0.1:8100/v1/system/health`

Generated runtime snapshot:

- `/root/opticable-api-platform.generated.env`

## Public API

When installed with:

```bash
SITE_AND_PASSWORD_API_HOST=api01.opticable.ca
```

Caddy exposes the stack at:

- `https://api01.opticable.ca/`
- `https://api01.opticable.ca/docs`
- `https://api01.opticable.ca/openapi.json`
- `https://api01.opticable.ca/v1/system/health`
- `https://api01.opticable.ca/v1/system/catalog`
- `https://api01.opticable.ca/v1/workflows/site-and-password`
- `https://api01.opticable.ca/v1/workflows/site-and-password/jobs/{job_id}`
- `https://api01.opticable.ca/v1/integrations/zoho/oauth/start`
- `https://api01.opticable.ca/v1/integrations/zoho/oauth/status`
- `https://api01.opticable.ca/pdf/health`
- `https://api01.opticable.ca/omada/api/health`

## Detailed: How It Works

### 1. Zoho CRM Trigger

Zoho CRM runs the Deluge function in:

- `docs/zoho-deluge-service-contract-signed.dg`

The function is meant to run when a CRM `Services` record has a non-empty:

- `Service_Contract_Signed_Date`

The current workflow tracking fields on `Services` are:

- `Workflow_API_Job_ID`
- `Workflow_API_Last_Error`

The function fetches the Service record, its linked Service Location, and the Service Location WorkDrive folder ID. The folder ID must come from the Service Location only:

- Service Location field: `WorkDrive_Folder_ID`

If that folder is missing, the workflow stops because the earlier Service Location creation automation failed.

### 2. Workflow API

The Deluge function posts to:

- `POST /v1/workflows/site-and-password`

The workflow API normalizes the payload, creates a job ID, and starts a background workflow. It does not do PDF rendering or Omada browser automation itself. It orchestrates the two lower services.

Main behavior:

- validates payload
- generates normalized unit/SSID/password records
- calls the PDF service first for `pdf_only` and `pdf_and_site`
- writes `omada-plan.yaml`
- uploads controller artifacts to WorkDrive under `Document/Controller`
- calls the Omada service for `site_only` and `pdf_and_site`
- stores workflow job JSON under `/var/lib/opticable-workflow-api/output/jobs`

### 3. Password/PDF Service

The PDF service receives generated or predefined WiFi credential records.

For generated credentials:

- input `Units`: raw values such as `101,102,101a`
- output `SSIDs`: generated final SSIDs
- output `Passwords`: generated passwords

The service creates:

- one PDF per unit
- merged PDF
- TXT export
- ZIP export
- YA export

Then it uploads them to WorkDrive:

```text
Service Location folder
  Document
    Passwords
      individual PDFs
      merged PDF
      TXT
      ZIP
      YA
```

It also updates the Zoho CRM Service record:

- `SSIDs`
- `Passwords`

### 4. Omada Service

The Omada service receives a YAML/JSON Omada plan from the workflow API.

It uses Playwright Chromium to sign into the TP-Link Omada cloud portal and apply:

- organization selection: default `Opticable`
- site create/update
- LAN/VLAN create/update
- WLAN group create/update
- SSID create/update

The service now detects expired Omada sessions and attempts automatic sign-in using:

- `OMADA_SITE_CREATOR_CLOUD_EMAIL`
- `OMADA_SITE_CREATOR_CLOUD_PASSWORD`

It reuses the persistent browser profile at:

- `/var/lib/opticable-omada-site/data/browser-profile`

That keeps a valid session between runs and reduces repeated login challenges.

### 5. WorkDrive Folder Rules

The workflow expects the Service Location root folder ID from CRM.

Below that folder, the VM creates missing folders as needed:

```text
Service Location folder
  Document
    Passwords
    Controller
```

Password/PDF files go to:

- `Document/Passwords`

Omada plan and live-site artifacts go to:

- `Document/Controller`

### 6. Zoho OAuth

The stack uses one shared Zoho OAuth credential file:

- `/var/lib/opticable-api-platform/shared/zoho-oauth.json`

To connect Zoho after install:

1. Set `ZOHO_OAUTH_CLIENT_ID` and `ZOHO_OAUTH_CLIENT_SECRET`.
2. Install/reinstall the VM.
3. Open:

```text
https://api01.opticable.ca/v1/integrations/zoho/oauth/start?api_key=YOUR_WORKFLOW_API_KEY
```

4. Approve access.
5. Check:

```text
https://api01.opticable.ca/v1/integrations/zoho/oauth/status
```

Do not commit OAuth tokens, API keys, `.env` files, or runtime snapshots.

## Installer Variables

Common variables:

- `SITE_AND_PASSWORD_API_HOST`
- `SITE_AND_PASSWORD_CREATOR_REPO_URL`
- `SITE_AND_PASSWORD_CREATOR_REPO_REF`
- `SITE_AND_PASSWORD_CREATOR_INSTALL_DIR`
- `PASSWORD_PDF_API_KEY`
- `OMADA_SITE_CREATOR_WEBHOOK_TOKEN`
- `SITE_AND_PASSWORD_WORKFLOW_API_KEY`
- `OMADA_ORGANIZATION_NAME`
- `OMADA_SITE_CREATOR_CLOUD_EMAIL`
- `OMADA_SITE_CREATOR_CLOUD_PASSWORD`
- `OMADA_SITE_CREATOR_DEVICE_USERNAME`
- `OMADA_SITE_CREATOR_DEVICE_PASSWORD`
- `ZOHO_OAUTH_CLIENT_ID`
- `ZOHO_OAUTH_CLIENT_SECRET`
- `ZOHO_OAUTH_REDIRECT_URI`
- `ZOHO_OAUTH_SCOPES`
- `ZOHO_OAUTH_CREDENTIALS_PATH`
- `PASSWORD_PDF_ZOHO_REGION`
- `AUTO_SWAP_ENABLED`
- `AUTO_SWAP_SIZE_GB`

## Service Commands

```bash
sudo systemctl status opticable-workflow-api --no-pager
sudo systemctl status opticable-password-pdf --no-pager
sudo systemctl status opticable-omada-site --no-pager
```

```bash
sudo journalctl -u opticable-workflow-api -f
sudo journalctl -u opticable-password-pdf -f
sudo journalctl -u opticable-omada-site -f
```

```bash
curl http://127.0.0.1:8100/v1/system/health
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:3210/api/health
```

## Repository Structure

```text
.
├── apps/
│   ├── workflow-api/
│   ├── password-pdf-service/
│   └── omada-site-service/
├── deploy/
├── docs/
├── scripts/
│   └── update.sh
├── install.sh
└── README.md
```

## Source Of Truth

- GitHub repo: `yboucher97/Opticable-Api-VM01`
- branch: `main`
- install command: `install.sh`
- update command: `scripts/update.sh`

Local production secrets live in `/etc/*.env` and `/var/lib/...`; they do not belong in Git.
