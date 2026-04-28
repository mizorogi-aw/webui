import csv
import hashlib
import io
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, session, redirect, make_response
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

APP_ROOT = Path(__file__).resolve().parent.parent
app = Flask(
    __name__,
    template_folder=str(APP_ROOT / "templates"),
    static_folder=str(APP_ROOT / "static"),
    static_url_path="/static",
)

DEFAULT_INTERFACE = "eth0"
APP_CONFIG_DIR = Path("/etc/field-iot-gateway-webui")
LEGACY_APP_CONFIG_DIR = Path("/etc/" + "nano" + "pi-webui")
APP_CONFIG_PATH = APP_CONFIG_DIR / "config.json"
LEGACY_APP_CONFIG_PATH = LEGACY_APP_CONFIG_DIR / "config.json"
SECRET_KEY_PATH = APP_CONFIG_DIR / "secret_key"
LEGACY_SECRET_KEY_PATH = LEGACY_APP_CONFIG_DIR / "secret_key"
TIMESYNCD_CONF_PATH = Path("/etc/systemd/timesyncd.conf")
NETPLAN_PATH = Path("/etc/netplan/99-webui-config.yaml")
DHCPCD_CONF_PATH = Path("/etc/dhcpcd.conf")
INTERFACES_PATH = Path("/etc/network/interfaces")
RESOLV_CONF_PATH = Path("/etc/resolv.conf")
WEBUI_MANAGED_BLOCK_BEGIN = "# BEGIN field-iot-gateway-webui"
WEBUI_MANAGED_BLOCK_END = "# END field-iot-gateway-webui"
DEFAULT_UPLOAD_DIR = Path("/var/lib/field-iot-gateway-webui/uploads")
MAX_UPLOAD_SIZE_BYTES = 1024 * 1024
MAX_UPLOAD_FILES = 5
ALLOWED_UPLOAD_EXTENSION = ".der"
ALLOWED_ADDRESS_SPACE_EXTENSION = ".csv"
ADDRESS_SPACE_DEFINITION_FILENAME = "address-space-definition.csv"
OPCUA_INSTALL_ROOT = Path("/opt/ua_server_sample")
OPCUA_SERVER_BIN = OPCUA_INSTALL_ROOT / "bin" / "ua_server_sample"
OPCUA_CLIENT_CERT_DIR = OPCUA_INSTALL_ROOT / "client_certs"
OPCUA_FORMAT_FILE = OPCUA_INSTALL_ROOT / "config" / "format.csv"
OPCUA_CONFIG_FILE = OPCUA_INSTALL_ROOT / "config" / "config.csv"
MODBUS_TCP_FILE = OPCUA_INSTALL_ROOT / "config" / "modbustcp.csv"
OPCUA_SERVICE_NAME = "ua_server_sample.service"
OPCUA_MAX_CLIENT_CERTS = 5
OPCUA_MAX_USERS = 5
OPCUA_MAX_SESSIONS_LIMIT = 16
OPCUA_PRODUCT_NAME_PATTERN = re.compile(r"^[\x20-\x7E]{1,64}$")
CUSTOM_PAGE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{2,32}$")
PASSWORD_PATTERN = re.compile(r"^.{3,128}$")
AUTH_REALM = "Field IoT Gateway Nano"
FORCE_REAUTH_COOKIE = "force_reauth"
MODBUS_CUSTOM_PAGE_ID = "modbus-tcp"
MODBUS_MAX_SLAVES = 5
MODBUS_ALLOWED_TYPES = {"holding"}

# format.csv column indices
_FC_NODE_CLASS = 0
_FC_BROWSE_PATH = 1
_FC_NODE_ID = 2
_FC_REFERENCE_TYPE_ID = 3
_FC_BROWSE_NAME = 4
_FC_TYPE_DEFINITION_ID = 5
_FC_HAS_MODELLING_RULE = 6
_FC_DISPLAY_NAME = 9
_FC_DESCRIPTION = 10
_FC_WRITE_MASK = 11
_FC_OBJECT_EVENT_NOTIFIER = 12
_FC_DATA_TYPE = 14
_FC_VALUE_RANK = 15
_FC_ARRAY_DIMENSIONS_SIZE = 16
_FC_VALUE = 17
_FC_ACCESS_LEVEL = 18
_FC_MIN_SAMPLING_INTERVAL = 19
_FC_HISTORIZING = 20
_FC_CYCLIC = 24
_FC_PARAM1 = 25
_FC_PARAM2 = 26
_FC_TOTAL_COLS = 27

_FC_REF_TYPE_DEFAULT = "Type/ReferenceTypes/References/HierarchicalReferences/Organizes"
_FC_OBJECT_TYPE_DEF = "Type/ObjectTypes/BaseObjectType/FolderType"
_FC_VARIABLE_TYPE_DEF = "Type/VariableTypes/BaseVariableType/BaseDataVariableType"
_FC_HAS_MODELLING_RULE_DEFAULT = "Mandatory"
_FC_NODE_ID_START = 10001

# meta row: namespace label columns start at index 4 (ns=0 → index 4, ns=1 → index 5, ...)
_FC_NAMESPACE_LABELS_META_START = 4
_FC_NAMESPACE_MAX = 5

# DataType short name <-> CSV path mapping
_FC_DATATYPE_SHORT_TO_PATH: dict[str, str] = {
    "Boolean": "Type/DataTypes/BaseDataType/Boolean",
    "INT16": "Type/DataTypes/BaseDataType/Number/Integer/Int16",
    "UINT16": "Type/DataTypes/BaseDataType/Number/UInteger/UInt16",
    "INT32": "Type/DataTypes/BaseDataType/Number/Integer/Int32",
    "UINT32": "Type/DataTypes/BaseDataType/Number/UInteger/UInt32",
    "FLOAT": "Type/DataTypes/BaseDataType/Number/Float",
    "INT64": "Type/DataTypes/BaseDataType/Number/Integer/Int64",
    "UINT64": "Type/DataTypes/BaseDataType/Number/UInteger/UInt64",
    "DOUBLE": "Type/DataTypes/BaseDataType/Number/Double",
    "String": "Type/DataTypes/BaseDataType/String",
}
_FC_DATATYPE_PATH_TO_SHORT: dict[str, str] = {v: k for k, v in _FC_DATATYPE_SHORT_TO_PATH.items()}
DEFAULT_PASSWORD_HASH = (
    "scrypt:32768:8:1$DtR8LXlWQETIJPNU$43aed9e52d15c8339bd450ff202e593c2f16899f"
    "ba1b91959dc6fe457ab4cdff9fda5f935ca9cc1f74ce988f2808b0fef4a9ba48f5dac5c826"
    "fc8c8e9e81b0ec"
)


def load_secret_key() -> str:
    env_key = os.environ.get("FIELD_IOT_GATEWAY_WEBUI_SECRET") or os.environ.get("NANO" "PI_WEBUI_SECRET")
    if env_key:
        return env_key
    try:
        if SECRET_KEY_PATH.exists():
            return SECRET_KEY_PATH.read_text(encoding="utf-8").strip()
        if LEGACY_SECRET_KEY_PATH.exists():
            return LEGACY_SECRET_KEY_PATH.read_text(encoding="utf-8").strip()
        SECRET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        new_key = secrets.token_urlsafe(48)
        SECRET_KEY_PATH.write_text(new_key, encoding="utf-8")
        os.chmod(SECRET_KEY_PATH, 0o600)
        return new_key
    except Exception:
        return "field-iot-gateway-webui-dev-secret"


def get_existing_config_path() -> Path:
    if APP_CONFIG_PATH.exists():
        return APP_CONFIG_PATH
    if LEGACY_APP_CONFIG_PATH.exists():
        return LEGACY_APP_CONFIG_PATH
    return APP_CONFIG_PATH


app.secret_key = load_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE_BYTES


def auth_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Check session first (common case for browser)
        if session.get("authenticated", False):
            return func(*args, **kwargs)
        # Fall back to Basic Auth (for curl/scripting)
        ok, _username = verify_basic_auth()
        if not ok:
            return jsonify({"error": "authentication required"}), 401
        return func(*args, **kwargs)

    return wrapper


def build_auth_challenge_response(error_message: str):
    # HTML with meta redirect to /logout + Basic Auth challenge
    html_body = """
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8" />
        <meta http-equiv="refresh" content="0; url=/logout" />
        <title>Authentication Required</title>
        <style>
            body { font-family: sans-serif; text-align: center; padding: 50px; }
            p { color: #666; }
            a { color: #667eea; text-decoration: none; }
        </style>
    </head>
    <body>
        <h2>Authentication Required</h2>
        <p>Redirecting to the logout page...</p>
        <p><a href="/logout">Click here</a></p>
    </body>
    </html>
    """
    response = app.response_class(
        response=html_body,
        status=401,
        mimetype="text/html"
    )
    response.headers["WWW-Authenticate"] = f'Basic realm="{AUTH_REALM}"'
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


def verify_basic_auth() -> tuple[bool, str]:
    config = load_app_config()
    auth = config.get("auth", {})

    if not auth.get("enabled", True):
        return True, auth.get("username", "admin")

    credentials = request.authorization
    if not credentials:
        return False, ""

    if str(credentials.type or "").lower() != "basic":
        return False, ""

    username = str(credentials.username or "").strip()
    password = str(credentials.password or "")
    stored_username = str(auth.get("username", ""))
    stored_hash = str(auth.get("password_hash", ""))

    if normalize_username(username) != normalize_username(stored_username):
        return False, ""

    if not check_password_hash(stored_hash, password):
        return False, ""

    return True, stored_username


def normalize_username(value: str) -> str:
    return value.strip().casefold()


def run_command(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def load_app_config() -> dict:
    config_path = get_existing_config_path()
    if not config_path.exists():
        return {
            "upload_dir": str(DEFAULT_UPLOAD_DIR),
            "custom_pages": {},
            "auth": {
                "enabled": True,
                "username": "admin",
                "password_hash": DEFAULT_PASSWORD_HASH,
            },
        }

    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "upload_dir" not in data:
        data["upload_dir"] = str(DEFAULT_UPLOAD_DIR)
    if "custom_pages" not in data or not isinstance(data["custom_pages"], dict):
        data["custom_pages"] = {}
    if "auth" not in data or not isinstance(data["auth"], dict):
        data["auth"] = {
            "enabled": True,
            "username": "admin",
            "password_hash": DEFAULT_PASSWORD_HASH,
        }
    else:
        auth = data["auth"]
        if "enabled" not in auth:
            auth["enabled"] = True
        if "username" not in auth or not auth["username"]:
            auth["username"] = "admin"
        if "password_hash" not in auth or not auth["password_hash"]:
            auth["password_hash"] = DEFAULT_PASSWORD_HASH

    return data


def save_app_config(config: dict) -> None:
    APP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with APP_CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def get_upload_dir(config: dict | None = None) -> Path:
    data = config or load_app_config()
    raw_path = str(data.get("upload_dir", str(DEFAULT_UPLOAD_DIR))).strip()
    return Path(raw_path or str(DEFAULT_UPLOAD_DIR))


def validate_filename_for_extension(filename: str, extension: str) -> str:
    normalized = secure_filename(filename)
    if not normalized or normalized != filename:
        raise ValueError("invalid filename")
    if Path(normalized).suffix.lower() != extension:
        raise ValueError(f"file extension must be {extension}")
    return normalized


def validate_uploaded_filename(filename: str) -> str:
    return validate_filename_for_extension(filename, ALLOWED_UPLOAD_EXTENSION)


def validate_address_space_filename(filename: str) -> str:
    return validate_filename_for_extension(filename, ALLOWED_ADDRESS_SPACE_EXTENSION)


def serialize_uploaded_file(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
    }


def list_upload_file_paths(upload_dir: Path, extension: str | None = None) -> list[Path]:
    files = sorted(path for path in upload_dir.glob("*") if path.is_file())
    if extension is None:
        return files
    return [path for path in files if path.suffix.lower() == extension]


def get_address_space_file_path(upload_dir: Path) -> Path:
    return upload_dir / ADDRESS_SPACE_DEFINITION_FILENAME


def parse_systemctl_properties(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def get_opcua_service_status() -> dict:
    installed = OPCUA_SERVER_BIN.is_file()
    status = {
        "service_name": OPCUA_SERVICE_NAME,
        "installed": installed,
        "systemctl_available": shutil.which("systemctl") is not None,
        "active": False,
        "active_state": "unknown",
        "sub_state": "unknown",
        "enabled": False,
        "unit_file_state": "unknown",
    }

    if not status["systemctl_available"]:
        return status

    result = subprocess.run(
        [
            "systemctl",
            "show",
            OPCUA_SERVICE_NAME,
            "--property=LoadState,ActiveState,SubState,UnitFileState",
            "--no-page",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    props = parse_systemctl_properties(result.stdout)
    load_state = props.get("LoadState", "unknown")
    active_state = props.get("ActiveState", "unknown")
    sub_state = props.get("SubState", "unknown")
    unit_file_state = props.get("UnitFileState", "unknown")

    if load_state == "not-found":
        active_state = "not-found"
        sub_state = "not-found"
        unit_file_state = "not-found"

    status["active_state"] = active_state
    status["sub_state"] = sub_state
    status["unit_file_state"] = unit_file_state
    status["active"] = active_state == "active"
    status["enabled"] = unit_file_state == "enabled"
    return status


def ensure_opcua_installed() -> tuple[bool, str]:
    if not OPCUA_SERVER_BIN.is_file():
        return False, f"OPCUA server is not installed: {str(OPCUA_SERVER_BIN)}"
    return True, ""


# ---------------------------------------------------------------------------
# format.csv grid helpers
# ---------------------------------------------------------------------------

def _pad_csv_row(row: list[str], length: int = _FC_TOTAL_COLS) -> list[str]:
    if len(row) < length:
        return row + [""] * (length - len(row))
    return list(row[:length])


def parse_format_csv(text: str) -> dict:
    """Parse format.csv text into meta lines, header row, and data rows.

    Also extracts namespace labels from the meta row (positions 4+).
    """
    reader = csv.reader(io.StringIO(text))
    all_rows = list(reader)
    # Skip trailing empty rows
    while all_rows and all(c.strip() == "" for c in all_rows[-1]):
        all_rows.pop()
    if len(all_rows) < 2:
        raise ValueError("format.csv must have at least 2 rows (meta + header)")
    meta_lines = [all_rows[0]]
    header_row = all_rows[1]
    data_rows = [_pad_csv_row(r) for r in all_rows[2:] if any(c.strip() for c in r)]
    # Extract namespace labels from meta row (index 4 onwards)
    meta_row = all_rows[0]
    ns_labels = []
    for i in range(_FC_NAMESPACE_LABELS_META_START, _FC_NAMESPACE_LABELS_META_START + _FC_NAMESPACE_MAX):
        label = meta_row[i].strip() if i < len(meta_row) else ""
        ns_labels.append(label)
    # Trim trailing empty labels
    while ns_labels and not ns_labels[-1]:
        ns_labels.pop()
    return {"meta": meta_lines, "header": header_row, "data": data_rows, "ns_labels": ns_labels}


def format_csv_serialize(parsed: dict) -> str:
    """Serialize parsed format.csv back to CSV text, writing ns_labels into meta row."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    # Rebuild meta row with updated ns_labels
    meta_row = list(parsed["meta"][0]) if parsed["meta"] else []
    ns_labels: list[str] = parsed.get("ns_labels", [])
    # Ensure meta row is long enough
    needed = _FC_NAMESPACE_LABELS_META_START + _FC_NAMESPACE_MAX
    while len(meta_row) < needed:
        meta_row.append("")
    # Write ns labels at positions 4+
    for i, label in enumerate(ns_labels[:_FC_NAMESPACE_MAX]):
        meta_row[_FC_NAMESPACE_LABELS_META_START + i] = label
    # Clear any leftover labels beyond current list
    for i in range(len(ns_labels), _FC_NAMESPACE_MAX):
        meta_row[_FC_NAMESPACE_LABELS_META_START + i] = ""
    writer.writerow(meta_row)
    writer.writerow(parsed["header"])
    for row in parsed["data"]:
        writer.writerow(row)
    return buf.getvalue()


def _split_node_id(node_id: str) -> tuple[str, str]:
    """Split 'ns=X;i=N' into ('X', 'N').  Returns ('0', '') for empty or non-matching."""
    if not node_id:
        return ("0", "")
    m = re.fullmatch(r"ns=(\d+);i=(\d+)", node_id.strip())
    if m:
        return (m.group(1), m.group(2))
    return ("0", node_id.strip())


def _normalize_access_level_for_ui(raw_access: str) -> str:
    """CSV access level (1-7) → UI base value (1-3). Strips the HistoryRead bit (4)."""
    try:
        val = int(str(raw_access or "").strip())
    except ValueError:
        return ""
    base = val & 0x03
    return str(base) if base in (1, 2, 3) else ""


def _compose_access_level_for_csv(ui_access: str, historizing: str) -> str:
    """UI base access (1-3) + Historizing flag → CSV access level (1-7)."""
    try:
        base = int(str(ui_access or "").strip()) & 0x03
    except ValueError:
        return ""
    if base not in (1, 2, 3):
        return ""
    if str(historizing or "").strip() == "1":
        base |= 0x04
    return str(base)


def _format_locale_text(value: str) -> str:
    """Build locale-prefixed text used by DisplayName/Description columns."""
    return f"en:{value}" if value else ""


def format_csv_to_dto(parsed: dict) -> list[dict]:
    """Convert parsed format.csv data rows to grid DTOs (editable columns only)."""
    rows = []
    for i, row in enumerate(parsed["data"]):
        ns_idx, id_num = _split_node_id(row[_FC_NODE_ID])
        rows.append({
            "_row": i,
            "NodeClass": row[_FC_NODE_CLASS],
            "BrowsePath": row[_FC_BROWSE_PATH],
            "NamespaceIndex": ns_idx,
            "NodeIdNumber": id_num,
            "BrowseName": row[_FC_BROWSE_NAME],
            "DataType": _FC_DATATYPE_PATH_TO_SHORT.get(row[_FC_DATA_TYPE], row[_FC_DATA_TYPE]),
            "Access": _normalize_access_level_for_ui(row[_FC_ACCESS_LEVEL]),
            "Historizing": row[_FC_HISTORIZING],
            "EventNotifier": row[_FC_OBJECT_EVENT_NOTIFIER],
            "Cyclic": row[_FC_CYCLIC] if row[_FC_CYCLIC].strip() else "1000",
            "Param1": row[_FC_PARAM1],
        })
    return rows


def _build_new_csv_row(dto: dict) -> list[str]:
    """Build a complete CSV row for a brand-new entry with defaults for non-editable fields."""
    node_class = str(dto.get("NodeClass", "Variable")).strip()
    browse_path = str(dto.get("BrowsePath", "")).strip()
    browse_name = str(dto.get("BrowseName", "")).strip()
    ns_idx = str(dto.get("NamespaceIndex", "0")).strip()
    id_num = str(dto.get("NodeIdNumber", "")).strip()
    node_id = f"ns={ns_idx};i={id_num}" if id_num else ""
    data_type_short = str(dto.get("DataType", "")).strip()
    data_type = _FC_DATATYPE_SHORT_TO_PATH.get(data_type_short, data_type_short)
    historizing = str(dto.get("Historizing", "")).strip()
    access = _compose_access_level_for_csv(str(dto.get("Access", "")).strip(), historizing)
    event_notifier = str(dto.get("EventNotifier", "0")).strip()
    param1 = str(dto.get("Param1", "")).strip()
    cyclic = str(dto.get("Cyclic", "1000")).strip() or "1000"

    row = [""] * _FC_TOTAL_COLS
    row[_FC_NODE_CLASS] = node_class
    row[_FC_BROWSE_PATH] = browse_path
    row[_FC_NODE_ID] = node_id
    row[_FC_REFERENCE_TYPE_ID] = _FC_REF_TYPE_DEFAULT
    row[_FC_BROWSE_NAME] = browse_name
    row[_FC_TYPE_DEFINITION_ID] = _FC_OBJECT_TYPE_DEF if node_class == "Object" else _FC_VARIABLE_TYPE_DEF
    row[_FC_HAS_MODELLING_RULE] = _FC_HAS_MODELLING_RULE_DEFAULT
    row[_FC_DISPLAY_NAME] = _format_locale_text(browse_name)
    row[_FC_DESCRIPTION] = _format_locale_text(browse_name)
    row[_FC_WRITE_MASK] = "0"
    if node_class == "Object":
        row[_FC_OBJECT_EVENT_NOTIFIER] = event_notifier if event_notifier else "0"
    if node_class == "Variable":
        row[_FC_VALUE_RANK] = "-1"
        row[_FC_ARRAY_DIMENSIONS_SIZE] = "0"
        row[_FC_MIN_SAMPLING_INTERVAL] = "250"
        row[_FC_CYCLIC] = cyclic
    row[_FC_DATA_TYPE] = data_type
    row[_FC_ACCESS_LEVEL] = access
    row[_FC_HISTORIZING] = historizing
    row[_FC_PARAM1] = param1 if node_class == "Variable" else ""
    if node_class == "Variable" and row[_FC_PARAM1] not in ("0", "1"):
        row[_FC_PARAM1] = "0"
    row[_FC_PARAM2] = ""
    return row


def dto_to_format_csv_row(dto: dict, existing_row: list[str] | None) -> list[str]:
    """Merge DTO editable fields into a CSV row, preserving non-editable fields."""
    if existing_row is None:
        return _build_new_csv_row(dto)

    row = _pad_csv_row(list(existing_row))
    old_class = row[_FC_NODE_CLASS]
    new_class = str(dto.get("NodeClass", old_class)).strip()
    row[_FC_NODE_CLASS] = new_class
    row[_FC_BROWSE_PATH] = str(dto.get("BrowsePath", row[_FC_BROWSE_PATH])).strip()
    ns_idx = str(dto.get("NamespaceIndex", "0")).strip()
    id_num = str(dto.get("NodeIdNumber", "")).strip()
    row[_FC_NODE_ID] = f"ns={ns_idx};i={id_num}" if id_num else ""
    row[_FC_BROWSE_NAME] = str(dto.get("BrowseName", row[_FC_BROWSE_NAME])).strip()
    row[_FC_DISPLAY_NAME] = _format_locale_text(row[_FC_BROWSE_NAME])
    row[_FC_DESCRIPTION] = _format_locale_text(row[_FC_BROWSE_NAME])
    data_type_short = str(dto.get("DataType", "")).strip()
    row[_FC_DATA_TYPE] = _FC_DATATYPE_SHORT_TO_PATH.get(data_type_short, data_type_short)
    row[_FC_HISTORIZING] = str(dto.get("Historizing", row[_FC_HISTORIZING])).strip()
    row[_FC_ACCESS_LEVEL] = _compose_access_level_for_csv(
        str(dto.get("Access", _normalize_access_level_for_ui(row[_FC_ACCESS_LEVEL]))).strip(),
        row[_FC_HISTORIZING],
    )
    if new_class == "Object":
        row[_FC_OBJECT_EVENT_NOTIFIER] = str(dto.get("EventNotifier", row[_FC_OBJECT_EVENT_NOTIFIER])).strip()
    if new_class == "Variable":
        row[_FC_MIN_SAMPLING_INTERVAL] = "250"
        cyclic_val = str(dto.get("Cyclic", row[_FC_CYCLIC])).strip() or "1000"
        row[_FC_CYCLIC] = cyclic_val
    else:
        row[_FC_CYCLIC] = ""
    row[_FC_PARAM1] = str(dto.get("Param1", row[_FC_PARAM1])).strip() if new_class == "Variable" else ""
    row[_FC_PARAM2] = ""
    if old_class != new_class:
        row[_FC_TYPE_DEFINITION_ID] = _FC_OBJECT_TYPE_DEF if new_class == "Object" else _FC_VARIABLE_TYPE_DEF
    return row


def validate_format_grid(rows: list[dict]) -> list[dict]:
    """Validate grid rows. Returns a list of per-row error dicts."""
    errors: list[dict] = []

    full_path_seen: set[str] = set()
    node_id_seen: dict[str, int] = {}
    event_notifier_rows: list[int] = []

    # Build object paths for BrowsePath tree check
    object_full_paths: set[str] = {"Objects"}
    for row in rows:
        node_class = str(row.get("NodeClass", "")).strip()
        bp = str(row.get("BrowsePath", "")).strip()
        bn = str(row.get("BrowseName", "")).strip()
        if node_class == "Object":
            full = f"{bp}/{bn}" if bp else bn
            object_full_paths.add(full)

    for i, row in enumerate(rows):
        node_class = str(row.get("NodeClass", "")).strip()
        browse_path = str(row.get("BrowsePath", "")).strip()
        browse_name = str(row.get("BrowseName", "")).strip()
        ns_idx = str(row.get("NamespaceIndex", "0")).strip()
        id_num = str(row.get("NodeIdNumber", "")).strip()
        node_id = f"ns={ns_idx};i={id_num}" if id_num else ""

        if node_class not in ("Object", "Variable"):
            errors.append({"row": i, "field": "NodeClass", "message": "NodeClass must be Object or Variable"})

        if node_class == "Object" and str(row.get("EventNotifier", "")).strip() == "1":
            event_notifier_rows.append(i)

        if not browse_name:
            errors.append({"row": i, "field": "BrowseName", "message": "BrowseName is required"})

        if node_class == "Variable":
            param1_val = str(row.get("Param1", "")).strip()
            if param1_val not in ("", "0", "1"):
                errors.append({"row": i, "field": "Param1",
                                "message": f"Param1 must be '0' or '1' for Variable rows, got '{param1_val}'"})

            cyclic_val = str(row.get("Cyclic", "1000")).strip() or "1000"
            try:
                cyclic_int = int(cyclic_val)
                if not (250 <= cyclic_int <= 300000):
                    errors.append({"row": i, "field": "Cyclic",
                                   "message": f"Cyclic must be between 250 and 300000, got {cyclic_int}"})
            except ValueError:
                errors.append({"row": i, "field": "Cyclic",
                               "message": f"Cyclic must be an integer, got '{cyclic_val}'"})
        full_path = f"{browse_path}/{browse_name}" if browse_path else browse_name
        if full_path in full_path_seen:
            errors.append({"row": i, "field": "BrowseName", "message": f"Duplicate BrowsePath+BrowseName: {full_path}"})
        else:
            full_path_seen.add(full_path)

        if browse_path and browse_path not in object_full_paths:
            errors.append({"row": i, "field": "BrowsePath", "message": f"Parent path not found: {browse_path}"})

        if node_id:
            if node_id in node_id_seen:
                errors.append({"row": i, "field": "NodeIdNumber", "message": f"Duplicate NodeId: {node_id}"})
            else:
                node_id_seen[node_id] = i

    if len(event_notifier_rows) == 0:
        errors.append({"row": 0, "field": "EventNotifier", "message": "One Object row must have EventNotifier=1"})
    elif len(event_notifier_rows) > 1:
        for row_idx in event_notifier_rows:
            errors.append({"row": row_idx, "field": "EventNotifier", "message": "Only one Object row can have EventNotifier=1"})

    return errors


def assign_format_grid_node_ids(rows: list[dict]) -> list[dict]:
    """Assign NodeIds (NamespaceIndex=0, NodeIdNumber=N) to rows that have an empty NodeIdNumber."""
    existing_ids: set[int] = set()
    for row in rows:
        id_num = str(row.get("NodeIdNumber", "")).strip()
        if id_num and id_num.isdigit():
            existing_ids.add(int(id_num))

    next_id = _FC_NODE_ID_START
    updated = []
    for row in rows:
        r = dict(row)
        if not str(r.get("NodeIdNumber", "")).strip():
            while next_id in existing_ids:
                next_id += 1
            r["NamespaceIndex"] = r.get("NamespaceIndex", "0") or "0"
            r["NodeIdNumber"] = str(next_id)
            existing_ids.add(next_id)
            next_id += 1
        updated.append(r)
    return updated


def ensure_opcua_mutable_paths() -> tuple[bool, str]:
    ok, message = ensure_opcua_installed()
    if not ok:
        return False, message

    try:
        OPCUA_CLIENT_CERT_DIR.mkdir(parents=True, exist_ok=True)
        OPCUA_FORMAT_FILE.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return False, f"permission denied for OPCUA install root: {str(OPCUA_INSTALL_ROOT)}"

    return True, ""


def get_opcua_error_status(message: str) -> int:
    if message.startswith("permission denied"):
        return 500
    return 404


def list_opcua_client_cert_paths() -> list[Path]:
    if not OPCUA_CLIENT_CERT_DIR.exists():
        return []
    return list_upload_file_paths(OPCUA_CLIENT_CERT_DIR, ALLOWED_UPLOAD_EXTENSION)


def validate_opcua_client_cert_filename(filename: str) -> str:
    name = str(filename)
    if not name or name in {".", ".."}:
        raise ValueError("invalid filename")
    if Path(name).name != name:
        raise ValueError("invalid filename")
    if "/" in name or "\\" in name or "\x00" in name:
        raise ValueError("invalid filename")
    if not name.lower().endswith(ALLOWED_UPLOAD_EXTENSION):
        raise ValueError(f"file extension must be {ALLOWED_UPLOAD_EXTENSION}")
    return name


def validate_der_certificate_payload(raw_bytes: bytes) -> tuple[bool, str]:
    if not raw_bytes:
        return False, "empty file"

    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file.write(raw_bytes)
        temp_path = temp_file.name

    try:
        result = subprocess.run(
            ["openssl", "x509", "-inform", "DER", "-in", temp_path, "-noout"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, "invalid DER certificate"
        return True, ""
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def parse_config_csv_entry(raw_line: str) -> tuple[str, str] | None:
    if "," not in raw_line:
        return None
    key, value = raw_line.split(",", 1)
    return key.strip(), value.strip()


def empty_modbus_settings() -> dict:
    return {"slaves": [], "mappings": []}


def get_saved_modbus_draft() -> dict:
    config = load_app_config()
    custom_pages = config.get("custom_pages", {})
    draft = custom_pages.get(MODBUS_CUSTOM_PAGE_ID, {})
    return draft if isinstance(draft, dict) else {}


def save_modbus_draft(settings: dict) -> None:
    config = load_app_config()
    custom_pages = config.setdefault("custom_pages", {})
    custom_pages[MODBUS_CUSTOM_PAGE_ID] = settings
    save_app_config(config)


def _normalize_modbus_slave(raw: dict) -> dict:
    return {
        "name": str(raw.get("name", "")).strip(),
        "ip": str(raw.get("ip", "")).strip(),
        "port": str(raw.get("port", "502")).strip(),
        "type": str(raw.get("type", "holding")).strip() or "holding",
    }


def _normalize_modbus_mapping(raw: dict) -> dict:
    return {
        "nodeId": str(raw.get("nodeId", "")).strip(),
        "browsePath": str(raw.get("browsePath", "")).strip(),
        "browseName": str(raw.get("browseName", "")).strip(),
        "dataType": str(raw.get("dataType", "")).strip(),
        "slaveName": str(raw.get("slaveName", "")).strip(),
        "address": str(raw.get("address", "")).strip(),
    }


def _load_opcua_variable_lookup() -> dict[str, dict]:
    if not OPCUA_FORMAT_FILE.is_file():
        return {}

    try:
        parsed = parse_format_csv(OPCUA_FORMAT_FILE.read_text(encoding="utf-8"))
        rows = format_csv_to_dto(parsed)
    except (OSError, ValueError, IndexError):
        return {}

    lookup: dict[str, dict] = {}
    for row in rows:
        if str(row.get("NodeClass", "")).strip() != "Variable":
            continue
        ns_index = str(row.get("NamespaceIndex", "0")).strip() or "0"
        node_id_number = str(row.get("NodeIdNumber", "")).strip()
        if not node_id_number:
            continue
        node_id = f"ns={ns_index};i={node_id_number}"
        lookup[node_id] = {
            "nodeId": node_id,
            "browsePath": str(row.get("BrowsePath", "")).strip(),
            "browseName": str(row.get("BrowseName", "")).strip(),
            "dataType": str(row.get("DataType", "")).strip(),
        }
    return lookup


def normalize_modbus_settings(payload: dict | None) -> dict:
    source = payload if isinstance(payload, dict) else {}
    slaves = [_normalize_modbus_slave(item) for item in source.get("slaves", []) if isinstance(item, dict)]
    mappings = [_normalize_modbus_mapping(item) for item in source.get("mappings", []) if isinstance(item, dict)]
    return {"slaves": slaves[:MODBUS_MAX_SLAVES], "mappings": mappings}


def prune_modbus_settings(settings: dict) -> dict:
    normalized = normalize_modbus_settings(settings)
    slaves = normalized["slaves"]
    slave_names = {slave["name"].casefold() for slave in slaves if slave["name"]}
    opcua_lookup = _load_opcua_variable_lookup()
    mappings = []
    for mapping in normalized["mappings"]:
        if not mapping["slaveName"] or mapping["slaveName"].casefold() not in slave_names:
            continue
        if not mapping["address"]:
            continue
        current_node = opcua_lookup.get(mapping["nodeId"])
        if opcua_lookup and current_node is None:
            continue
        merged = dict(mapping)
        if current_node:
            merged["browsePath"] = current_node["browsePath"]
            merged["browseName"] = current_node["browseName"]
            merged["dataType"] = current_node["dataType"]
        mappings.append(merged)
    return {"slaves": slaves, "mappings": mappings}


def validate_modbus_settings(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise TypeError("settings payload must be a JSON object")

    raw_slaves = payload.get("slaves", [])
    raw_mappings = payload.get("mappings", [])
    if not isinstance(raw_slaves, list):
        raise TypeError("slaves must be a list")
    if not isinstance(raw_mappings, list):
        raise TypeError("mappings must be a list")

    settings = normalize_modbus_settings(payload)
    slaves = settings["slaves"]
    mappings = settings["mappings"]

    if len(slaves) > MODBUS_MAX_SLAVES:
        raise ValueError(f"maximum slaves is {MODBUS_MAX_SLAVES}")

    seen_names: set[str] = set()
    for slave in slaves:
        if not slave["name"]:
            raise ValueError("slave name is required")
        normalized_name = slave["name"].casefold()
        if normalized_name in seen_names:
            raise ValueError("slave names must be unique")
        seen_names.add(normalized_name)
        try:
            ipaddress.IPv4Address(slave["ip"])
        except ipaddress.AddressValueError as error:
            raise ValueError(f"invalid IP address for slave {slave['name']}: {error}") from error
        try:
            port = int(slave["port"])
        except ValueError as error:
            raise ValueError("port must be between 1 and 65535") from error
        if port < 1 or port > 65535:
            raise ValueError("port must be between 1 and 65535")
        if slave["type"] not in MODBUS_ALLOWED_TYPES:
            raise ValueError(f"unsupported slave type: {slave['type']}")

    for mapping in mappings:
        if not mapping["slaveName"] or not mapping["address"]:
            raise ValueError("mapping requires both slaveName and address")
        if mapping["slaveName"].casefold() not in seen_names:
            raise ValueError(f"mapping references unknown slave: {mapping['slaveName']}")

    return prune_modbus_settings(settings)


def test_modbus_tcp_connection(host: str, port: int, timeout_seconds: float = 1.5) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True, ""
    except OSError as error:
        return False, str(error)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise OSError("connection closed by peer")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_modbus_addr0_to_8_hex(host: str, port: int, unit_id: int = 1, timeout_seconds: float = 1.5) -> list[str]:
    if unit_id < 0 or unit_id > 255:
        raise ValueError("unit_id must be between 0 and 255")

    transaction_id = 1
    start_addr = 0
    quantity = 9
    function_code = 0x03

    request = (
        transaction_id.to_bytes(2, "big")
        + (0).to_bytes(2, "big")
        + (6).to_bytes(2, "big")
        + bytes([unit_id, function_code])
        + start_addr.to_bytes(2, "big")
        + quantity.to_bytes(2, "big")
    )

    with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
        sock.settimeout(timeout_seconds)
        sock.sendall(request)

        mbap = _recv_exact(sock, 7)
        protocol_id = int.from_bytes(mbap[2:4], "big")
        length_field = int.from_bytes(mbap[4:6], "big")
        if protocol_id != 0:
            raise OSError(f"invalid protocol id: {protocol_id}")
        if length_field < 2:
            raise OSError(f"invalid MBAP length: {length_field}")

        pdu = _recv_exact(sock, length_field - 1)
        if len(pdu) < 2:
            raise OSError("invalid Modbus response length")

        response_fc = pdu[0]
        if response_fc == (function_code | 0x80):
            exception_code = pdu[1]
            raise OSError(f"modbus exception code: 0x{exception_code:02X}")
        if response_fc != function_code:
            raise OSError(f"unexpected function code: 0x{response_fc:02X}")

        byte_count = pdu[1]
        data = pdu[2:]
        expected_bytes = quantity * 2
        if byte_count != expected_bytes or len(data) < expected_bytes:
            raise OSError(
                f"unexpected payload size: byte_count={byte_count}, data_len={len(data)}, expected={expected_bytes}"
            )

        registers = [int.from_bytes(data[i:i + 2], "big") for i in range(0, expected_bytes, 2)]
        return [f"0x{value:04X}" for value in registers]


def parse_modbus_settings_csv(text: str) -> dict:
    reader = csv.reader(io.StringIO(text))
    slaves_by_index: dict[int, dict] = {}
    mappings: list[dict] = []
    opcua_lookup = _load_opcua_variable_lookup()

    for raw_row in reader:
        row = [cell.strip() for cell in raw_row]
        if not row or not any(row):
            continue
        key = row[0]
        property_match = re.fullmatch(r"modbus\.server\.setting(\d+)\.(name|ip|port|type)", key)
        compact_match = re.fullmatch(r"modbus\.server\.setting(\d+)\.(.+)", key)
        mapping_match = re.fullmatch(r"modbus\.connection\.value(\d+)\.(.+)", key)

        if property_match:
            index = int(property_match.group(1))
            prop = property_match.group(2)
            slave = slaves_by_index.setdefault(index, _normalize_modbus_slave({}))
            slave[prop] = row[1] if len(row) > 1 else ""
            continue

        if compact_match and len(row) >= 4:
            index = int(compact_match.group(1))
            slave = slaves_by_index.setdefault(index, _normalize_modbus_slave({}))
            slave["name"] = compact_match.group(2).strip()
            slave["ip"] = row[1]
            slave["port"] = row[2]
            slave["type"] = row[3]
            continue

        if mapping_match:
            slave_name = mapping_match.group(2).strip()
            node_id = row[2] if len(row) > 2 else ""
            current_node = opcua_lookup.get(node_id, {})
            mappings.append(
                {
                    "nodeId": node_id,
                    "browsePath": current_node.get("browsePath", ""),
                    "browseName": current_node.get("browseName", ""),
                    "dataType": row[3] if len(row) > 3 and row[3] else current_node.get("dataType", ""),
                    "slaveName": slave_name,
                    "address": row[1] if len(row) > 1 else "",
                }
            )

    ordered_slaves = [_normalize_modbus_slave(slaves_by_index[index]) for index in sorted(slaves_by_index)]
    return prune_modbus_settings({"slaves": ordered_slaves, "mappings": mappings})


def serialize_modbus_settings_csv(settings: dict) -> str:
    normalized = prune_modbus_settings(settings)
    opcua_lookup = _load_opcua_variable_lookup()
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)

    for index, slave in enumerate(normalized["slaves"], start=1):
        writer.writerow([f"modbus.server.setting{index}.name", slave["name"]])
        writer.writerow([f"modbus.server.setting{index}.ip", slave["ip"]])
        writer.writerow([f"modbus.server.setting{index}.port", slave["port"]])
        writer.writerow([f"modbus.server.setting{index}.type", slave["type"]])

    for index, mapping in enumerate(normalized["mappings"], start=1):
        data_type = mapping["dataType"] or opcua_lookup.get(mapping["nodeId"], {}).get("dataType", "")
        writer.writerow([
            f"modbus.connection.value{index}.{mapping['slaveName']}",
            mapping["address"],
            mapping["nodeId"],
            data_type,
        ])

    return buffer.getvalue()


def read_opcua_config() -> dict:
    if not OPCUA_CONFIG_FILE.is_file():
        raise FileNotFoundError(str(OPCUA_CONFIG_FILE))

    lines = OPCUA_CONFIG_FILE.read_text(encoding="utf-8").splitlines()
    port = None
    product_name = ""
    software_version = ""
    max_sessions = ""
    allow_anonymous = ""
    usernames: list[str] = []
    passwords: list[str] = []

    for line in lines:
        parsed = parse_config_csv_entry(line)
        if not parsed:
            continue
        key, value = parsed
        if key == "server.portNumber":
            port = value
        elif key == "server.buildInfo.productName":
            product_name = value
        elif key == "server.buildInfo.softwareVersion":
            software_version = value
        elif key == "server.maxSessions":
            max_sessions = value
        elif key == "server.allowAnonymous":
            allow_anonymous = value
        elif key == "server.userName":
            usernames.append(value)
        elif key == "server.userPassword":
            passwords.append(value)

    users = []
    for index, username in enumerate(usernames):
        password = passwords[index] if index < len(passwords) else ""
        users.append({"username": username, "password": password})

    if port is None:
        port = ""

    return {
        "port": port,
        "product_name": product_name,
        "software_version": software_version,
        "max_sessions": max_sessions,
        "allow_anonymous": allow_anonymous,
        "users": users,
    }


def validate_opcua_port(value: str) -> int:
    try:
        port = int(str(value).strip())
    except ValueError as error:
        raise ValueError("port must be a number") from error

    if port <= 1023 or port >= 65536:
        raise ValueError("port must be between 1024 and 65535")
    return port


def validate_opcua_users(users_payload: list) -> list[dict[str, str]]:
    if not isinstance(users_payload, list):
        raise ValueError("users must be an array")

    if len(users_payload) == 0:
        raise ValueError("at least one user is required")
    if len(users_payload) > OPCUA_MAX_USERS:
        raise ValueError(f"maximum users is {OPCUA_MAX_USERS}")

    normalized_users: list[dict[str, str]] = []
    for index, item in enumerate(users_payload):
        if not isinstance(item, dict):
            raise ValueError(f"users[{index}] must be an object")

        username = str(item.get("username", "")).strip()
        password = str(item.get("password", "")).strip()
        if not username:
            raise ValueError(f"users[{index}].username is required")
        if not password:
            raise ValueError(f"users[{index}].password is required")
        normalized_users.append({"username": username, "password": password})

    return normalized_users


def validate_opcua_product_name(value: str) -> str:
    product_name = str(value).strip()
    if not product_name:
        raise ValueError("product name is required")
    if not OPCUA_PRODUCT_NAME_PATTERN.fullmatch(product_name):
        raise ValueError("product name must be ASCII only and up to 64 characters")
    if "," in product_name:
        raise ValueError("product name cannot contain comma")
    return product_name


def validate_opcua_software_version(value: str) -> str:
    software_version = str(value).strip()
    if not software_version:
        raise ValueError("software version is required")
    if len(software_version) > 64:
        raise ValueError("software version must be up to 64 characters")
    if "," in software_version:
        raise ValueError("software version cannot contain comma")
    return software_version


def validate_opcua_max_sessions(value: str) -> int:
    try:
        max_sessions = int(str(value).strip())
    except ValueError as error:
        raise ValueError("max sessions must be a number") from error

    if max_sessions <= 0 or max_sessions > OPCUA_MAX_SESSIONS_LIMIT:
        raise ValueError(f"max sessions must be between 1 and {OPCUA_MAX_SESSIONS_LIMIT}")
    return max_sessions


def validate_opcua_allow_anonymous(value) -> int:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "on", "yes"}:
        return 1
    if normalized in {"0", "false", "off", "no"}:
        return 0
    raise ValueError("allow anonymous must be ON or OFF")


def format_allow_anonymous_value(allow_anonymous: int, existing_lines: list[str]) -> str:
    existing_value = ""
    for line in existing_lines:
        parsed = parse_config_csv_entry(line)
        if not parsed:
            continue
        key, value = parsed
        if key == "server.allowAnonymous":
            existing_value = str(value).strip().lower()
            break

    if existing_value in {"on", "off"}:
        return "ON" if allow_anonymous == 1 else "OFF"
    if existing_value in {"true", "false"}:
        return "true" if allow_anonymous == 1 else "false"
    return "1" if allow_anonymous == 1 else "0"


def write_opcua_config(
    port: int,
    users: list[dict[str, str]],
    product_name: str,
    software_version: str,
    max_sessions: int,
    allow_anonymous: int,
) -> None:
    lines = OPCUA_CONFIG_FILE.read_text(encoding="utf-8").splitlines()
    allow_anonymous_value = format_allow_anonymous_value(allow_anonymous, lines)
    managed_keys = {
        "server.buildInfo.productName",
        "server.buildInfo.softwareVersion",
        "server.portNumber",
        "server.maxSessions",
        "server.userNameSize",
        "server.userName",
        "server.userPasswordSize",
        "server.userPassword",
        "server.allowAnonymous",
    }

    filtered_lines: list[str] = []
    first_managed_index: int | None = None
    for line in lines:
        parsed = parse_config_csv_entry(line)
        key = parsed[0] if parsed else ""
        if key in managed_keys:
            if first_managed_index is None:
                first_managed_index = len(filtered_lines)
            continue
        filtered_lines.append(line)

    insert_at = first_managed_index if first_managed_index is not None else len(filtered_lines)
    managed_block = [
        f"server.buildInfo.productName,{product_name}",
        f"server.buildInfo.softwareVersion,{software_version}",
        f"server.portNumber,{port}",
        f"server.maxSessions,{max_sessions}",
        f"server.userNameSize,{len(users)}",
    ]
    managed_block.extend([f"server.userName,{entry['username']}" for entry in users])
    managed_block.append(f"server.userPasswordSize,{len(users)}")
    managed_block.extend([f"server.userPassword,{entry['password']}" for entry in users])
    managed_block.append(f"server.allowAnonymous,{allow_anonymous_value}")

    new_lines = filtered_lines[:insert_at] + managed_block + filtered_lines[insert_at:]
    OPCUA_CONFIG_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def get_opcua_overview() -> dict:
    service = get_opcua_service_status()
    cert_files = [serialize_uploaded_file(path) for path in list_opcua_client_cert_paths()]
    format_file = serialize_uploaded_file(OPCUA_FORMAT_FILE) if OPCUA_FORMAT_FILE.is_file() else None
    config = None
    if OPCUA_CONFIG_FILE.is_file():
        try:
            config = read_opcua_config()
        except Exception:
            config = None
    return {
        "install_root": str(OPCUA_INSTALL_ROOT),
        "installed": bool(service["installed"]),
        "service": service,
        "client_certs": cert_files,
        "format_file": format_file,
        "config": config,
    }


def require_root() -> tuple[bool, tuple]:
    if os.geteuid() != 0:
        return False, (jsonify({"error": "This endpoint requires root privileges"}), 403)
    return True, ()


def interface_sort_key(name: str) -> tuple:
    parts = re.split(r"(\d+)", name)
    normalized = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            normalized.append((0, int(part)))
        else:
            normalized.append((1, part))
    return tuple(normalized)


def is_wired_interface(name: str) -> bool:
    return bool(re.match(r"^(eth\d+|en[a-z0-9]+)$", name))


def build_interface_choices(interfaces: list[str]) -> list[dict[str, str]]:
    choices = []
    wired_index = 0
    for interface in interfaces:
        if is_wired_interface(interface):
            label = f"Ether{wired_index} ({interface})"
            wired_index += 1
        else:
            label = interface
        choices.append({"value": interface, "label": label})
    return choices


def list_system_interfaces() -> list[str]:
    interfaces = []
    try:
        lines = run_command(["ip", "-o", "link", "show"]).splitlines()
        for line in lines:
            parts = line.split(":", 2)
            if len(parts) < 2:
                continue
            name = parts[1].strip()
            if "@" in name:
                name = name.split("@", 1)[0]
            if name and name != "lo":
                interfaces.append(name)
    except Exception:
        return []
    return sorted(dict.fromkeys(interfaces), key=interface_sort_key)


def get_default_interface() -> str:
    try:
        route = run_command(["ip", "-4", "route", "show", "default"])
        if not route:
            interfaces = list_system_interfaces()
            return interfaces[0] if interfaces else DEFAULT_INTERFACE

        first_line = route.splitlines()[0].strip()
        parts = first_line.split()
        if "dev" in parts:
            dev_index = parts.index("dev")
            if dev_index + 1 < len(parts):
                return parts[dev_index + 1]
    except Exception:
        pass

    interfaces = list_system_interfaces()
    return interfaces[0] if interfaces else DEFAULT_INTERFACE


def normalize_interface_name(interface: str | None) -> str:
    requested = (interface or "").strip()
    available = list_system_interfaces()
    if requested and requested in available:
        return requested
    return available[0] if available else DEFAULT_INTERFACE


def read_resolv_nameservers() -> str:
    if not RESOLV_CONF_PATH.exists():
        return ""

    servers = []
    try:
        for raw in RESOLV_CONF_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("nameserver "):
                item = line.split(None, 1)[1].strip()
                try:
                    ipaddress.ip_address(item)
                    servers.append(item)
                except Exception:
                    continue
    except Exception:
        return ""

    return ",".join(servers)


def read_netplan_interfaces() -> dict[str, dict[str, str]]:
    if not NETPLAN_PATH.exists():
        return {}

    entries: dict[str, dict[str, str]] = {}
    current_interface = ""
    current_section = ""

    try:
        for raw_line in NETPLAN_PATH.read_text(encoding="utf-8").splitlines():
            line = raw_line.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            indent = len(line) - len(line.lstrip(" "))
            if indent == 4 and stripped.endswith(":") and stripped != "ethernets:":
                current_interface = stripped[:-1]
                current_section = ""
                entries[current_interface] = {
                    "mode": "dhcp",
                    "ipv4": "",
                    "gateway4": "",
                    "dns": "",
                }
                continue

            if not current_interface:
                continue

            if indent == 6 and stripped.startswith("dhcp4:"):
                value = stripped.split(":", 1)[1].strip().lower()
                entries[current_interface]["mode"] = "dhcp" if value == "true" else "static"
                current_section = ""
                continue

            if indent == 6 and stripped in {"addresses:", "routes:", "nameservers:"}:
                current_section = stripped[:-1]
                continue

            if indent == 8 and current_section == "addresses" and stripped.startswith("- "):
                entries[current_interface]["ipv4"] = stripped[2:].strip()
                continue

            if indent == 10 and current_section == "routes" and stripped.startswith("via:"):
                entries[current_interface]["gateway4"] = stripped.split(":", 1)[1].strip()
                continue

            if indent == 8 and current_section == "nameservers" and stripped.startswith("addresses:") and "[" in stripped and "]" in stripped:
                raw_values = stripped.split("[", 1)[1].split("]", 1)[0]
                entries[current_interface]["dns"] = raw_values.replace(" ", "")
    except Exception:
        return {}

    return entries


def read_mode_from_netplan(interface: str) -> str:
    return read_netplan_interfaces().get(interface, {}).get("mode", "")


def read_dns_from_netplan(interface: str) -> str:
    return read_netplan_interfaces().get(interface, {}).get("dns", "")


def read_mode_from_dhcpcd(interface: str) -> str:
    if not DHCPCD_CONF_PATH.exists():
        return ""

    in_interface = False
    try:
        for raw in DHCPCD_CONF_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("interface "):
                in_interface = line.split(None, 1)[1].strip() == interface
                continue
            if in_interface and line.startswith("static ip_address="):
                return "static"
    except Exception:
        return ""

    return ""


def read_mode_from_interfaces(interface: str) -> str:
    if not INTERFACES_PATH.exists():
        return ""
    try:
        for raw in INTERFACES_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 4 and parts[0] == "iface" and parts[1] == interface and parts[2] == "inet":
                if parts[3] == "static":
                    return "static"
                if parts[3] == "dhcp":
                    return "dhcp"
    except Exception:
        return ""
    return ""


def get_network_info(interface: str) -> dict:
    info = {
        "interface": interface,
        "mode": "dhcp",
        "ipv4": "",
        "gateway4": "",
        "dns": "",
    }

    try:
        ip_addr = run_command(["ip", "-4", "addr", "show", "dev", interface])
        for line in ip_addr.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                info["ipv4"] = line.split()[1]
                break
    except Exception:
        pass

    try:
        route = run_command(["ip", "route", "show", "default", "dev", interface])
        if route:
            parts = route.splitlines()[0].split()
            if parts and parts[0] == "default" and "via" in parts:
                via_index = parts.index("via")
                if via_index + 1 < len(parts):
                    info["gateway4"] = parts[via_index + 1]
    except Exception:
        pass

    netplan_entries = read_netplan_interfaces()
    netplan_info = netplan_entries.get(interface, {})
    if netplan_info.get("ipv4") and not info["ipv4"]:
        info["ipv4"] = netplan_info["ipv4"]
    if netplan_info.get("gateway4") and not info["gateway4"]:
        info["gateway4"] = netplan_info["gateway4"]

    mode = read_mode_from_netplan(interface)
    if not mode:
        mode = read_mode_from_dhcpcd(interface)
    if not mode:
        mode = read_mode_from_interfaces(interface)
    if mode:
        info["mode"] = mode

    dns = read_dns_from_netplan(interface)
    if not dns:
        dns = read_resolv_nameservers()
    info["dns"] = dns

    return info


def read_sntp_servers() -> str:
    if not TIMESYNCD_CONF_PATH.exists():
        return ""

    for line in TIMESYNCD_CONF_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("NTP="):
            return line.split("=", 1)[1].strip()

    return ""


def validate_static_payload(payload: dict) -> tuple[bool, str]:
    ipv4 = payload.get("ipv4", "").strip()
    gateway4 = payload.get("gateway4", "").strip()
    dns = payload.get("dns", "").strip()

    try:
        ipaddress.ip_interface(ipv4)
    except Exception:
        return False, "ipv4 must be in CIDR format. example: 192.168.1.20/24"

    try:
        ipaddress.ip_address(gateway4)
    except Exception:
        return False, "gateway4 must be a valid IPv4 address"

    if dns:
        for item in dns.split(","):
            try:
                ipaddress.ip_address(item.strip())
            except Exception:
                return False, f"invalid dns address: {item.strip()}"

    return True, ""


def write_netplan(payload: dict) -> None:
    interface = payload.get("interface", DEFAULT_INTERFACE).strip() or DEFAULT_INTERFACE
    mode = payload.get("mode", "dhcp").strip()
    entries = read_netplan_interfaces()
    entries[interface] = {
        "mode": mode,
        "ipv4": payload.get("ipv4", "").strip(),
        "gateway4": payload.get("gateway4", "").strip(),
        "dns": payload.get("dns", "").strip(),
    }

    lines = [
        "network:",
        "  version: 2",
        "  renderer: networkd",
        "  ethernets:",
    ]

    for current_interface in sorted(entries, key=interface_sort_key):
        current = entries[current_interface]
        lines.append(f"    {current_interface}:")
        if current.get("mode", "dhcp") == "dhcp":
            lines.append("      dhcp4: true")
            continue

        lines.append("      dhcp4: false")
        lines.append("      addresses:")
        lines.append(f"        - {current.get('ipv4', '')}")
        lines.append("      routes:")
        lines.append("        - to: default")
        lines.append(f"          via: {current.get('gateway4', '')}")

        dns_values = ", ".join([v.strip() for v in current.get("dns", "").split(",") if v.strip()])
        if dns_values:
            lines.append("      nameservers:")
            lines.append(f"        addresses: [{dns_values}]")

    NETPLAN_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_dhcpcd(payload: dict) -> None:
    interface = payload.get("interface", DEFAULT_INTERFACE).strip() or DEFAULT_INTERFACE
    mode = payload.get("mode", "dhcp").strip()

    current = ""
    if DHCPCD_CONF_PATH.exists():
        current = DHCPCD_CONF_PATH.read_text(encoding="utf-8")

    block_header = f"{WEBUI_MANAGED_BLOCK_BEGIN} {interface}"
    block_footer = f"{WEBUI_MANAGED_BLOCK_END} {interface}"
    block_pattern = re.compile(
        rf"\n?{re.escape(block_header)}\n.*?\n{re.escape(block_footer)}\n?",
        flags=re.DOTALL,
    )
    cleaned = re.sub(block_pattern, "\n", current).rstrip("\n")

    lines = [
        block_header,
        f"interface {interface}",
    ]

    if mode == "static":
        ipv4 = payload.get("ipv4", "").strip()
        gateway4 = payload.get("gateway4", "").strip()
        dns = payload.get("dns", "").strip()

        lines.append(f"static ip_address={ipv4}")
        lines.append(f"static routers={gateway4}")
        if dns:
            dns_values = " ".join([v.strip() for v in dns.split(",") if v.strip()])
            if dns_values:
                lines.append(f"static domain_name_servers={dns_values}")

    lines.append(block_footer)
    block = "\n".join(lines)

    if cleaned:
        content = f"{cleaned}\n\n{block}\n"
    else:
        content = f"{block}\n"

    DHCPCD_CONF_PATH.write_text(content, encoding="utf-8")


def restart_first_available_service(candidates: list[str]) -> bool:
    for name in candidates:
        try:
            run_command(["systemctl", "restart", name])
            return True
        except Exception:
            continue
    return False


def stop_first_available_service(candidates: list[str]) -> bool:
    for name in candidates:
        try:
            run_command(["systemctl", "stop", name])
            return True
        except Exception:
            continue
    return False


def apply_network_settings(payload: dict) -> None:
    if command_exists("netplan"):
        write_netplan(payload)
        run_command(["netplan", "generate"])
        run_command(["netplan", "apply"])
        return

    if DHCPCD_CONF_PATH.exists() or command_exists("dhcpcd"):
        write_dhcpcd(payload)
        restarted = restart_first_available_service(["dhcpcd", "dhcpcd.service"])
        if not restarted:
            raise RuntimeError("failed to restart dhcpcd service")
        return

    raise RuntimeError("unsupported network stack: neither netplan nor dhcpcd is available")


def write_sntp_servers(sntp: str) -> None:
    lines = [
        "[Time]",
        f"NTP={sntp.strip()}",
    ]
    TIMESYNCD_CONF_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def schedule_reboot(delay_seconds: int = 2) -> None:
    # Delay reboot slightly so the HTTP response can be returned.
    subprocess.Popen(["bash", "-lc", f"sleep {delay_seconds} && systemctl reboot"])


@app.route("/")
def index():
    # If logout page requested re-auth, force exactly one auth challenge.
    # This prevents browser-cached Basic credentials from auto-entering Web UI.
    if request.cookies.get(FORCE_REAUTH_COOKIE) == "1":
        response = build_auth_challenge_response("authentication required")
        response.delete_cookie(FORCE_REAUTH_COOKIE, path="/")
        return response

    # Check 1: Is there a valid session?
    if session.get("authenticated", False):
        return render_template("index.html")

    # Check 2: Is there a valid Basic Auth header?
    ok, username = verify_basic_auth()
    if not ok:
        # No session and no valid Basic Auth -> require authentication
        return build_auth_challenge_response("authentication required")

    # Basic Auth succeeded -> create session
    session["authenticated"] = True
    session["username"] = username
    return render_template("index.html")


@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(_error):
    return (
        jsonify({"error": f"file size must be <= {MAX_UPLOAD_SIZE_BYTES} bytes"}),
        413,
    )


@app.get("/api/auth/status")
def auth_status():
    config = load_app_config()
    auth = config.get("auth", {})
    ok, username = verify_basic_auth()

    return jsonify(
        {
            "enabled": bool(auth.get("enabled", True)),
            "authenticated": ok,
            "username": username,
        }
    )


@app.post("/api/auth/login")
def auth_login():
    return (
        jsonify(
            {
                "error": "html login is disabled. use browser basic authentication prompt"
            }
        ),
        410,
    )


@app.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return redirect("/logout")


@app.route("/logout")
def logout_page():
    # Ensure session is cleared when viewing logout page
    session.clear()
    response = make_response(render_template("logout.html"))
    # Explicitly clear the session cookie
    response.delete_cookie("session", path="/")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response

@app.get("/auth/clear-session")
def clear_session_and_redirect():
    """
    Clear session on server and redirect to / to force fresh Basic Auth.
    This is called by logout page BEFORE navigating to /
    Ensures session is cleared on server before the next request to /.
    """
    session.clear()
    response = make_response(redirect("/"))
    response.delete_cookie("session", path="/")
    response.set_cookie(FORCE_REAUTH_COOKIE, "1", path="/", samesite="Lax")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/api/auth/settings")
@auth_required
def get_auth_settings():
    config = load_app_config()
    auth = config.get("auth", {})

    return jsonify(
        {
            "enabled": bool(auth.get("enabled", True)),
            "username": auth.get("username", "admin"),
        }
    )


@app.post("/api/auth/settings")
@auth_required
def set_auth_settings():
    payload = request.get_json(force=True)
    username = payload.get("username")
    new_password = payload.get("new_password")

    if username is None and new_password is None:
        return jsonify({"error": "username or new_password is required"}), 400

    config = load_app_config()
    auth = config.setdefault("auth", {})

    if username is not None:
        username = str(username).strip()
        if not USERNAME_PATTERN.fullmatch(username):
            return (
                jsonify(
                    {
                        "error": (
                            "username must be 2-32 chars and contain only letters, "
                            "numbers, dot, underscore, hyphen"
                        )
                    }
                ),
                400,
            )
        auth["username"] = username

    if new_password is not None:
        new_password = str(new_password)
        if not PASSWORD_PATTERN.fullmatch(new_password):
            return (
                jsonify(
                    {
                        "error": "password must be 3-128 characters"
                    }
                ),
                400,
            )
        auth["password_hash"] = generate_password_hash(new_password)

    auth["enabled"] = True
    save_app_config(config)

    return jsonify({"ok": True, "username": auth.get("username", "admin")})


@app.get("/api/basic")
@auth_required
def get_basic():
    interfaces = list_system_interfaces()
    interface = normalize_interface_name(request.args.get("interface") or get_default_interface())
    network = get_network_info(interface)

    return jsonify(
        {
            "hostname": socket.gethostname(),
            "network": network,
            "interfaces": build_interface_choices(interfaces),
            "selected_interface": interface,
            "sntp": read_sntp_servers(),
        }
    )


@app.post("/api/basic")
@auth_required
def apply_basic():
    allowed, response = require_root()
    if not allowed:
        return response

    payload = request.get_json(force=True)
    hostname = payload.get("hostname", "").strip()
    mode = payload.get("mode", "dhcp").strip()
    sntp = payload.get("sntp", "").strip()
    payload["interface"] = normalize_interface_name(payload.get("interface"))

    if not hostname:
        return jsonify({"error": "hostname is required"}), 400

    if mode not in {"dhcp", "static"}:
        return jsonify({"error": "mode must be dhcp or static"}), 400

    if mode == "static":
        ok, message = validate_static_payload(payload)
        if not ok:
            return jsonify({"error": message}), 400

    try:
        run_command(["hostnamectl", "set-hostname", hostname])
        apply_network_settings(payload)

        if sntp:
            write_sntp_servers(sntp)
            run_command(["systemctl", "restart", "systemd-timesyncd"])

        schedule_reboot()

        return jsonify({"ok": True, "message": "Basic settings applied and reboot scheduled"})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": e.stderr.strip() or str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/system/reboot")
@auth_required
def system_reboot():
    allowed, response = require_root()
    if not allowed:
        return response

    try:
        schedule_reboot()
        return jsonify({"ok": True, "message": "reboot scheduled"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/app")
@auth_required
def get_app_settings():
    config = load_app_config()
    return jsonify(
        {
            **config,
            "upload_dir": str(get_upload_dir(config)),
            "upload_max_bytes": MAX_UPLOAD_SIZE_BYTES,
            "upload_max_files": MAX_UPLOAD_FILES,
        }
    )


@app.post("/api/app")
@auth_required
def set_app_settings():
    allowed, response = require_root()
    if not allowed:
        return response

    payload = request.get_json(force=True)
    upload_dir = payload.get("upload_dir", "").strip()

    config = load_app_config()

    if upload_dir:
        config["upload_dir"] = upload_dir
        Path(upload_dir).mkdir(parents=True, exist_ok=True)

    save_app_config(config)

    return jsonify({"ok": True, "upload_dir": config["upload_dir"]})


@app.get("/api/app/custom/<page_id>")
@auth_required
def get_custom_page_settings(page_id: str):
    if not CUSTOM_PAGE_ID_PATTERN.fullmatch(page_id):
        return jsonify({"error": "invalid page_id"}), 400

    config = load_app_config()
    custom_pages = config.get("custom_pages", {})
    page_settings = custom_pages.get(page_id, {})

    return jsonify({"page_id": page_id, "settings": page_settings})


@app.post("/api/app/custom/<page_id>")
@auth_required
def set_custom_page_settings(page_id: str):
    allowed, response = require_root()
    if not allowed:
        return response

    if not CUSTOM_PAGE_ID_PATTERN.fullmatch(page_id):
        return jsonify({"error": "invalid page_id"}), 400

    payload = request.get_json(force=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "settings payload must be a JSON object"}), 400

    config = load_app_config()
    custom_pages = config.setdefault("custom_pages", {})
    custom_pages[page_id] = payload
    save_app_config(config)

    return jsonify({"ok": True, "page_id": page_id, "settings": payload})


@app.get("/api/modbus")
@auth_required
def get_modbus_settings():
    settings = empty_modbus_settings()
    source = "default"

    if MODBUS_TCP_FILE.is_file():
        try:
            settings = parse_modbus_settings_csv(MODBUS_TCP_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, IndexError, csv.Error) as error:
            return jsonify({"error": f"failed to parse modbustcp.csv: {error}"}), 500
        source = "file"
    else:
        draft = get_saved_modbus_draft()
        if draft:
            settings = prune_modbus_settings(draft)
            source = "draft"

    return jsonify(
        {
            "installed": OPCUA_SERVER_BIN.is_file(),
            "file_exists": MODBUS_TCP_FILE.is_file(),
            "source": source,
            "settings": settings,
        }
    )


@app.put("/api/modbus")
@auth_required
def save_modbus_settings():
    allowed, response = require_root()
    if not allowed:
        return response

    ok, message = ensure_opcua_mutable_paths()
    if not ok:
        return jsonify({"error": message}), get_opcua_error_status(message)

    payload = request.get_json(force=True)
    try:
        settings = validate_modbus_settings(payload)
    except TypeError as error:
        return jsonify({"error": str(error)}), 400
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    try:
        MODBUS_TCP_FILE.parent.mkdir(parents=True, exist_ok=True)
        MODBUS_TCP_FILE.write_text(serialize_modbus_settings_csv(settings), encoding="utf-8")
        save_modbus_draft(settings)
    except PermissionError:
        return jsonify({"error": f"permission denied for OPCUA install root: {str(OPCUA_INSTALL_ROOT)}"}), 500

    return jsonify({"ok": True, "settings": settings, "file": str(MODBUS_TCP_FILE)})


@app.post("/api/modbus/test-connection")
@auth_required
def test_modbus_connection():
    payload = request.get_json(force=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "payload must be a JSON object"}), 400

    ip = str(payload.get("ip", "")).strip()
    port_raw = str(payload.get("port", "")).strip()
    timeout_ms_raw = str(payload.get("timeout_ms", "1500")).strip()
    unit_id_raw = str(payload.get("unit_id", "1")).strip()

    if not ip:
        return jsonify({"error": "ip is required"}), 400
    try:
        ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError:
        return jsonify({"error": f"invalid IPv4 address: {ip}"}), 400

    try:
        port = int(port_raw)
    except ValueError:
        return jsonify({"error": "port must be between 1 and 65535"}), 400
    if port < 1 or port > 65535:
        return jsonify({"error": "port must be between 1 and 65535"}), 400

    try:
        timeout_ms = int(timeout_ms_raw)
    except ValueError:
        timeout_ms = 1500
    timeout_ms = min(max(timeout_ms, 200), 10000)

    try:
        unit_id = int(unit_id_raw)
    except ValueError:
        return jsonify({"error": "unit_id must be between 0 and 255"}), 400
    if unit_id < 0 or unit_id > 255:
        return jsonify({"error": "unit_id must be between 0 and 255"}), 400

    try:
        hex_values = read_modbus_addr0_to_8_hex(ip, port, unit_id=unit_id, timeout_seconds=timeout_ms / 1000.0)
    except (OSError, ValueError) as error:
        return jsonify({"error": f"connection/read failed to {ip}:{port} ({error})"}), 502

    return jsonify(
        {
            "ok": True,
            "ip": ip,
            "port": port,
            "unit_id": unit_id,
            "timeout_ms": timeout_ms,
            "hex_values": hex_values,
        }
    )


@app.post("/api/app/upload")
@auth_required
def upload_file():
    config = load_app_config()
    upload_dir = get_upload_dir(config)
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return (
            jsonify({"error": f"permission denied for upload_dir: {str(upload_dir)}"}),
            500,
        )

    if "file" not in request.files:
        return jsonify({"error": "file field is required"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "empty file"}), 400

    try:
        filename = validate_uploaded_filename(file.filename)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    destination = upload_dir / filename
    existing_files = list_upload_file_paths(upload_dir, ALLOWED_UPLOAD_EXTENSION)
    if destination.exists():
        return (
            jsonify(
                {
                    "error": (
                        "file already exists. please delete the existing file before "
                        "uploading a replacement"
                    )
                }
            ),
            400,
        )

    if len(existing_files) >= MAX_UPLOAD_FILES:
        return (
            jsonify(
                {
                    "error": (
                        f"file count must be <= {MAX_UPLOAD_FILES}. please delete an "
                        "existing file before uploading"
                    )
                }
            ),
            400,
        )

    try:
        file.save(destination)
    except PermissionError:
        return (
            jsonify({"error": f"permission denied for upload_dir: {str(upload_dir)}"}),
            500,
        )

    return jsonify({"ok": True, "filename": filename})


@app.get("/api/app/files")
@auth_required
def list_uploaded_files():
    config = load_app_config()
    upload_dir = get_upload_dir(config)
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return (
            jsonify({"error": f"permission denied for upload_dir: {str(upload_dir)}"}),
            500,
        )

    files = []
    for path in list_upload_file_paths(upload_dir, ALLOWED_UPLOAD_EXTENSION):
        files.append(serialize_uploaded_file(path))

    return jsonify({"upload_dir": str(upload_dir), "files": files})


@app.delete("/api/app/files")
@auth_required
def delete_all_uploaded_files():
    config = load_app_config()
    upload_dir = get_upload_dir(config)

    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return (
            jsonify({"error": f"permission denied for upload_dir: {str(upload_dir)}"}),
            500,
        )

    deleted_count = 0
    try:
        for path in list_upload_file_paths(upload_dir, ALLOWED_UPLOAD_EXTENSION):
            path.unlink()
            deleted_count += 1
    except PermissionError:
        return (
            jsonify({"error": f"permission denied for upload_dir: {str(upload_dir)}"}),
            500,
        )

    return jsonify({"ok": True, "deleted_count": deleted_count})


@app.delete("/api/app/files/<path:filename>")
@auth_required
def delete_uploaded_file(filename: str):
    config = load_app_config()
    upload_dir = get_upload_dir(config)

    try:
        normalized = validate_uploaded_filename(filename)
    except ValueError:
        return jsonify({"error": "invalid filename"}), 400

    target = upload_dir / normalized
    if not target.is_file():
        return jsonify({"error": "file not found"}), 404

    try:
        target.unlink()
    except PermissionError:
        return (
            jsonify({"error": f"permission denied for upload_dir: {str(upload_dir)}"}),
            500,
        )

    return jsonify({"ok": True, "filename": normalized})


@app.get("/api/app/address-space-file")
@auth_required
def get_address_space_file():
    config = load_app_config()
    upload_dir = get_upload_dir(config)
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return (
            jsonify({"error": f"permission denied for upload_dir: {str(upload_dir)}"}),
            500,
        )

    target = get_address_space_file_path(upload_dir)
    if not target.is_file():
        return jsonify({"exists": False, "file": None})

    return jsonify({"exists": True, "file": serialize_uploaded_file(target)})


@app.post("/api/app/address-space-file")
@auth_required
def upload_address_space_file():
    config = load_app_config()
    upload_dir = get_upload_dir(config)
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return (
            jsonify({"error": f"permission denied for upload_dir: {str(upload_dir)}"}),
            500,
        )

    if "file" not in request.files:
        return jsonify({"error": "file field is required"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "empty file"}), 400

    try:
        validate_address_space_filename(file.filename)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    overwrite = str(request.form.get("overwrite", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    target = get_address_space_file_path(upload_dir)

    if target.exists() and not overwrite:
        return (
            jsonify(
                {
                    "error": "address space definition file already exists",
                    "requires_confirmation": True,
                }
            ),
            409,
        )

    try:
        file.save(target)
    except PermissionError:
        return (
            jsonify({"error": f"permission denied for upload_dir: {str(upload_dir)}"}),
            500,
        )

    return jsonify(
        {
            "ok": True,
            "filename": target.name,
            "overwritten": overwrite,
            "file": serialize_uploaded_file(target),
        }
    )


@app.delete("/api/app/address-space-file")
@auth_required
def delete_address_space_file():
    config = load_app_config()
    upload_dir = get_upload_dir(config)
    target = get_address_space_file_path(upload_dir)

    if not target.is_file():
        return jsonify({"error": "file not found"}), 404

    try:
        target.unlink()
    except PermissionError:
        return (
            jsonify({"error": f"permission denied for upload_dir: {str(upload_dir)}"}),
            500,
        )

    return jsonify({"ok": True, "filename": target.name})


@app.get("/api/app/address-space-file/download")
@auth_required
def download_address_space_file():
    config = load_app_config()
    upload_dir = get_upload_dir(config)
    target = get_address_space_file_path(upload_dir)

    if not target.is_file():
        return jsonify({"error": "file not found"}), 404

    return send_file(
        target,
        mimetype="text/csv",
        as_attachment=True,
        download_name=target.name,
    )


@app.get("/api/opcua")
@auth_required
def get_opcua_status():
    return jsonify(get_opcua_overview())


@app.post("/api/opcua/client-certs")
@auth_required
def upload_opcua_client_cert():
    allowed, response = require_root()
    if not allowed:
        return response

    ok, message = ensure_opcua_mutable_paths()
    if not ok:
        return jsonify({"error": message}), get_opcua_error_status(message)

    if "file" not in request.files:
        return jsonify({"error": "file field is required"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "empty file"}), 400

    try:
        filename = validate_opcua_client_cert_filename(file.filename)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    cert_paths = list_opcua_client_cert_paths()
    if len(cert_paths) >= OPCUA_MAX_CLIENT_CERTS and not any(path.name == filename for path in cert_paths):
        return jsonify({"error": f"maximum client certificates is {OPCUA_MAX_CLIENT_CERTS}"}), 400

    raw_bytes = file.read()
    file.stream.seek(0)
    valid_der, der_error = validate_der_certificate_payload(raw_bytes)
    if not valid_der:
        return jsonify({"error": der_error}), 400

    overwrite = str(request.form.get("overwrite", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    target = OPCUA_CLIENT_CERT_DIR / filename
    if target.exists() and not overwrite:
        return (
            jsonify(
                {
                    "error": "client certificate already exists",
                    "requires_confirmation": True,
                }
            ),
            409,
        )

    try:
        file.save(target)
    except PermissionError:
        return jsonify({"error": f"permission denied for path: {str(target)}"}), 500

    return jsonify(
        {
            "ok": True,
            "filename": filename,
            "overwritten": overwrite,
            "file": serialize_uploaded_file(target),
        }
    )


@app.delete("/api/opcua/client-certs/<path:filename>")
@auth_required
def delete_opcua_client_cert(filename: str):
    allowed, response = require_root()
    if not allowed:
        return response

    ok, message = ensure_opcua_mutable_paths()
    if not ok:
        return jsonify({"error": message}), get_opcua_error_status(message)

    try:
        normalized = validate_opcua_client_cert_filename(filename)
    except ValueError:
        return jsonify({"error": "invalid filename"}), 400

    target = OPCUA_CLIENT_CERT_DIR / normalized
    if not target.is_file():
        return jsonify({"error": "file not found"}), 404

    try:
        target.unlink()
    except PermissionError:
        return jsonify({"error": f"permission denied for path: {str(target)}"}), 500

    return jsonify({"ok": True, "filename": normalized})


@app.get("/api/opcua/config")
@auth_required
def get_opcua_config():
    ok, message = ensure_opcua_installed()
    if not ok:
        return jsonify({"error": message}), 404

    if not OPCUA_CONFIG_FILE.is_file():
        return jsonify({"error": f"config not found: {str(OPCUA_CONFIG_FILE)}"}), 404

    try:
        config = read_opcua_config()
    except Exception as error:
        return jsonify({"error": str(error)}), 500

    return jsonify(
        {
            "config_file": str(OPCUA_CONFIG_FILE),
            "port": config["port"],
            "product_name": config["product_name"],
            "software_version": config["software_version"],
            "max_sessions": config["max_sessions"],
            "allow_anonymous": config["allow_anonymous"],
            "users": config["users"],
            "max_users": OPCUA_MAX_USERS,
            "max_sessions_limit": OPCUA_MAX_SESSIONS_LIMIT,
        }
    )


@app.post("/api/opcua/config")
@auth_required
def set_opcua_config():
    allowed, response = require_root()
    if not allowed:
        return response

    ok, message = ensure_opcua_installed()
    if not ok:
        return jsonify({"error": message}), 404

    if not OPCUA_CONFIG_FILE.is_file():
        return jsonify({"error": f"config not found: {str(OPCUA_CONFIG_FILE)}"}), 404

    payload = request.get_json(force=True)
    try:
        port = validate_opcua_port(payload.get("port", ""))
        product_name = validate_opcua_product_name(payload.get("product_name", ""))
        software_version = validate_opcua_software_version(payload.get("software_version", ""))
        max_sessions = validate_opcua_max_sessions(payload.get("max_sessions", ""))
        allow_anonymous = validate_opcua_allow_anonymous(payload.get("allow_anonymous", ""))
        users = validate_opcua_users(payload.get("users", []))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    try:
        write_opcua_config(
            port=port,
            users=users,
            product_name=product_name,
            software_version=software_version,
            max_sessions=max_sessions,
            allow_anonymous=allow_anonymous,
        )
    except PermissionError:
        return jsonify({"error": f"permission denied for path: {str(OPCUA_CONFIG_FILE)}"}), 500
    except Exception as error:
        return jsonify({"error": str(error)}), 500

    return jsonify({"ok": True, "config": read_opcua_config()})


@app.get("/api/opcua/format-file/download")
@auth_required
def download_opcua_format_file():
    ok, message = ensure_opcua_installed()
    if not ok:
        return jsonify({"error": message}), 404

    if not OPCUA_FORMAT_FILE.is_file():
        return jsonify({"error": "format.csv not found"}), 404

    return send_file(
        OPCUA_FORMAT_FILE,
        mimetype="text/csv",
        as_attachment=True,
        download_name=OPCUA_FORMAT_FILE.name,
    )


@app.post("/api/opcua/format-file")
@auth_required
def upload_opcua_format_file():
    allowed, response = require_root()
    if not allowed:
        return response

    ok, message = ensure_opcua_mutable_paths()
    if not ok:
        return jsonify({"error": message}), get_opcua_error_status(message)

    if "file" not in request.files:
        return jsonify({"error": "file field is required"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "empty file"}), 400

    if Path(file.filename).suffix.lower() != ".csv":
        return jsonify({"error": "file extension must be .csv"}), 400

    if OPCUA_FORMAT_FILE.exists():
        overwrite = str(request.form.get("overwrite", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not overwrite:
            return (
                jsonify(
                    {
                        "error": "format.csv already exists",
                        "requires_confirmation": True,
                    }
                ),
                409,
            )

    try:
        OPCUA_FORMAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        file.save(OPCUA_FORMAT_FILE)
    except PermissionError:
        return jsonify({"error": f"permission denied for path: {str(OPCUA_FORMAT_FILE)}"}), 500

    return jsonify(
        {
            "ok": True,
            "filename": OPCUA_FORMAT_FILE.name,
            "file": serialize_uploaded_file(OPCUA_FORMAT_FILE),
        }
    )


@app.post("/api/opcua/service")
@auth_required
def control_opcua_service():
    allowed, response = require_root()
    if not allowed:
        return response

    ok, message = ensure_opcua_installed()
    if not ok:
        return jsonify({"error": message}), 404

    if shutil.which("systemctl") is None:
        return jsonify({"error": "systemctl is not available"}), 500

    payload = request.get_json(force=True)
    action = str(payload.get("action", "")).strip().lower()
    if action not in {"start", "stop", "restart"}:
        return jsonify({"error": "action must be start, stop, or restart"}), 400

    result = subprocess.run(
        ["systemctl", action, OPCUA_SERVICE_NAME, "--no-block"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return jsonify({"error": result.stderr.strip() or f"systemctl {action} failed"}), 500

    return jsonify(
        {
            "ok": True,
            "action": action,
            "service": get_opcua_service_status(),
        }
    )


@app.get("/api/opcua/format-grid")
@auth_required
def get_opcua_format_grid():
    ok, message = ensure_opcua_installed()
    if not ok:
        return jsonify({"error": message}), 404

    if not OPCUA_FORMAT_FILE.is_file():
        return jsonify({"error": "format.csv not found"}), 404

    try:
        text = OPCUA_FORMAT_FILE.read_text(encoding="utf-8")
        parsed = parse_format_csv(text)
        rows = format_csv_to_dto(parsed)
    except (ValueError, IndexError) as error:
        return jsonify({"error": f"failed to parse format.csv: {error}"}), 500

    return jsonify({"rows": rows, "ns_labels": parsed.get("ns_labels", [])})


def _parse_format_grid_payload(payload: dict) -> tuple[list, list[str]]:
    if not isinstance(payload, dict) or "rows" not in payload:
        raise ValueError("rows field is required")

    rows = payload["rows"]
    if not isinstance(rows, list):
        raise TypeError("rows must be a list")

    ns_labels_raw = payload.get("ns_labels", [])
    if not isinstance(ns_labels_raw, list):
        raise TypeError("ns_labels must be a list")

    ns_labels = [str(lbl).strip() for lbl in ns_labels_raw[:_FC_NAMESPACE_MAX]]
    return rows, ns_labels


@app.post("/api/opcua/format-grid/validate")
@auth_required
def validate_opcua_format_grid():
    payload = request.get_json(force=True)
    try:
        rows, _ns_labels = _parse_format_grid_payload(payload)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except TypeError as error:
        return jsonify({"error": str(error)}), 400

    errors = validate_format_grid(rows)
    return jsonify({"ok": len(errors) == 0, "errors": errors})


@app.put("/api/opcua/format-grid")
@auth_required
def save_opcua_format_grid():
    allowed, response = require_root()
    if not allowed:
        return response

    ok, message = ensure_opcua_mutable_paths()
    if not ok:
        return jsonify({"error": message}), get_opcua_error_status(message)

    if not OPCUA_FORMAT_FILE.is_file():
        return jsonify({"error": "format.csv not found"}), 404

    payload = request.get_json(force=True)
    try:
        rows, ns_labels = _parse_format_grid_payload(payload)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except TypeError as error:
        return jsonify({"error": str(error)}), 400

    errors = validate_format_grid(rows)
    if errors:
        return jsonify({"error": "validation failed", "errors": errors}), 422

    try:
        text = OPCUA_FORMAT_FILE.read_text(encoding="utf-8")
        parsed = parse_format_csv(text)
    except (ValueError, IndexError) as error:
        return jsonify({"error": f"failed to parse format.csv: {error}"}), 500

    new_data = []
    for dto in rows:
        row_idx = dto.get("_row", -1)
        existing_row = (
            parsed["data"][row_idx]
            if isinstance(row_idx, int) and 0 <= row_idx < len(parsed["data"])
            else None
        )
        new_data.append(dto_to_format_csv_row(dto, existing_row))
    parsed["data"] = new_data
    parsed["ns_labels"] = ns_labels
    new_text = format_csv_serialize(parsed)

    try:
        OPCUA_FORMAT_FILE.write_text(new_text, encoding="utf-8")
    except PermissionError:
        return jsonify({"error": f"permission denied for path: {str(OPCUA_FORMAT_FILE)}"}), 500

    return jsonify({"ok": True, "row_count": len(new_data)})


@app.post("/api/opcua/format-grid/assign-node-ids")
@auth_required
def opcua_assign_node_ids():
    payload = request.get_json(force=True)
    if not isinstance(payload, dict) or "rows" not in payload:
        return jsonify({"error": "rows field is required"}), 400

    rows = payload["rows"]
    if not isinstance(rows, list):
        return jsonify({"error": "rows must be a list"}), 400

    updated = assign_format_grid_node_ids(rows)
    return jsonify({"rows": updated})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
