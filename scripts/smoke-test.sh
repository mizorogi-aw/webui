#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1}"
AUTH_USER="${2:-admin}"
AUTH_PASS="${3:-password}"

AUTH_OPTS=(--user "${AUTH_USER}:${AUTH_PASS}")
TMP_DIR="$(mktemp -d /tmp/field-iot-gateway-webui-smoke.XXXXXX)"
COOKIE_JAR="${TMP_DIR}/cookies.txt"
PAGE_HEADERS="${TMP_DIR}/page.headers"
PAGE_BODY="${TMP_DIR}/page.out"
LOGOUT_BODY="${TMP_DIR}/logout.out"
REAUTH1_BODY="${TMP_DIR}/reauth1.out"
WRONG_BODY="${TMP_DIR}/wrong.out"
OK_HEADERS="${TMP_DIR}/ok.headers"
OK_BODY="${TMP_DIR}/ok.out"
LOGOUT_API_HEADERS="${TMP_DIR}/logout-api.headers"
LOGOUT_API_BODY="${TMP_DIR}/logout-api.out"
REAUTH2_BODY="${TMP_DIR}/reauth2.out"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

rm -f "${COOKIE_JAR}"

echo "[1/4] GET /api/basic"
BASIC_JSON="$(curl -fsS "${AUTH_OPTS[@]}" "$BASE_URL/api/basic")"
echo "${BASIC_JSON}" | cat
if [[ "${BASIC_JSON}" != *'"wifi"'* ]]; then
  echo "FAILED: /api/basic response does not include wifi block"
  exit 1
fi

echo "[2/4] GET /api/app"
curl -fsS "${AUTH_OPTS[@]}" "$BASE_URL/api/app" | cat

echo "[3/4] POST /api/app (sample upload_dir)"
curl -fsS "${AUTH_OPTS[@]}" -X POST "$BASE_URL/api/app" \
  -H 'Content-Type: application/json' \
  -d '{"upload_dir":"/var/lib/field-iot-gateway-webui/uploads"}' | cat

echo "[4/4] GET /api/app/files"
curl -fsS "${AUTH_OPTS[@]}" "$BASE_URL/api/app/files" | cat

echo "[extra] GET https endpoint (self-signed expected)"
curl -kfsS "${AUTH_OPTS[@]}" "https://127.0.0.1/api/basic" | cat

echo "[auth-flow] Page entry without auth returns 401 with browser Basic Auth prompt"
PAGE_STATUS="$(curl -sS -D "${PAGE_HEADERS}" -o "${PAGE_BODY}" -w '%{http_code}' "${BASE_URL}/")"
echo "status=${PAGE_STATUS}"
if [[ "${PAGE_STATUS}" != "401" ]]; then
  echo "FAILED: / without auth must be 401"
  exit 1
fi
if ! grep -qi "WWW-Authenticate" "${PAGE_HEADERS}" 2>/dev/null; then
  echo "FAILED: WWW-Authenticate header not found"
  exit 1
fi

echo "[auth-flow-extended] cancel->logout->login button->wrong pass->correct pass->logout->login button"

# cancel equivalent: user goes to logout page from 401 page
LOGOUT_PAGE_STATUS="$(curl -sS -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" -o "${LOGOUT_BODY}" -w '%{http_code}' "${BASE_URL}/logout")"
echo "logout_page_status=${LOGOUT_PAGE_STATUS}"
if [[ "${LOGOUT_PAGE_STATUS}" != "200" ]]; then
  echo "FAILED: /logout must return 200"
  exit 1
fi

# login button equivalent: /auth/clear-session then redirect to / should end at 401
REAUTH_STATUS_1="$(curl -sS -L -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" -o "${REAUTH1_BODY}" -w '%{http_code}' "${BASE_URL}/auth/clear-session")"
echo "reauth_status_1=${REAUTH_STATUS_1}"
if [[ "${REAUTH_STATUS_1}" != "401" ]]; then
  echo "FAILED: /auth/clear-session flow must end with 401"
  exit 1
fi

# wrong credentials should keep returning 401
WRONG_STATUS="$(curl -sS -u "${AUTH_USER}:wrongpassword" -o "${WRONG_BODY}" -w '%{http_code}' "${BASE_URL}/")"
echo "wrong_auth_status=${WRONG_STATUS}"
if [[ "${WRONG_STATUS}" != "401" ]]; then
  echo "FAILED: wrong credentials must return 401"
  exit 1
fi

# correct credentials should authenticate and set session
OK_STATUS="$(curl -sS -D "${OK_HEADERS}" -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" "${AUTH_OPTS[@]}" -o "${OK_BODY}" -w '%{http_code}' "${BASE_URL}/")"
echo "ok_auth_status=${OK_STATUS}"
if [[ "${OK_STATUS}" != "200" ]]; then
  echo "FAILED: correct credentials must return 200"
  exit 1
fi
if ! grep -q "Field IoT Gateway Nano" "${OK_BODY}"; then
  echo "FAILED: authenticated page title not found"
  exit 1
fi

# logout button equivalent
LOGOUT_API_STATUS="$(curl -sS -D "${LOGOUT_API_HEADERS}" -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" "${AUTH_OPTS[@]}" -X POST -o "${LOGOUT_API_BODY}" -w '%{http_code}' "${BASE_URL}/api/auth/logout")"
echo "logout_api_status=${LOGOUT_API_STATUS}"
if [[ "${LOGOUT_API_STATUS}" != "302" ]]; then
  echo "FAILED: /api/auth/logout must return 302"
  exit 1
fi
if ! grep -q "^Location: /logout" "${LOGOUT_API_HEADERS}"; then
  echo "FAILED: /api/auth/logout must redirect to /logout"
  exit 1
fi

# login button again should force auth prompt again
REAUTH_STATUS_2="$(curl -sS -L -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" -o "${REAUTH2_BODY}" -w '%{http_code}' "${BASE_URL}/auth/clear-session")"
echo "reauth_status_2=${REAUTH_STATUS_2}"
if [[ "${REAUTH_STATUS_2}" != "401" ]]; then
  echo "FAILED: second /auth/clear-session flow must end with 401"
  exit 1
fi

echo "Smoke test completed"
