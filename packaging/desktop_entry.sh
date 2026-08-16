#!/usr/bin/env bash
# Shared desktop-entry helper for install_packages.sh and run_uvr.sh.
#
# Requires HERE to be set to the project root before sourcing.
# Usage:
#   install_desktop_entry            # create only when missing (launch hot path)
#   install_desktop_entry --update   # rewrite when missing or contents changed

install_desktop_entry() {
    local update=0
    if [[ "${1:-}" == "--update" ]]; then
        update=1
    fi
    local app_id="org.uvr.UltimateVocalRemover"
    local data_home="${XDG_DATA_HOME:-${HOME}/.local/share}"
    local apps_dir="${data_home}/applications"
    local target="${apps_dir}/${app_id}.desktop"
    local desktop_contents
    desktop_contents="[Desktop Entry]
Type=Application
Version=1.0
Name=Ultimate Vocal Remover
GenericName=Vocal Remover
Comment=Separate vocals and instruments from audio using AI models
Exec=${HERE}/uvr gui
Icon=${HERE}/packaging/${app_id}.png
Terminal=false
Categories=AudioVideo;Audio;
Keywords=audio;vocal;stem;separation;karaoke;instrumental;
StartupNotify=true
StartupWMClass=${app_id}
"
    mkdir -p "${apps_dir}" || return 0
    if [[ -f "${target}" ]]; then
        if [[ "${update}" -eq 0 ]]; then
            return 0
        fi
        if [[ "$(cat "${target}" 2>/dev/null)" == "${desktop_contents}" ]]; then
            return 0
        fi
    fi
    printf '%s' "${desktop_contents}" > "${target}" || return 0
    command -v update-desktop-database >/dev/null 2>&1 \
        && update-desktop-database "${apps_dir}" >/dev/null 2>&1 || true
}
