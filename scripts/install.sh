#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/field-iot-gateway-webui"
LEGACY_COMPAT_PREFIX="nano""pi-webui"
LEGACY_APP_DIR="/opt/${LEGACY_COMPAT_PREFIX}"
SERVICE_NAME="field-iot-gateway-webui.service"
LEGACY_SERVICE_NAME="${LEGACY_COMPAT_PREFIX}.service"
CONFIG_DIR="/etc/field-iot-gateway-webui"
LEGACY_CONFIG_DIR="/etc/${LEGACY_COMPAT_PREFIX}"
DATA_DIR="/var/lib/field-iot-gateway-webui"
LEGACY_DATA_DIR="/var/lib/${LEGACY_COMPAT_PREFIX}"
NGINX_CONF_NAME="field-iot-gateway-webui.conf"
LEGACY_NGINX_CONF_NAME="${LEGACY_COMPAT_PREFIX}.conf"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 設定ファイルの上書きポリシー
# 既定では運用環境の編集内容を保持する
CONFIG_MODE="${CONFIG_MODE:-preserve}"

usage() {
  cat <<EOF
Usage: sudo ./scripts/install.sh [--preserve-config|--overwrite-config|--config-mode preserve|overwrite]

  --preserve-config      設定を保持する（既定）
  --overwrite-config     設定を上書きする（上書き前に bak を作成）
  --config-mode MODE     MODE は preserve または overwrite
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --preserve-config)
      CONFIG_MODE="preserve"
      shift
      ;;
    --overwrite-config)
      CONFIG_MODE="overwrite"
      shift
      ;;
    --config-mode)
      shift
      [[ $# -gt 0 ]] || {
        echo "--config-mode の値が指定されていません" >&2
        exit 1
      }
      CONFIG_MODE="$1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ "$CONFIG_MODE" != "preserve" && "$CONFIG_MODE" != "overwrite" ]]; then
  echo "CONFIG_MODE は preserve または overwrite を指定してください" >&2
  exit 1
fi

backup_if_exists() {
  local path="$1"
  if [[ -f "$path" ]]; then
    local ts
    ts="$(date +%Y%m%d_%H%M%S)"
    cp -a "$path" "${path}.bak_${ts}"
    echo "[INFO] backup created: $(basename "$path").bak_${ts}"
  fi
}

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root: sudo ./scripts/install.sh"
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip netplan.io rsync nginx openssl hostapd iw

mkdir -p "$APP_DIR"
rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  "$SRC_DIR"/ "$APP_DIR"/

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [[ -d "$LEGACY_CONFIG_DIR" && ! -d "$CONFIG_DIR" ]]; then
  mv "$LEGACY_CONFIG_DIR" "$CONFIG_DIR"
fi
if [[ -d "$LEGACY_DATA_DIR" && ! -d "$DATA_DIR" ]]; then
  mv "$LEGACY_DATA_DIR" "$DATA_DIR"
fi

mkdir -p "$CONFIG_DIR"
if [[ "$CONFIG_MODE" == "overwrite" ]]; then
  backup_if_exists "$CONFIG_DIR/config.json"
fi
if [[ "$CONFIG_MODE" == "overwrite" || ! -f "$CONFIG_DIR/config.json" ]]; then
  cat <<'EOF' >"$CONFIG_DIR/config.json"
{
  "upload_dir": "/var/lib/field-iot-gateway-webui/uploads",
  "custom_pages": {},
  "auth": {
    "enabled": true,
    "username": "admin",
    "password_hash": "scrypt:32768:8:1$DtR8LXlWQETIJPNU$43aed9e52d15c8339bd450ff202e593c2f16899fba1b91959dc6fe457ab4cdff9fda5f935ca9cc1f74ce988f2808b0fef4a9ba48f5dac5c826fc8c8e9e81b0ec"
  }
}
EOF
  if [[ "$CONFIG_MODE" == "overwrite" ]]; then
    echo "[INFO] config.json overwritten (CONFIG_MODE=overwrite)"
  else
    echo "[INFO] config.json created"
  fi
else
  echo "[INFO] keep existing config.json (CONFIG_MODE=preserve)"
fi

mkdir -p "$DATA_DIR/uploads"

mkdir -p "$CONFIG_DIR/tls"
if [[ -f "$LEGACY_CONFIG_DIR/tls/server.crt" && ! -f "$CONFIG_DIR/tls/server.crt" ]]; then
  install -m 600 "$LEGACY_CONFIG_DIR/tls/server.crt" "$CONFIG_DIR/tls/server.crt"
fi
if [[ -f "$LEGACY_CONFIG_DIR/tls/server.key" && ! -f "$CONFIG_DIR/tls/server.key" ]]; then
  install -m 600 "$LEGACY_CONFIG_DIR/tls/server.key" "$CONFIG_DIR/tls/server.key"
fi
if [[ "$CONFIG_MODE" == "overwrite" ]]; then
  backup_if_exists "$CONFIG_DIR/tls/server.crt"
  backup_if_exists "$CONFIG_DIR/tls/server.key"
  rm -f "$CONFIG_DIR/tls/server.crt" "$CONFIG_DIR/tls/server.key"
fi
if [[ ! -f "$CONFIG_DIR/tls/server.crt" || ! -f "$CONFIG_DIR/tls/server.key" ]]; then
  PRIMARY_IP="$(hostname -I | awk '{print $1}')"
  if [[ -z "$PRIMARY_IP" ]]; then
    PRIMARY_IP="127.0.0.1"
  fi

  openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
    -keyout "$CONFIG_DIR/tls/server.key" \
    -out "$CONFIG_DIR/tls/server.crt" \
    -subj "/CN=$(hostname)" \
    -addext "subjectAltName=IP:127.0.0.1,IP:${PRIMARY_IP},DNS:$(hostname)"
  if [[ "$CONFIG_MODE" == "overwrite" ]]; then
    echo "[INFO] TLS cert/key regenerated (CONFIG_MODE=overwrite)"
  else
    echo "[INFO] TLS cert/key generated"
  fi
else
  echo "[INFO] keep existing TLS cert/key (CONFIG_MODE=preserve)"
fi

rm -f "/etc/nginx/sites-enabled/$LEGACY_NGINX_CONF_NAME" "/etc/nginx/sites-available/$LEGACY_NGINX_CONF_NAME"
install -m 644 "$APP_DIR/nginx/$NGINX_CONF_NAME" "/etc/nginx/sites-available/$NGINX_CONF_NAME"
ln -sfn "/etc/nginx/sites-available/$NGINX_CONF_NAME" "/etc/nginx/sites-enabled/$NGINX_CONF_NAME"
rm -f /etc/nginx/sites-enabled/default
nginx -t

if systemctl list-unit-files | grep -q "^${LEGACY_SERVICE_NAME}"; then
  systemctl disable --now "$LEGACY_SERVICE_NAME" || true
  rm -f "/etc/systemd/system/$LEGACY_SERVICE_NAME"
fi

install -m 644 "$APP_DIR/systemd/$SERVICE_NAME" "/etc/systemd/system/$SERVICE_NAME"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
systemctl enable --now nginx
systemctl restart nginx

echo "Field IoT Gateway Nano install complete"
echo "Open: http://<this-device-ip>/"
echo "Open: https://<this-device-ip>/"
echo "Default login: admin / password (change it immediately in Account Settings)"
echo "Auth reset: sudo /opt/field-iot-gateway-webui/scripts/reset-auth.sh"
