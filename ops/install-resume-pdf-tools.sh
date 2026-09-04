#!/usr/bin/env bash
# Idempotently provision the fixed-page resume rendering tools on Oracle Linux.
set -Eeuo pipefail

TECTONIC_VERSION="0.16.9"
TECTONIC_SHA256="f9aa39017dbd51f111fdb93dda222178cbe51c8193508fc567b523cc74fff9c1"
INSTALL_DIR="/usr/local/lib/resume-optimizer"
BIN_PATH="/usr/local/bin/tectonic"

if ! command -v soffice >/dev/null 2>&1 && ! command -v libreoffice >/dev/null 2>&1; then
  dnf install -y libreoffice-headless
fi

if [[ ! -x "$BIN_PATH" ]] || [[ "$($BIN_PATH --version 2>/dev/null || true)" != *"$TECTONIC_VERSION"* ]]; then
  [[ "$(uname -m)" == "aarch64" ]] || { echo "Only the Oracle A1 ARM runtime is supported by this locked installer." >&2; exit 1; }
  asset="tectonic-${TECTONIC_VERSION}-aarch64-unknown-linux-musl.tar.gz"
  base="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/${asset}"
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 -o "$work/$asset" "$base"
  echo "${TECTONIC_SHA256}  ${asset}" | (cd "$work" && sha256sum -c -)
  tar -xzf "$work/$asset" -C "$work"
  install -d -m 0755 "$INSTALL_DIR"
  install -m 0755 "$work/tectonic" "$INSTALL_DIR/tectonic-${TECTONIC_VERSION}"
  ln -sfn "$INSTALL_DIR/tectonic-${TECTONIC_VERSION}" "$BIN_PATH"
fi

command -v soffice >/dev/null 2>&1 || command -v libreoffice >/dev/null 2>&1
"$BIN_PATH" --version | grep -F "$TECTONIC_VERSION" >/dev/null
