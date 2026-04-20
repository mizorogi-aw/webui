#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/field-iot-gateway-webui"
SERVICE_NAME="field-iot-gateway-webui.service"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root: sudo ./scripts/uninstall.sh"
  exit 1
fi

systemctl disable --now "$SERVICE_NAME" || true
rm -f "/etc/systemd/system/$SERVICE_NAME"
systemctl daemon-reload

rm -f /etc/nginx/sites-enabled/field-iot-gateway-webui.conf
rm -f /etc/nginx/sites-available/field-iot-gateway-webui.conf
systemctl restart nginx || true

rm -rf "$APP_DIR"

echo "Uninstalled $SERVICE_NAME"
