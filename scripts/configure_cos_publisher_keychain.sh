#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This helper stores credentials in the macOS Keychain and only runs on macOS." >&2
  exit 1
fi

account="cad-release-publisher"
secret_id_service="FormingGrinderCAD-COS-SecretId"
secret_key_service="FormingGrinderCAD-COS-SecretKey"
secret_id=""
secret_key=""

cleanup() {
  unset secret_id secret_key
}
trap cleanup EXIT

read -r -s -p "Tencent COS SecretId: " secret_id
printf '\n'
read -r -s -p "Tencent COS SecretKey: " secret_key
printf '\n'

if [[ -z "$secret_id" || -z "$secret_key" ]]; then
  echo "SecretId and SecretKey are both required." >&2
  exit 1
fi

security add-generic-password \
  -U \
  -a "$account" \
  -s "$secret_id_service" \
  -w "$secret_id" >/dev/null
security add-generic-password \
  -U \
  -a "$account" \
  -s "$secret_key_service" \
  -w "$secret_key" >/dev/null

echo "Tencent COS publisher credentials were stored in the macOS Keychain."
