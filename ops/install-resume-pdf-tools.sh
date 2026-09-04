#!/usr/bin/env bash
# Idempotently provision the fixed-page resume rendering tools on Oracle Linux.
set -Eeuo pipefail

TECTONIC_VERSION="0.16.9"
INSTALL_DIR="/usr/local/lib/resume-optimizer"
BIN_PATH="/usr/local/bin/tectonic"

if ! command -v soffice >/dev/null 2>&1 && ! command -v libreoffice >/dev/null 2>&1; then
  dnf install -y libreoffice-headless
fi

if [[ ! -x "$BIN_PATH" ]] || [[ "$($BIN_PATH --version 2>/dev/null || true)" != *"$TECTONIC_VERSION"* ]]; then
  asset="tectonic-${TECTONIC_VERSION}-x86_64-unknown-linux-gnu.tar.gz"
  base="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/${asset}"
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 -o "$work/$asset" "$base"
  # Tectonic publishes a checksum alongside the pinned release asset. Refuse an
  # unverified binary rather than silently accepting a changed download.
  curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 -o "$work/$asset.sha256" "$base.sha256"
  (cd "$work" && sha256sum -c "$asset.sha256")
  tar -xzf "$work/$asset" -C "$work"
  install -d -m 0755 "$INSTALL_DIR"
  install -m 0755 "$work/tectonic" "$INSTALL_DIR/tectonic-${TECTONIC_VERSION}"
  ln -sfn "$INSTALL_DIR/tectonic-${TECTONIC_VERSION}" "$BIN_PATH"
fi

command -v soffice >/dev/null 2>&1 || command -v libreoffice >/dev/null 2>&1
"$BIN_PATH" --version | grep -F "$TECTONIC_VERSION" >/dev/null
