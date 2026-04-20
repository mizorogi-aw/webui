#!/usr/bin/env bash
# 配布用 tgz を生成するスクリプト
# 使い方: bash scripts/make-release.sh [バージョン]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(date +%Y%m%d)}"
ARCHIVE_NAME="field-iot-gateway-webui-${VERSION}.tgz"
TMP_OUTPUT="$(mktemp /tmp/field-iot-gateway-webui-XXXXXX.tgz)"
OUTPUT="${REPO_DIR}/${ARCHIVE_NAME}"

cd "$REPO_DIR"

tar -czf "$TMP_OUTPUT" \
  --exclude=".git" \
  --exclude=".venv" \
  --exclude="__pycache__" \
  --exclude="*.pyc" \
  --exclude="*.pyo" \
  --exclude="field-iot-gateway-webui-*.tgz" \
  --transform "s|^\.|field-iot-gateway-webui-${VERSION}|" \
  .

mv "$TMP_OUTPUT" "$OUTPUT"

echo "作成完了: ${OUTPUT}"
echo ""
echo "インストール手順:"
echo "  tar xzf ${ARCHIVE_NAME}"
echo "  sudo field-iot-gateway-webui-${VERSION}/scripts/install.sh"
