# WiFi PDF VM Deployment On ESXi

This is the exact production pattern recommended for this project:

- ESXi VM on your LAN
- Ubuntu Server 24.04 LTS guest
- static IP `10.2.0.10/24`
- gateway `10.2.0.1`
- router forwards TCP `80` and `443` to the VM
- Caddy terminates HTTPS and reverse-proxies to the FastAPI service on `127.0.0.1:8000`

## 1. Create The VM In ESXi

Use these VM settings:

- Name: `wifi-pdf-prod-01`
- Guest OS family: `Linux`
- Guest OS version: `Ubuntu Linux (64-bit)`
- Firmware: `EFI`
- vCPU: `2`
- RAM: `4 GB`
- Disk: `40 GB`, thin provisioned
- SCSI controller: `VMware Paravirtual`
- NIC: `VMXNET3`
- Attach the Ubuntu Server ISO and connect it at power on

## 2. Install Ubuntu Server

During install:

- choose `Ubuntu Server`
- set hostname to `wifi-pdf-prod-01`
- create your admin user
- install `OpenSSH server`
- finish install and reboot

## 3. Configure The Static IP

First find the NIC name:

```bash
ip link
```

It is often `ens160` on ESXi. Replace that name below if your VM uses something else.

Create `/etc/netplan/01-static.yaml`:

```yaml
network:
  version: 2
  ethernets:
    ens160:
      dhcp4: false
      addresses:
        - 10.2.0.10/24
      routes:
        - to: default
          via: 10.2.0.1
      nameservers:
        addresses:
          - 1.1.1.1
          - 8.8.8.8
```

Apply it:

```bash
sudo netplan generate
sudo netplan apply
```

Verify it:

```bash
ip addr
ip route
ping -c 4 10.2.0.1
ping -c 4 8.8.8.8
```

## 4. Update Ubuntu And Install Packages

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git open-vm-tools ufw caddy
sudo systemctl enable --now open-vm-tools
```

## 5. Configure The Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

Do not open `8000` to the network. Caddy should be the only public listener.

## 6. Create The App User And Directories

```bash
sudo useradd --system --create-home --home /var/lib/wifi-pdf --shell /usr/sbin/nologin wifiapp
sudo mkdir -p /opt/wifi-pdf
sudo chown -R wifiapp:wifiapp /opt/wifi-pdf /var/lib/wifi-pdf
```

## 7. Copy The Project To The VM

Copy these paths into `/opt/wifi-pdf`:

- `wifi_pdf/`
- `config/wifi_pdf/`
- `input/wifi_pdf/`
- `assets/wifi_pdf/`
- `assets/fonts/` if you have custom fonts
- `requirements.txt`

Then create the virtual environment:

```bash
cd /opt/wifi-pdf
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
sudo chown -R wifiapp:wifiapp /opt/wifi-pdf
```

## 8. Create The Environment File

Create `/etc/wifi-pdf.env`:

```bash
sudo nano /etc/wifi-pdf.env
```

Use:

```text
WIFI_PDF_API_KEY=replace-with-long-random-secret
ZOHO_OAUTH_CREDENTIALS_PATH=/etc/wifi-pdf/zoho-oauth.json
# Optional fallback if the webhook does not send workdrive_folder_id
# ZOHO_WORKDRIVE_PARENT_FOLDER_ID=default-folder-id
```

Lock it down:

```bash
sudo chmod 600 /etc/wifi-pdf.env
sudo chown root:root /etc/wifi-pdf.env
```

## 9. Enable WorkDrive Upload In Config

Edit `/opt/wifi-pdf/config/wifi_pdf/brand_settings.json` and set:

```json
"workdrive": {
  "enabled": true,
  "api_base_url": "https://www.zohoapis.com/workdrive/api/v1",
  "accounts_base_url": "https://accounts.zoho.com/oauth/v2/token",
  "parent_folder_id": null,
  "cleanup_local_after_upload": true,
  "upload_individual_pdfs": true,
  "upload_merged_pdf": true,
  "upload_field_name": "content"
}
```

With this configuration, the batch folder is deleted only after all uploads succeed.

## 10. Create The Systemd Service

Create `/etc/systemd/system/wifi-pdf.service`:

```ini
[Unit]
Description=WiFi PDF Generator API
After=network.target

[Service]
User=wifiapp
Group=wifiapp
WorkingDirectory=/opt/wifi-pdf
EnvironmentFile=/etc/wifi-pdf.env
Environment="PATH=/opt/wifi-pdf/.venv/bin"
ExecStart=/opt/wifi-pdf/.venv/bin/uvicorn wifi_pdf.api:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wifi-pdf
sudo systemctl status wifi-pdf
curl http://127.0.0.1:8000/health
```

## 11. Configure Caddy

Create `/etc/caddy/Caddyfile`:

```caddy
wifi-api.yourdomain.com {
    reverse_proxy 127.0.0.1:8000
}
```

Reload Caddy:

```bash
sudo systemctl reload caddy
sudo systemctl status caddy
```

## 12. Router And DNS

Set:

- DNS A record: `wifi-api.yourdomain.com` -> your public IP
- Port forward TCP `80` -> `10.2.0.10:80`
- Port forward TCP `443` -> `10.2.0.10:443`

Do not forward:

- `8000`
- ESXi management ports
- `22` unless you restrict source IPs or use a VPN

## 13. Test The API

From the VM:

```bash
curl http://127.0.0.1:8000/health
```

Local webhook test:

```bash
curl -X POST http://127.0.0.1:8000/webhooks/zoho/wifi-pdfs \
  -H "Content-Type: application/json" \
  -H "X-API-Key: replace-with-long-random-secret" \
  --data @input/wifi_pdf/example_records.json
```

Public HTTPS test after DNS and NAT:

```bash
curl https://wifi-api.yourdomain.com/health
```

## 14. Zoho Payload Shape

Recommended payload:

```json
{
  "building_name": "101-103 Rue Yanick",
  "workdrive_folder_id": "abc123workdrivefolderid",
  "template_name": "Opticable Template Basic 01",
  "records": [
    {
      "ssid": "app101_jw",
      "password": "4430jw6355$@",
      "unit_label": "Appartement 101",
      "auth_type": "WPA"
    }
  ]
}
```

Folder id resolution order:

1. `workdrive_folder_id` from the webhook JSON
2. `ZOHO_WORKDRIVE_PARENT_FOLDER_ID` from `/etc/wifi-pdf.env`
3. `workdrive.parent_folder_id` in config

## 15. Operational Notes

- Keep custom Unicode fonts in `assets/fonts/` if you expect uncommon password characters.
- Do not store Zoho secrets in Python files.
- Use ESXi snapshots only short-term during rollout.
- Back up the VM separately; snapshots are not backups.
- If a WorkDrive upload fails, local files remain on disk by design.
