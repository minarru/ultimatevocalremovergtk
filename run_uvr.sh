#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${HERE}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
INSTALLER="${HERE}/install_packages.sh"

# How to react when the venv is missing/stale (typically after a system Python
# or GTK upgrade orphaned it):
#   auto   - (default) rebuild inline when launched from a terminal; when
#            launched from the GUI (no TTY) show a message/notification instead
#            of silently pulling gigabytes with no visible progress.
#   always - rebuild inline unconditionally (handy for headless wrappers).
#   never  - only print the diagnostic and exit.
UVR_AUTO_REBUILD="${UVR_AUTO_REBUILD:-auto}"

# Ensure a desktop entry is installed so the Wayland/GNOME shell resolves the
# window's app id (org.uvr.UltimateVocalRemover) to the friendly application
# name and icon, instead of showing the raw app id in the dock/taskbar.
# Idempotent and best-effort: never block launching the app.
install_desktop_entry() {
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
Exec=${HERE}/run_uvr.sh
Icon=${HERE}/packaging/${app_id}.png
Terminal=false
Categories=AudioVideo;Audio;
Keywords=audio;vocal;stem;separation;karaoke;instrumental;
StartupNotify=true
StartupWMClass=${app_id}
"
    mkdir -p "${apps_dir}" || return 0
    # Only rewrite when missing or changed, to avoid needless disk churn.
    if [[ ! -f "${target}" ]] || [[ "$(cat "${target}" 2>/dev/null)" != "${desktop_contents}" ]]; then
        printf '%s' "${desktop_contents}" > "${target}" || return 0
        command -v update-desktop-database >/dev/null 2>&1 \
            && update-desktop-database "${apps_dir}" >/dev/null 2>&1 || true
    fi
}

# Probe the venv. Echoes a status and returns:
#   0 healthy
#   1 interpreter missing/dangling (e.g. base Python was removed by an upgrade)
#   2 stale: interpreter runs but GTK4/PyGObject can no longer be imported
venv_health() {
    # A dangling symlink (base interpreter deleted by a minor-version upgrade)
    # is not executable, so this also catches the most common breakage.
    [[ -x "${VENV_PYTHON}" ]] || return 1
    if [[ "${UVR_SKIP_CHECK:-0}" == "1" ]]; then
        return 0
    fi
    # With --system-site-packages the venv borrows the system PyGObject, which
    # lives under a version-specific path; a Python/GTK bump can hide it.
    "${VENV_PYTHON}" - >/dev/null 2>&1 <<'PY' || return 2
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw  # noqa: F401
PY
    return 0
}

gui_notify() {
    command -v notify-send >/dev/null 2>&1 \
        && notify-send "Ultimate Vocal Remover" "$1" >/dev/null 2>&1 || true
}

rebuild_venv() {
    if [[ ! -f "${INSTALLER}" ]]; then
        echo "Installer not found at ${INSTALLER}; cannot rebuild automatically." >&2
        return 1
    fi
    echo "Rebuilding the virtual environment via install_packages.sh (this can take a while) ..." >&2
    bash "${INSTALLER}"
}

ensure_venv() {
    if venv_health; then
        return 0
    fi
    local code=$?

    if [[ ${code} -eq 1 ]]; then
        if [[ -e "${VENV_DIR}/pyvenv.cfg" ]]; then
            echo "The virtual environment at ${VENV_DIR} is orphaned: its Python interpreter is gone." >&2
            echo "This usually means the system Python was upgraded (e.g. 3.14 -> 3.15) and the" >&2
            echo "interpreter the venv was built on was removed." >&2
        else
            echo "Virtual environment not found at ${VENV_DIR}." >&2
        fi
    else
        echo "The virtual environment at ${VENV_DIR} is stale: GTK4/PyGObject can no longer be imported." >&2
        echo "This usually follows a system Python or GTK/libadwaita upgrade." >&2
    fi
    echo "Fix: re-run ${INSTALLER}" >&2

    case "${UVR_AUTO_REBUILD}" in
        never)
            exit 1
            ;;
        always)
            rebuild_venv || exit 1
            ;;
        *)
            if [[ -t 0 && -t 1 ]]; then
                if [[ ${code} -eq 1 ]]; then
                    # Interpreter gone -> rebuild automatically, as requested.
                    rebuild_venv || exit 1
                else
                    local answer=""
                    read -r -p "Rebuild the environment now? [Y/n] " answer || true
                    if [[ "${answer}" =~ ^[Nn] ]]; then
                        exit 1
                    fi
                    rebuild_venv || exit 1
                fi
            else
                # GUI launch: avoid a silent multi-gigabyte reinstall with no
                # visible progress. Point the user at the installer instead.
                gui_notify "Python was updated. Open a terminal in the UVR folder and run ./install_packages.sh to repair the app."
                echo "Launched without a terminal; not rebuilding silently." >&2
                echo "Run ${INSTALLER} from a terminal, or set UVR_AUTO_REBUILD=always." >&2
                exit 1
            fi
            ;;
    esac

    # Re-verify after a rebuild attempt before continuing to launch.
    if ! venv_health; then
        echo "The environment is still not healthy after rebuilding. See output above." >&2
        exit 1
    fi
}

install_desktop_entry || true
ensure_venv

if [[ -n "${UVR_DEBUG:-}" ]]; then
    _uvr_debug_log="${UVR_DEBUG_LOG:-${XDG_CACHE_HOME:-${HOME}/.cache}/uvr/debug.log}"
    if pgrep -f "${VENV_PYTHON} -m ui" >/dev/null 2>&1; then
        echo "UVR is already running; this launch will exit immediately (single-instance app)." >&2
        echo "Quit the running instance first, or: tail -f ${_uvr_debug_log}" >&2
    else
        echo "UVR debug logging to: ${_uvr_debug_log}" >&2
    fi
fi

cd "${HERE}"
exec "${VENV_PYTHON}" -m ui "$@"
