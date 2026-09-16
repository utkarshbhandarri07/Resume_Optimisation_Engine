#!/usr/bin/env bash
# Idempotently provision the DOCX page-count renderer on Oracle Linux.
set -Eeuo pipefail

if ! command -v soffice >/dev/null 2>&1 && ! command -v libreoffice >/dev/null 2>&1; then
  dnf install -y libreoffice-headless
fi

command -v soffice >/dev/null 2>&1 || command -v libreoffice >/dev/null 2>&1
