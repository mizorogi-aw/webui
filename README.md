# Edge Computer Settings Web UI

This Web UI lets you configure the following items on the Edge Computer from a browser.

- Basic Settings tab
  - Hostname
  - IPv4 network settings
  - DHCP / Manual
  - WiFi: Enable/Disable and AP settings (shown only when WiFi NIC exists)
  - SNTP servers
  - Reboot button
- OPCUA Server tab
  - Operates on the server installed by `open62541lib/dist/ua_server_sample-<version>-installer.sh` (latest)
  - Reflect client certificates into `/opt/ua_server_sample/client_certs`
  - Update `/opt/ua_server_sample/format.csv`
  - Start / stop `ua_server_sample.service`
- App Settings tab
  - Upload client allowlist (client certificates)
  - Only `.der` files can be uploaded
  - 1 MB size limit per file
  - Up to 5 stored files
  - Delete uploaded files
  - Delete all uploaded files
  - Uploaded file list

## Requirements

- Ubuntu 24.04 / Debian / Raspberry Pi OS
- systemd
- netplan or dhcpcd

## Install

```bash
cd /home/pi/dev/webui
chmod +x scripts/*.sh
sudo ./scripts/install.sh
```

After installation:

- URL: `http://<Edge-Computer-IP>/`
- URL: `https://<Edge-Computer-IP>/` (self-signed certificate warning appears on first access)
- Service name: `field-iot-gateway-webui.service`
- Reverse proxy: `nginx` (80/443)
- Default login: `admin / password` (change after login)

## Login Authentication

- A browser-native login dialog (HTTP Basic Auth) appears before the page is shown.
- After that, the page is protected by a server-side session.
- Change username/password in the "Account Settings" tab.
- Current password input is not required.
- New password constraints: 3 to 128 characters, with no required character classes.

To reset authentication settings:

```bash
sudo ./scripts/reset-auth.sh
```

- Resets credentials to `admin / password`.
- On installed environments, you can also run `sudo /opt/field-iot-gateway-webui/scripts/reset-auth.sh`.

## Start, Stop, and Status

```bash
sudo systemctl status field-iot-gateway-webui.service
sudo systemctl restart field-iot-gateway-webui.service
sudo journalctl -u field-iot-gateway-webui.service -f
sudo systemctl status nginx
sudo nginx -t
```

## Install on Another Ubuntu 24.04 Host

Copy this whole folder, then run:

```bash
chmod +x scripts/*.sh
sudo ./scripts/install.sh
```

## Verification

### 1) Service connectivity

```bash
curl -fsS -u admin:password http://127.0.0.1/api/basic
curl -kfsS -u admin:password https://127.0.0.1/api/basic
curl -fsS -u admin:password http://127.0.0.1/api/opcua
```

### 2) Smoke test

```bash
sudo ./scripts/smoke-test.sh http://127.0.0.1 admin password
```

This script verifies API connectivity and the authentication flow (unauthenticated access to `/` returns 401).

## If External Access Fails

```bash
sudo ss -ltnp | egrep ':80|:443|:18080'
sudo systemctl status field-iot-gateway-webui.service nginx
sudo ufw status
```

- If ports 80/443 are not listening: rerun `sudo ./scripts/install.sh`
- If UFW is enabled: `sudo ufw allow 80/tcp && sudo ufw allow 443/tcp`

## Uninstall

```bash
sudo ./scripts/uninstall.sh
```

## Notes

- Applying basic settings runs `hostnamectl`, applies network via netplan or dhcpcd, and restarts `systemd-timesyncd`.
- WiFi AP settings are shown only when a WiFi NIC is detected.
- WiFi AP apply uses NetworkManager (`nmcli`) when available, otherwise `hostapd` fallback.
- SSH may be temporarily disconnected when changing network settings.
- Currently, only IPv4 is supported.
- The OPCUA Server tab assumes the installer deployed the server to `/opt/ua_server_sample` and registered `ua_server_sample.service`.
- Upload destination is managed internally. It is not shown on the screen, but can be checked via `upload_dir` in `/etc/field-iot-gateway-webui/config.json` or `GET /api/app`.
- Because uploaded files are treated as a client allowlist, only `.der` extensions are accepted.
- Upload size limit is 1 MB.
- Maximum stored upload files is 5.
- Overwriting files with the same name is not allowed. Delete the existing file before re-uploading.

## OPCUA Compatibility Note (Anonymous Connection)

- Some OPCUA server variants parse `server.allowAnonymous` in `config.csv` with different token styles (`1/0`, `ON/OFF`, or `true/false`).
- This Web UI preserves the existing token style found in `config.csv` when saving settings, to avoid compatibility regressions after restart.
- If Anonymous Connection behavior seems wrong after Save + Restart, verify both:
  - the value written in `/opt/ua_server_sample/config/config.csv`
  - actual anonymous client login result against `opc.tcp://<device-ip>:<port>`
