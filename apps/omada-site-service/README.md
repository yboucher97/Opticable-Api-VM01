# Omada Site Creator

`Omada Site Creator` is a local helper app for **Omada Essentials / Omada Cloud** environments where the official northbound API is not available for the current tenant tier.

It uses:

- a **persistent Playwright browser profile** so you log in once
- a **YAML or JSON plan file**
- a small **desktop GUI** where you sign in, upload the file, and press `Start`
- an optional **token-protected webhook endpoint** so another system can push a plan automatically
- optional **automatic TP-Link cloud login** for unattended Linux/server use

This is UI automation. It is not an official TP-Link integration, so selectors may need occasional tuning when the Omada UI changes.

## What You Upload

Upload a `yaml`, `yml`, or `json` file shaped like [`examples/plan.example.yaml`](./examples/plan.example.yaml).

Top-level structure:

```yaml
version: 1
controller:
  organizationName: Opticable
  baseUrl: https://use1-omada-cloud.tplinkcloud.com/
  browserChannel: msedge
  headless: false
  cloudAccount:
    email: your-tplink-email@example.com
    password: change-me-cloud-password
  deviceAccount:
    username: admin
    password: change-me-device-password

execution:
  stopOnError: true
  screenshots: true

sites:
  - name: Store-001
    region: Canada
    timezone: America/Toronto
    scenario: Office
    lans:
      - name: "10"
        vlanId: 10
    wlanGroups:
      - name: Store-Staff
        ssids:
          - name: Store-Staff
            security: wpa2_psk
            password: change-me
      - name: Store-Guest
        ssids:
          - name: Store-Guest
            security: wpa2_psk
            password: change-me-too
```

For site creation on Omada Essentials, the plan must include device-account credentials.
You can set them once under `controller.deviceAccount` and override per site with `sites[].deviceAccount` when needed.
For unattended server runs, you can also set `controller.cloudAccount` or use `OMADA_SITE_CREATOR_CLOUD_EMAIL` and `OMADA_SITE_CREATOR_CLOUD_PASSWORD` in the server environment so the runner can re-authenticate automatically when the saved TP-Link session expires.
For the LAN flow, Omada Site Creator uses `DHCP Server Device = None`, `VLAN Type = Single`, and uses the VLAN number as the LAN name when `lans[].name` is omitted.
If an SSID omits `vlanId`, the runner assigns VLANs in order from `sites[].lans`: first SSID gets the first LAN, next SSID gets the next LAN, and so on.

## Operator Flow

1. Build and launch the desktop app:

   ```powershell
   npm install
   npm run desktop
   ```

2. Click `Sign In to Omada`.
3. Log in to Omada in the opened browser window, then close that window.
4. Upload your plan file.
5. Click `Validate` first.
6. Click `Start`.

To keep the desktop app on a stable local port for webhook use, set:

```powershell
$env:OMADA_SITE_CREATOR_PORT = "3210"
```

To build a Windows `.exe`:

```powershell
npm run dist:win
```

The packaged Windows app is written to `release/Omada Site Creator-win32-x64/`, and the launcher is:

```text
release/Omada Site Creator-win32-x64/Omada Site Creator.exe
```

## CLI Shortcuts

Open login browser:

```powershell
npm run login
```

Dry-run the sample plan:

```powershell
npm run dry-run:example
```

Run the built server directly:

```powershell
npm run serve:dist
```

Apply the sample plan:

```powershell
npm run apply:example
```

Apply a specific plan file:

```powershell
npm run apply -- data/uploads/my-plan.yaml
```

Run the web-only version instead of the desktop wrapper:

```powershell
npm start
```

## Webhook Automation

You can run the local service and let Zoho Flow, your own app server, or any other webhook sender push plans directly into the runner.

Set a shared token first:

```powershell
$env:OMADA_SITE_CREATOR_WEBHOOK_TOKEN = "replace-with-a-long-random-secret"
```

Optional server settings:

```powershell
$env:OMADA_SITE_CREATOR_PORT = "3210"
$env:OMADA_SITE_CREATOR_HOST = "127.0.0.1"
```

Start the server:

```powershell
npm start
```

Accepted webhook endpoint:

```text
POST /api/webhooks/run
```

Authentication:

- `Authorization: Bearer <token>`
- or `X-Omada-Webhook-Token: <token>`

Accepted payload shapes:

1. Raw YAML or JSON body
2. JSON body with `planText`
3. JSON body with `plan`

Example: raw YAML body

```powershell
curl.exe -X POST "http://127.0.0.1:3210/api/webhooks/run" ^
  -H "Authorization: Bearer replace-with-a-long-random-secret" ^
  -H "Content-Type: text/yaml" ^
  -H "X-Plan-File-Name: auto-plan.yaml" ^
  --data-binary "@data/uploads/my-plan.yaml"
```

Example: JSON body with `plan`

```json
{
  "fileName": "auto-plan.json",
  "plan": {
    "version": 1,
    "controller": {
      "organizationName": "Opticable",
      "baseUrl": "https://use1-omada-cloud.tplinkcloud.com/",
      "browserChannel": "msedge",
      "headless": false
    },
    "execution": {
      "stopOnError": true,
      "screenshots": true,
      "dryRun": false
    },
    "sites": [
      {
        "name": "Webhook-Site-001",
        "lans": [],
        "wlanGroups": []
      }
    ]
  }
}
```

The webhook returns `202 Accepted` immediately and queues the job. Check job status here:

```text
GET /api/jobs/{jobId}
```

Returned job states are `queued`, `running`, `success`, or `failed`.

Important limitation:

- If you do not configure `controller.cloudAccount` or `OMADA_SITE_CREATOR_CLOUD_EMAIL` and `OMADA_SITE_CREATOR_CLOUD_PASSWORD`, the webhook run still depends on the saved Omada browser session.
- Site creation still needs `controller.deviceAccount` or `sites[].deviceAccount` inside the submitted plan.

## Linux VPS

For unattended Linux deployment, use:

- `browserChannel: chromium`
- `headless: true`
- `OMADA_SITE_CREATOR_CLOUD_EMAIL`
- `OMADA_SITE_CREATOR_CLOUD_PASSWORD`

Sample Linux plan:

- [`examples/plan.linux-vps.example.yaml`](./examples/plan.linux-vps.example.yaml)

Deployment assets:

- [`deploy/linux/install.sh`](./deploy/linux/install.sh)
- [`deploy/linux/omada-site-creator.service`](./deploy/linux/omada-site-creator.service)
- [`deploy/linux/omada-site-creator.env.example`](./deploy/linux/omada-site-creator.env.example)
- [`deploy/linux/omada-site-creator.caddy`](./deploy/linux/omada-site-creator.caddy)
- [`deploy/linux/README.md`](./deploy/linux/README.md)

The Linux installer is intended for Ubuntu VMs and installs the app as a `systemd` service that listens on localhost and can be reverse-proxied by Caddy.

## Same VM as Password_PDF_Generator

If you deploy this next to `Password_PDF_Generator`, keep them as separate localhost services and give each one its own hostname through Caddy:

- `wifi-api.example.com` -> Password PDF Generator
- `omada.example.com` -> Omada Site Creator

That is the cleanest way to run both on the same Linux VM.

## Repo Layout

```text
examples/
  plan.example.yaml
  plan.linux-vps.example.yaml
deploy/
  linux/
    install.sh
    omada-site-creator.caddy
    omada-site-creator.env.example
    omada-site-creator.service
    README.md
public/
  index.html
src/
  cli.ts
  desktop/
    main.ts
  server/
    app.ts
  server.ts
  config/
    load-plan.ts
    schema.ts
  omada/
    locators.ts
    portal.ts
    session.ts
  runtime/
    paths.ts
    report.ts
    run-plan.ts
data/
  browser-profile/
  reports/
  uploads/
```

## Notes

- The desktop build still works well on Windows with `msedge`, but Linux/server deployments should prefer the bundled `chromium` browser channel.
- The runner is built to be **idempotent where possible**. It first looks for existing sites, WLAN groups, and SSIDs before creating them.
- Site, LAN, WLAN group, and SSID creation all use authenticated Essentials controller endpoints now; the desktop browser session is only used to keep the tenant authenticated.
- On Linux without a desktop session, interactive login is not supported; use automatic TP-Link cloud login via environment variables or `controller.cloudAccount`.
- The verified SSID provisioning flow currently targets password-protected WPA2-Personal SSIDs.
- Reports and screenshots are written under `data/reports/`.
