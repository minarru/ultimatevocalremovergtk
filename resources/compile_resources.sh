#!/usr/bin/env bash
# Compile Blueprint layouts and bundle all application resources.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${HERE}/.." && pwd)"
ICONS_DIR="${HERE}/icons"
STYLE_CSS="${HERE}/style.css"
BLUEPRINT_DIR="${HERE}/ui"
XML="${HERE}/uvr.gresource.xml"
OUT_DIR="${REPO_ROOT}/ui/data"
OUT_BIN="${OUT_DIR}/uvr.gresource"
PREFIX="/org/uvr/UltimateVocalRemover"
BLUEPRINT_COMPILER="${BLUEPRINT_COMPILER:-blueprint-compiler}"

if ! command -v glib-compile-resources >/dev/null 2>&1; then
    echo "glib-compile-resources not found. Install glib2 (Arch/CachyOS) or libglib2.0-dev-bin (Debian/Ubuntu)." >&2
    exit 1
fi

if [[ "${BLUEPRINT_COMPILER}" == */* ]]; then
    if [[ ! -x "${BLUEPRINT_COMPILER}" ]]; then
        echo "Blueprint compiler not found or not executable: ${BLUEPRINT_COMPILER}" >&2
        exit 1
    fi
elif ! command -v "${BLUEPRINT_COMPILER}" >/dev/null 2>&1; then
    echo "Blueprint compiler not found: ${BLUEPRINT_COMPILER}" >&2
    echo "Install blueprint-compiler or set BLUEPRINT_COMPILER to its executable path." >&2
    exit 1
fi

if [[ ! -f "${ICONS_DIR}/index.theme" ]]; then
    echo "Missing ${ICONS_DIR}/index.theme" >&2
    exit 1
fi

if [[ ! -f "${STYLE_CSS}" ]]; then
    echo "Missing ${STYLE_CSS}" >&2
    exit 1
fi

APP_ICON_SRC="${REPO_ROOT}/packaging/org.uvr.UltimateVocalRemover.png"
APP_ICON_DEST="${ICONS_DIR}/hicolor/256x256/apps/org.uvr.UltimateVocalRemover.png"
if [[ -f "${APP_ICON_SRC}" ]]; then
    mkdir -p "$(dirname "${APP_ICON_DEST}")"
    cp -f "${APP_ICON_SRC}" "${APP_ICON_DEST}"
fi

mkdir -p "${OUT_DIR}"
STAGING_DIR="$(mktemp -d "${OUT_DIR}/.uvr-resources.XXXXXX")"
cleanup() {
    rm -rf -- "${STAGING_DIR}"
}
trap cleanup EXIT

compiler_version="$("${BLUEPRINT_COMPILER}" --version 2>/dev/null || true)"
echo "Using Blueprint compiler: ${BLUEPRINT_COMPILER}${compiler_version:+ (${compiler_version})}"

blueprints=()
while IFS= read -r -d '' file; do
    blueprints+=("${file}")
done < <(find "${BLUEPRINT_DIR}" -type f -name '*.blp' -print0 | sort -z)

if [[ ${#blueprints[@]} -eq 0 ]]; then
    echo "No Blueprint sources found under ${BLUEPRINT_DIR}" >&2
    exit 1
fi

for file in "${blueprints[@]}"; do
    rel="${file#${BLUEPRINT_DIR}/}"
    generated="${STAGING_DIR}/ui/${rel%.blp}.ui"
    mkdir -p "$(dirname -- "${generated}")"
    "${BLUEPRINT_COMPILER}" compile --output "${generated}" "${file}"
done

{
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo '<gresources>'
    echo "  <gresource prefix=\"${PREFIX}\">"
    echo "    <file>style.css</file>"
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
    for file in "${blueprints[@]}"; do
        rel="${file#${BLUEPRINT_DIR}/}"
        echo "    <file>ui/${rel%.blp}.ui</file>"
    done
    echo '  </gresource>'
    echo '</gresources>'
} > "${STAGING_DIR}/uvr.gresource.xml"

glib-compile-resources \
    --sourcedir="${STAGING_DIR}" \
    --sourcedir="${HERE}" \
    --target="${STAGING_DIR}/uvr.gresource" \
    "${STAGING_DIR}/uvr.gresource.xml"

# Publish generated XML only after every Blueprint and the completed bundle
# have compiled. The final rename keeps a previously working bundle intact on
# any compile failure above.
for file in "${blueprints[@]}"; do
    rel="${file#${BLUEPRINT_DIR}/}"
    generated="ui/${rel%.blp}.ui"
    destination="${HERE}/${generated}"
    mkdir -p "$(dirname -- "${destination}")"
    mv -f -- "${STAGING_DIR}/${generated}" "${destination}"
done
mv -f -- "${STAGING_DIR}/uvr.gresource.xml" "${XML}"
mv -f -- "${STAGING_DIR}/uvr.gresource" "${OUT_BIN}"

echo "Wrote ${OUT_BIN}"
