#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="/etc/field-iot-gateway-webui/config.json"
DEFAULT_USERNAME="admin"
DEFAULT_PASSWORD_HASH='scrypt:32768:8:1$DtR8LXlWQETIJPNU$43aed9e52d15c8339bd450ff202e593c2f16899fba1b91959dc6fe457ab4cdff9fda5f935ca9cc1f74ce988f2808b0fef4a9ba48f5dac5c826fc8c8e9e81b0ec'

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root: sudo ./scripts/reset-auth.sh"
  exit 1
fi

mkdir -p "$(dirname "$CONFIG_PATH")"

python3 - <<'PY'
import json
from pathlib import Path

config_path = Path("/etc/field-iot-gateway-webui/config.json")
legacy_config_path = Path("/etc/" + "nano" + "pi-webui/config.json")
default_password_hash = (
    "scrypt:32768:8:1$DtR8LXlWQETIJPNU$43aed9e52d15c8339bd450ff202e593c2f16899f"
    "ba1b91959dc6fe457ab4cdff9fda5f935ca9cc1f74ce988f2808b0fef4a9ba48f5dac5c826"
    "fc8c8e9e81b0ec"
)

if config_path.exists():
    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
elif legacy_config_path.exists():
    with legacy_config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
else:
    data = {}

data.setdefault("upload_dir", "/var/lib/field-iot-gateway-webui/uploads")
data.setdefault("custom_pages", {})
data["auth"] = {
    "enabled": True,
    "username": "admin",
    "password_hash": default_password_hash,
}

with config_path.open("w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY

echo "Authentication reset complete"
echo "Login: ${DEFAULT_USERNAME} / password"
