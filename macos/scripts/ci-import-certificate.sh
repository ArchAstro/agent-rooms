#!/usr/bin/env bash
# Import a Developer ID Application .p12 into a temporary keychain for CI.
#
# Required env:
#   MACOS_CERTIFICATE_P12_BASE64  base64 of the .p12 file
#   MACOS_CERTIFICATE_PASSWORD    password for the .p12
# Optional:
#   KEYCHAIN_PASSWORD             password for the ephemeral keychain (default: random)
#
# Use --preserve-keychain only when a later CI step needs the identity, then
# always call --cleanup. Without it, the temporary credential is removed on exit.
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

PRESERVE_KEYCHAIN=0
[[ "${1:-}" != "--preserve-keychain" ]] || PRESERVE_KEYCHAIN=1
KEYCHAIN_PASSWORD="${KEYCHAIN_PASSWORD:-$(openssl rand -base64 24)}"
KEYCHAIN_PATH="${RUNNER_TEMP:-/tmp}/rooms-signing.keychain-db"
CERT_PATH="${RUNNER_TEMP:-/tmp}/rooms-signing.p12"
SEARCH_LIST_PATH="${RUNNER_TEMP:-/tmp}/rooms-signing-keychains.txt"
IMPORT_COMPLETE=0

restore_keychain_search_list() {
  [[ -f "$SEARCH_LIST_PATH" ]] || return 0
  local keychains=()
  local keychain
  while IFS= read -r keychain; do
    [[ -z "$keychain" ]] || keychains+=("$keychain")
  done <"$SEARCH_LIST_PATH"
  if ((${#keychains[@]})); then
    security list-keychains -d user -s "${keychains[@]}" >/dev/null
  fi
}

cleanup_signing_keychain() {
  restore_keychain_search_list || true
  security delete-keychain "$KEYCHAIN_PATH" 2>/dev/null || true
  rm -f "$CERT_PATH" "$SEARCH_LIST_PATH"
}

if [[ "${1:-}" == "--cleanup" ]]; then
  cleanup_signing_keychain
  echo "==> Signing keychain removed"
  exit 0
fi
if [[ $# -gt 1 || ($# -eq 1 && "$1" != "--preserve-keychain") ]]; then
  echo "error: usage: $0 [--preserve-keychain | --cleanup]" >&2
  exit 1
fi

: "${MACOS_CERTIFICATE_P12_BASE64:?set MACOS_CERTIFICATE_P12_BASE64}"
: "${MACOS_CERTIFICATE_PASSWORD:?set MACOS_CERTIFICATE_PASSWORD}"

cleanup_on_exit() {
  rm -f "$CERT_PATH"
  if [[ "$PRESERVE_KEYCHAIN" != "1" || "$IMPORT_COMPLETE" != "1" ]]; then
    cleanup_signing_keychain
  fi
}
trap cleanup_on_exit EXIT

echo "==> Decoding certificate"
echo "$MACOS_CERTIFICATE_P12_BASE64" | base64 --decode >"$CERT_PATH"

echo "==> Creating temporary keychain"
cleanup_signing_keychain
security list-keychains -d user |
  sed -E 's/^[[:space:]]*"//; s/"[[:space:]]*$//' >"$SEARCH_LIST_PATH"
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"

echo "==> Importing .p12"
security import "$CERT_PATH" \
  -P "$MACOS_CERTIFICATE_PASSWORD" \
  -A \
  -f pkcs12 \
  -k "$KEYCHAIN_PATH"

# Allow codesign to use the key without UI prompts.
security set-key-partition-list \
  -S apple-tool:,apple:,codesign: \
  -s \
  -k "$KEYCHAIN_PASSWORD" \
  "$KEYCHAIN_PATH"

# Prepend our keychain so the imported identity is preferred.
EXISTING_KEYCHAINS=()
while IFS= read -r keychain; do
  [[ -z "$keychain" ]] || EXISTING_KEYCHAINS+=("$keychain")
done <"$SEARCH_LIST_PATH"
security list-keychains -d user -s "$KEYCHAIN_PATH" "${EXISTING_KEYCHAINS[@]}"

echo "==> Available signing identities"
IDENTITIES="$(security find-identity -v -p codesigning "$KEYCHAIN_PATH")"
echo "$IDENTITIES"
VALID_COUNT="$(
  awk '$2 == "valid" && $3 == "identities" && $4 == "found" { print $1 }' \
    <<<"$IDENTITIES"
)"
if [[ ! "$VALID_COUNT" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: the imported .p12 contains no usable code-signing identity" >&2
  echo "Export the Developer ID Application certificate together with its private key." >&2
  exit 1
fi

# Export for later steps / package script.
if [[ -n "${GITHUB_ENV:-}" ]]; then
  {
    echo "KEYCHAIN_PATH=$KEYCHAIN_PATH"
    echo "KEYCHAIN_PASSWORD=$KEYCHAIN_PASSWORD"
  } >>"$GITHUB_ENV"
fi

IMPORT_COMPLETE=1
if [[ "$PRESERVE_KEYCHAIN" == "1" ]]; then
  echo "==> Certificate import complete; run $0 --cleanup after signing"
else
  echo "==> Certificate import verified; temporary credential will be removed"
fi
