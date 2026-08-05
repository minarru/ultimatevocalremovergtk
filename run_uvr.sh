#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${HERE}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
INSTALLER="${HERE}/install_packages.sh"
# Stamp written after a successful full GTK/Adw import probe. Invalidated when
# pyvenv.cfg is newer (venv rebuilt / Python bumped).
VENV_HEALTH_STAMP="${XDG_CACHE_HOME:-${HOME}/.cache}/uvr/venv_gtk_ok"

# How to react when the venv is missing/stale (typically after a system Python
# or GTK upgrade orphaned it):
#   auto   - (default) rebuild inline when launched from a terminal; when
#            launched from the GUI (no TTY) show a message/notification instead
#            of silently pulling gigabytes with no visible progress.
#   always - rebuild inline unconditionally (handy for headless wrappers).
#   never  - only print the diagnostic and exit.
UVR_AUTO_REBUILD="${UVR_AUTO_REBUILD:-auto}"

# shellcheck source=packaging/desktop_entry.sh
source "${HERE}/packaging/desktop_entry.sh"

write_venv_health_stamp() {
    mkdir -p "$(dirname -- "${VENV_HEALTH_STAMP}")" || return 0
    : > "${VENV_HEALTH_STAMP}" || true
}

clear_venv_health_stamp() {
    rm -f "${VENV_HEALTH_STAMP}" || true
}

# Return 0 when a full GTK/Adw import probe should run.
gtk_probe_needed() {
    if [[ "${UVR_FORCE_VENV_CHECK:-0}" == "1" ]]; then
        return 0
    fi
    local cfg="${VENV_DIR}/pyvenv.cfg"
    [[ -f "${VENV_HEALTH_STAMP}" ]] || return 0
    [[ -f "${cfg}" ]] || return 0
    # -ot: stamp older than pyvenv.cfg → venv was (re)created since last probe.
    if [[ "${VENV_HEALTH_STAMP}" -ot "${cfg}" ]]; then
        return 0
    fi
    return 1
}

# Probe the venv. Returns:
#   0 healthy
#   1 interpreter missing/dangling (e.g. base Python was removed by an upgrade)
#   2 stale: interpreter runs but GTK4/PyGObject can no longer be imported
#
# Default hot path: executable check only (~1 ms). A full GTK import probe
# (~80 ms, separate process) runs when the stamp is missing/stale, after a
# rebuild, or when UVR_FORCE_VENV_CHECK=1. UVR_SKIP_CHECK=1 skips the probe
# entirely (stamp untouched).
venv_health() {
    # A dangling symlink (base interpreter deleted by a minor-version upgrade)
    # is not executable, so this also catches the most common breakage.
    [[ -x "${VENV_PYTHON}" ]] || return 1
    if [[ "${UVR_SKIP_CHECK:-0}" == "1" ]]; then
        return 0
    fi
    if ! gtk_probe_needed; then
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
    write_venv_health_stamp
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
    clear_venv_health_stamp
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
    # Stamp was cleared; force a full probe regardless of other env.
    UVR_FORCE_VENV_CHECK=1
    if ! venv_health; then
        echo "The environment is still not healthy after rebuilding. See output above." >&2
        exit 1
    fi
}

# Hot path: create the .desktop only when missing. Full rewrite happens from
# install_packages.sh (--update).
install_desktop_entry || true
ensure_venv

if [[ -n "${G_MESSAGES_DEBUG:-}" ]]; then
    # Expand UVR shorthands (e.g. uvr -> uvr-ui uvr-worker …) before Python loads GLib.
    G_MESSAGES_DEBUG="$(
        cd "${HERE}" && "${VENV_PYTHON}" -c "
from core.debug_log import normalize_g_messages_debug_env
import os
normalize_g_messages_debug_env()
print(os.environ.get('G_MESSAGES_DEBUG', ''))
" 2>/dev/null || echo "${G_MESSAGES_DEBUG}"
    )"
    export G_MESSAGES_DEBUG
fi

if [[ -n "${G_MESSAGES_DEBUG:-}" || -n "${UVR_LOG_FILE:-}" || -n "${UVR_VERBOSE:-}" ]]; then
    if pgrep -f "${VENV_PYTHON} -m ui" >/dev/null 2>&1; then
        echo "UVR is already running; this launch will exit immediately (single-instance app)." >&2
        if [[ -n "${UVR_LOG_FILE:-}" ]]; then
            echo "Quit the running instance first, or: tail -f ${UVR_LOG_FILE}" >&2
        else
            echo "Quit the running instance first, or use: journalctl --user -f" >&2
        fi
    elif [[ -n "${UVR_LOG_FILE:-}" ]]; then
        echo "UVR debug log file: ${UVR_LOG_FILE}" >&2
    elif [[ -n "${UVR_VERBOSE:-}" ]]; then
        echo "UVR high-frequency trace: UVR_VERBOSE=${UVR_VERBOSE}" >&2
    elif [[ -n "${G_MESSAGES_DEBUG:-}" ]]; then
        echo "UVR GLib debug domains: G_MESSAGES_DEBUG=${G_MESSAGES_DEBUG}" >&2
    fi
fi

cd "${HERE}"
exec "${VENV_PYTHON}" -m ui "$@"
