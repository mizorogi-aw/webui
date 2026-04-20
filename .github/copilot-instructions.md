WEB# Project Guidelines

## Code Style
- Follow existing patterns in `app/main.py`: explicit input validation, clear error JSON, and standard-library-first design.
- Keep Python dependencies minimal (`requirements.txt` currently uses Flask and gunicorn only).
- For shell scripts, keep `set -euo pipefail` and idempotent behavior used in `scripts/install.sh`.

## Architecture
- Runtime flow is nginx (80/443) -> gunicorn (127.0.0.1:18080) -> Flask app (`app/main.py`).
- The Flask app owns REST APIs, auth/session handling, config persistence, and system integration.
- Persistent app state is external to the repo (`/etc/field-iot-gateway-webui`, `/var/lib/field-iot-gateway-webui`) and must be preserved across reinstalls.

## Build and Test
- Local development:
  - `python3 -m venv .venv`
  - `.venv/bin/pip install -r requirements.txt`
  - `.venv/bin/python app/main.py`
- Device install/update:
  - `chmod +x scripts/*.sh`
  - `sudo ./scripts/install.sh`
- Verification:
  - `curl -fsS -u admin:password http://127.0.0.1/api/basic`
  - `sudo ./scripts/smoke-test.sh http://127.0.0.1 admin password`

## Conventions
- Keep dual authentication behavior intact: HTTP Basic Auth for scripts plus session auth for browser flow.
- For config writes, preserve existing keys and compatibility behavior (for example OPCUA token style in CSV).
- Keep upload restrictions aligned with current behavior (`.der`, size/count limits) unless requirements explicitly change.
- Treat root-required operations carefully; do not remove privilege checks around network/system mutations.
- Prefer linking to existing docs instead of duplicating details. Primary reference: `README.md`.

## Operational Pitfalls
- This project targets Ubuntu 24.04 with systemd + netplan; avoid introducing assumptions for other init/network stacks.
- IPv4 is the supported network configuration path.
- Network/apply operations can interrupt SSH sessions; avoid running mutating network commands unless explicitly requested.

## References
- `README.md` for install, service operations, verification, and troubleshooting.
- `app/main.py` for API/auth/config conventions.
- `scripts/install.sh` for deployment/source-of-truth setup behavior.