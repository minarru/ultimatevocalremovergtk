#!/usr/bin/env bash
# Bundle resources/icons/ into uvr_gtk/data/uvr.gresource for Gtk.IconTheme.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${HERE}/.." && pwd)"
ICONS_DIR="${HERE}/icons"
XML="${HERE}/uvr.gresource.xml"
OUT_DIR="${REPO_ROOT}/uvr_gtk/data"
OUT_BIN="${OUT_DIR}/uvr.gresource"
PREFIX="/org/uvr/UltimateVocalRemover"

if ! command -v glib-compile-resources >/dev/null 2>&1; then
    echo "glib-compile-resources not found. Install glib2 (Arch/CachyOS) or libglib2.0-bin (Debian/Ubuntu)." >&2
    exit 1
fi

if [[ ! -f "${ICONS_DIR}/index.theme" ]]; then
    echo "Missing ${ICONS_DIR}/index.theme" >&2
    exit 1
fi

APP_ICON_SRC="${REPO_ROOT}/packaging/org.uvr.UltimateVocalRemover.png"
APP_ICON_DEST="${ICONS_DIR}/hicolor/256x256/apps/org.uvr.UltimateVocalRemover.png"
if [[ -f "${APP_ICON_SRC}" ]]; then
    mkdir -p "$(dirname "${APP_ICON_DEST}")"
    cp -f "${APP_ICON_SRC}" "${APP_ICON_DEST}"
fi

mkdir -p "${OUT_DIR}"

{
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo '<gresources>'
    echo "  <gresource prefix=\"${PREFIX}\">"
    while IFS= read -r -d '' file; do
        rel="${file#${ICONS_DIR}/}"
        case "${rel}" in
            README*|*.md|.gitkeep|index.theme) continue ;;
        esac
        case "${rel}" in
            *.svg) preprocess=' preprocess="xml-stripblanks"' ;;
            *) preprocess="" ;;
        esac
        echo "    <file${preprocess}>icons/${rel}</file>"
    done < <(find "${ICONS_DIR}" -type f -print0 | sort -z)
    echo '  </gresource>'
    echo '</gresources>'
} > "${XML}"

glib-compile-resources \
    --sourcedir="${HERE}" \
    --target="${OUT_BIN}" \
    "${XML}"

echo "Wrote ${OUT_BIN}"
