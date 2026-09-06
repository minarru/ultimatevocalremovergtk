#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${UVR_VENV_DIR:-${PROJECT_ROOT}/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PYTHON_EXPLICIT=0
UV_PYTHON_VERSION="${UVR_PYTHON_VERSION:-3.12}"
USE_UV="auto"
INSTALL_SYSTEM_DEPS=0
GPU_BACKEND="cpu"

# Preserve the original invocation so we can re-exec ourselves as the non-root
# user after handling the (root-only) system-package step. See the privilege
# drop below.
ORIG_ARGS=("$@")

# Install mode (the GTK4/libadwaita app is Linux-only):
#   system   - Option B (default, recommended): create the venv on the SYSTEM
#              Python (3.13+, e.g. 3.14) with --system-site-packages so gi/GTK4/
#              libadwaita come from the system packages, then pip-install the ML
#              stack on top. No pip-build of PyGObject.
#   fallback - Option A: a uv-managed Python 3.12 venv that pip-installs PyGObject
#              against the system girepository, pointing GI_TYPELIB_PATH at the
#              system typelibs. Same UI code; only the env bootstrap differs.
INSTALL_MODE="${UVR_INSTALL_MODE:-system}"
SYSTEM_PYTHON_BIN="${UVR_SYSTEM_PYTHON:-/usr/bin/python3}"

usage() {
    cat <<'EOF'
Usage: ./install_packages.sh [options]

Sets up the environment for the GTK4 / libadwaita Ultimate Vocal Remover app
(Linux-only). After it finishes, run the app with:  python -m ui

Options:
  --mode MODE         Install mode: 'system' (Option B, default) builds the venv
                      on the system Python with --system-site-packages so GTK4/
                      libadwaita resolve from the system; 'fallback' (Option A)
                      uses a uv-managed Python 3.12 venv + pip PyGObject.
  --system-deps       Install Linux system packages with the detected package manager.
  --cuda              Replace CPU ONNX Runtime with onnxruntime-gpu after installing requirements.
  --uv                Use uv to install/manage Python and dependencies.
  --no-uv             Disable uv auto-detection and use python/pip directly.
  --python-version X  Python version for uv-managed (fallback) installs. Default: 3.12
  --venv DIR          Virtual environment directory. Default: ./.venv
  --python PATH       Python executable to use. In 'system' mode this is the
                      system interpreter to base the venv on. Default: python3
  -h, --help          Show this help.

Environment:
  UVR_VENV_DIR        Alternative venv directory.
  PYTHON_BIN          Alternative Python executable.
  UVR_PYTHON_VERSION  Python version for uv-managed installs.
  UVR_INSTALL_MODE    Default install mode: system (default) or fallback.
  UVR_SYSTEM_PYTHON   System interpreter for 'system' mode. Default: /usr/bin/python3

Notes:
  Run this as your normal user. It uses sudo only for the system-package step.
  If launched with sudo, it installs system packages as root and then re-runs
  the rest as the invoking user so the virtual environment is user-owned (a
  leftover root-owned .venv from a previous run is removed and recreated).
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            INSTALL_MODE="$2"
            shift 2
            ;;
        --system-deps)
            INSTALL_SYSTEM_DEPS=1
            shift
            ;;
        --cuda)
            GPU_BACKEND="cuda"
            shift
            ;;
        --uv)
            USE_UV="yes"
            shift
            ;;
        --no-uv)
            USE_UV="no"
            shift
            ;;
        --python-version)
            UV_PYTHON_VERSION="$2"
            shift 2
            ;;
        --venv)
            VENV_DIR="$2"
            shift 2
            ;;
        --python)
            PYTHON_BIN="$2"
            PYTHON_EXPLICIT=1
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

# System packages: GTK4 + libadwaita + PyGObject for the UI, plus the audio
# runtime deps (ffmpeg, libsndfile, rubberband) the ML stack shells out to.
install_system_deps() {
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y ffmpeg python3-venv python3-pip python3-gi \
            gir1.2-gtk-4.0 gir1.2-adw-1 libglib2.0-bin blueprint-compiler \
            libsndfile1 rubberband-cli
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y ffmpeg python3-pip python3-gobject gtk4 libadwaita \
            blueprint-compiler libsndfile rubberband
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -Syu --needed ffmpeg python-pip python-virtualenv python-gobject \
            gtk4 libadwaita glib2 blueprint-compiler libsndfile rubberband
    elif command -v zypper >/dev/null 2>&1; then
        sudo zypper install -y ffmpeg python3-pip python3-gobject gtk4 libadwaita \
            blueprint-compiler libsndfile1 rubberband
    else
        echo "Unsupported package manager. Install ffmpeg, Python venv/pip, GTK4," >&2
        echo "libadwaita, PyGObject, blueprint-compiler, libsndfile, and rubberband manually." >&2
        exit 1
    fi
}

# Compile Blueprint layouts and bundle resources into ui/data/uvr.gresource.
compile_gresources() {
    local script="${PROJECT_ROOT}/resources/compile_resources.sh"
    if [[ ! -x "${script}" ]]; then
        chmod +x "${script}" 2>/dev/null || true
    fi
    if [[ ! -x "${script}" ]]; then
        echo "Resource compiler not found or not executable: ${script}" >&2
        return 1
    fi
    "${script}"
}

# Owning user of the venv directory (empty if it doesn't exist / can't stat).
venv_owner() {
    stat -c '%U' "${VENV_DIR}" 2>/dev/null || true
}

# Ensure the venv dir, if it already exists, is owned by the current user before
# we (re)create it. A leftover root-owned venv (e.g. from an earlier `sudo`
# install) is removed - with root if we have it, otherwise via sudo - so the
# recreation below is cleanly owned by the human user running the app.
prepare_venv_dir() {
    [[ -e "${VENV_DIR}" ]] || return 0
    local owner me
    owner="$(venv_owner)"
    me="$(id -un)"
    [[ -z "${owner}" || "${owner}" == "${me}" ]] && return 0
    echo "The venv at ${VENV_DIR} is owned by '${owner}', not the current user '${me}'." >&2
    echo "Removing it so it can be recreated with correct ownership ..." >&2
    if [[ ${EUID} -eq 0 ]]; then
        rm -rf "${VENV_DIR}"
    elif command -v sudo >/dev/null 2>&1; then
        sudo rm -rf "${VENV_DIR}"
    else
        echo "Cannot remove a foreign-owned venv without root. Run: sudo rm -rf '${VENV_DIR}'" >&2
        exit 1
    fi
}

if [[ "${INSTALL_MODE}" != "system" && "${INSTALL_MODE}" != "fallback" ]]; then
    echo "Invalid --mode '${INSTALL_MODE}'. Use 'system' or 'fallback'." >&2
    exit 2
fi

# A re-exec after the privilege drop already installed system packages as root.
if [[ "${UVR_SKIP_SYSTEM_DEPS:-0}" == "1" ]]; then
    INSTALL_SYSTEM_DEPS=0
fi

# Keep the venv owned by the human user. Only OS package installation needs root
# (handled via sudo inside install_system_deps), so when this script is run as
# root (e.g. `sudo ./install_packages.sh`), do that one step here and then
# re-exec the rest as the invoking user so the venv + pip installs are NOT
# root-owned. A real root login (no SUDO_USER) is warned about and proceeds.
if [[ ${EUID} -eq 0 && "${UVR_PRIVDROP_DONE:-0}" != "1" ]]; then
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        if [[ "${INSTALL_SYSTEM_DEPS}" -eq 1 ]]; then
            install_system_deps
        fi
        # Drop a stale venv not owned by the target user while we still have root
        # (avoids a later sudo password prompt once privileges are dropped).
        if [[ -e "${VENV_DIR}" && "$(venv_owner)" != "${SUDO_USER}" ]]; then
            echo "Removing root/foreign-owned venv at ${VENV_DIR} ..." >&2
            rm -rf "${VENV_DIR}"
        fi
        echo "Re-running as '${SUDO_USER}' so the virtual environment is user-owned ..." >&2
        exec sudo -u "${SUDO_USER}" -H env UVR_PRIVDROP_DONE=1 UVR_SKIP_SYSTEM_DEPS=1 \
            bash -lc 'exec "$0" "$@"' "$(readlink -f "${BASH_SOURCE[0]}")" "${ORIG_ARGS[@]}"
    else
        echo "warning: running as root. The virtual environment will be root-owned," >&2
        echo "         which prevents the app (run as your user) from updating it." >&2
        echo "         Prefer running this script as your normal user; it uses sudo" >&2
        echo "         only for system packages." >&2
    fi
fi

if [[ "${INSTALL_SYSTEM_DEPS}" -eq 1 ]]; then
    install_system_deps
fi

compile_gresources

# Recreate cleanly if a previous install left a foreign-owned venv behind.
prepare_venv_dir

# Validate the uv-managed interpreter used for fallback (Option A) installs.
validate_python() {
    "$1" - <<'PY'
import sys
if sys.version_info < (3, 10) or sys.version_info >= (3, 13):
    raise SystemExit("The fallback (uv) path expects Python >=3.10 and <3.13.")
PY
}

# Validate the interpreter used for 'system' (Option B) installs. The GTK4 UI
# targets the system Python (3.13+, e.g. 3.14) that ships system PyGObject; the
# ML stack only needs Python >=3.10.
validate_system_python() {
    "$1" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("UVR requires Python >= 3.10.")
if sys.version_info < (3, 13):
    print("warning: the GTK4 app targets system Python 3.13+ (e.g. 3.14); "
          f"found {sys.version.split()[0]}.", file=sys.stderr)
PY
}

# CPU `onnxruntime` and GPU `onnxruntime-gpu` both unpack into the same
# site-packages/onnxruntime/ tree. Uninstalling only the CPU distribution
# deletes the Python API (InferenceSession) while leaving onnxruntime-gpu
# metadata satisfied, so a later `pip install -r requirements-cuda-linux.txt`
# is a no-op and import fails with:
#   cannot import name 'InferenceSession' from 'onnxruntime' (unknown location)
install_onnxruntime_cuda() {
    local venv_python="$1"
    echo "Replacing CPU ONNX Runtime with onnxruntime-gpu ..."
    if [[ "${use_uv}" -eq 1 ]]; then
        uv pip uninstall --python "${venv_python}" onnxruntime onnxruntime-gpu || true
    else
        "${venv_python}" -m pip uninstall -y onnxruntime onnxruntime-gpu || true
    fi
    local site
    site="$("${venv_python}" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
    rm -rf "${site}/onnxruntime"
    if [[ "${use_uv}" -eq 1 ]]; then
        uv pip install --python "${venv_python}" -r "${PROJECT_ROOT}/requirements-cuda-linux.txt"
    else
        "${venv_python}" -m pip install -r "${PROJECT_ROOT}/requirements-cuda-linux.txt"
    fi
    echo "Verifying onnxruntime ..."
    "${venv_python}" - <<'PY'
from onnxruntime import InferenceSession  # noqa: F401
import onnxruntime as ort
print(f"  onnxruntime: {ort.__file__}")
print(f"  providers: {ort.get_available_providers()}")
PY
}

# Smoke-check that gi + GTK 4.0 + Adw 1 import and print their versions. Fatal in
# 'system' mode (the whole point of Option B), advisory otherwise.
gtk_smoke_check() {
    local venv_python="$1"
    local fatal="${2:-0}"
    echo "Verifying GTK4 / libadwaita availability ..."
    if "${venv_python}" - <<'PY'
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
print(f"  gi (PyGObject): {gi.__version__}")
print(f"  GTK: {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}")
print(f"  libadwaita: {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}")
PY
    then
        echo "GTK4 / libadwaita import OK."
    else
        echo "GTK4 / libadwaita could not be imported." >&2
        echo "Install the system packages (e.g. on Arch: gtk4 libadwaita python-gobject;" >&2
        echo "on Debian/Ubuntu: gir1.2-gtk-4.0 gir1.2-adw-1 python3-gi) and ensure the venv" >&2
        echo "was created with --system-site-packages (system mode) or that GI_TYPELIB_PATH" >&2
        echo "points at the system typelibs (fallback mode)." >&2
        [[ "${fatal}" -eq 1 ]] && exit 1
        return 1
    fi
}

# Fallback (Option A) only: pip-install PyGObject into the uv-managed venv built
# against the system girepository, and surface the GI_TYPELIB_PATH the app needs
# at runtime to find the system GTK4/libadwaita typelibs.
install_pygobject_fallback() {
    local venv_python="$1"
    echo "Installing PyGObject into the fallback venv (building against system girepository) ..."
    if [[ "${use_uv}" -eq 1 ]]; then
        uv pip install --python "${venv_python}" pygobject || \
            echo "warning: PyGObject build failed; install girepository/cairo dev headers and retry." >&2
    else
        "${venv_python}" -m pip install pygobject || \
            echo "warning: PyGObject build failed; install girepository/cairo dev headers and retry." >&2
    fi

    local typelibdir=""
    if command -v pkg-config >/dev/null 2>&1; then
        typelibdir="$(pkg-config --variable=typelibdir gobject-introspection-1.0 2>/dev/null || true)"
    fi
    [[ -z "${typelibdir}" && -d /usr/lib/girepository-1.0 ]] && typelibdir="/usr/lib/girepository-1.0"
    if [[ -n "${typelibdir}" ]]; then
        echo "Fallback runtime needs the system typelibs on GI_TYPELIB_PATH:"
        echo "  export GI_TYPELIB_PATH=\"${typelibdir}\""
        FALLBACK_TYPELIB_HINT="${typelibdir}"
    fi
}

use_uv=0
if [[ "${USE_UV}" == "yes" ]]; then
    use_uv=1
elif [[ "${USE_UV}" == "auto" && "${PYTHON_EXPLICIT}" -eq 0 ]] && command -v uv >/dev/null 2>&1; then
    use_uv=1
fi

FALLBACK_TYPELIB_HINT=""

if [[ "${INSTALL_MODE}" == "system" ]]; then
    # Option B (default): system Python + --system-site-packages venv so gi/GTK4/
    # libadwaita resolve from the system packages; pip-install the ML stack on top.
    if [[ "${PYTHON_EXPLICIT}" -eq 1 ]]; then
        SYSTEM_PYTHON_BIN="${PYTHON_BIN}"
    fi
    if [[ ! -x "${SYSTEM_PYTHON_BIN}" ]] && ! command -v "${SYSTEM_PYTHON_BIN}" >/dev/null 2>&1; then
        echo "System Python '${SYSTEM_PYTHON_BIN}' not found. Set UVR_SYSTEM_PYTHON or pass --python." >&2
        exit 1
    fi
    validate_system_python "${SYSTEM_PYTHON_BIN}"

    "${SYSTEM_PYTHON_BIN}" -m venv --system-site-packages "${VENV_DIR}"
    VENV_PYTHON="${VENV_DIR}/bin/python"

    if [[ "${use_uv}" -eq 1 ]]; then
        uv pip install --python "${VENV_PYTHON}" --upgrade pip setuptools wheel
        uv pip install --python "${VENV_PYTHON}" -r "${PROJECT_ROOT}/requirements.txt"
    else
        "${VENV_PYTHON}" -m pip install --upgrade pip setuptools wheel
        "${VENV_PYTHON}" -m pip install -r "${PROJECT_ROOT}/requirements.txt"
    fi

    if [[ "${GPU_BACKEND}" == "cuda" ]]; then
        install_onnxruntime_cuda "${VENV_PYTHON}"
    fi

    gtk_smoke_check "${VENV_PYTHON}" 1

    cat <<EOF

UVR dependencies installed (system mode / Option B).

Activate the environment:
  source "${VENV_DIR}/bin/activate"

Run the GTK4 app:
  python -m ui
EOF
else
    # Option A (fallback): uv-managed Python 3.12 venv + pip PyGObject against the
    # system girepository. No Tk machinery -- the app is GTK4 only.
    if [[ "${use_uv}" -eq 1 ]]; then
        if ! command -v uv >/dev/null 2>&1; then
            echo "uv was requested but is not installed. Install uv or rerun with --no-uv." >&2
            exit 1
        fi

        uv python install "${UV_PYTHON_VERSION}"
        UV_PYTHON="$(uv python find "${UV_PYTHON_VERSION}")"
        validate_python "${UV_PYTHON}"
        uv venv --python "${UV_PYTHON}" "${VENV_DIR}"
        VENV_PYTHON="${VENV_DIR}/bin/python"

        uv pip install --python "${VENV_PYTHON}" -r "${PROJECT_ROOT}/requirements.txt"

        if [[ "${GPU_BACKEND}" == "cuda" ]]; then
            install_onnxruntime_cuda "${VENV_PYTHON}"
        fi
    else
        validate_python "${PYTHON_BIN}"

        "${PYTHON_BIN}" -m venv "${VENV_DIR}"
        VENV_PYTHON="${VENV_DIR}/bin/python"
        # shellcheck disable=SC1091
        source "${VENV_DIR}/bin/activate"

        python -m pip install --upgrade pip setuptools wheel
        python -m pip install -r "${PROJECT_ROOT}/requirements.txt"

        if [[ "${GPU_BACKEND}" == "cuda" ]]; then
            install_onnxruntime_cuda "${VENV_PYTHON}"
        fi
    fi

    install_pygobject_fallback "${VENV_PYTHON:-${VENV_DIR}/bin/python}"

    if [[ -n "${FALLBACK_TYPELIB_HINT}" ]]; then
        GI_TYPELIB_PATH="${FALLBACK_TYPELIB_HINT}" gtk_smoke_check "${VENV_PYTHON:-${VENV_DIR}/bin/python}" 0 || true
    else
        gtk_smoke_check "${VENV_PYTHON:-${VENV_DIR}/bin/python}" 0 || true
    fi

    cat <<EOF

UVR dependencies installed (fallback mode / Option A).

Activate the environment:
  source "${VENV_DIR}/bin/activate"
EOF
    if [[ -n "${FALLBACK_TYPELIB_HINT}" ]]; then
        cat <<EOF

The GTK4 app needs the system typelibs on GI_TYPELIB_PATH in this mode:
  export GI_TYPELIB_PATH="${FALLBACK_TYPELIB_HINT}"
EOF
    fi
    cat <<EOF

Run the GTK4 app:
  python -m ui
EOF
fi

# Keep the .desktop entry in sync after a successful install (full rewrite).
# run_uvr.sh only creates it when missing, to keep the launch hot path cheap.
HERE="${PROJECT_ROOT}"
# shellcheck source=packaging/desktop_entry.sh
source "${PROJECT_ROOT}/packaging/desktop_entry.sh"
install_desktop_entry --update || true

# Install the source-tree CLI launcher without replacing an unrelated command.
_uvr_user_bin="${HOME}/.local/bin"
_uvr_cli_target="${_uvr_user_bin}/uvr"
_uvr_cli_source="${PROJECT_ROOT}/uvr"
mkdir -p "${_uvr_user_bin}" 2>/dev/null || true
if [[ -L "${_uvr_cli_target}" && "$(readlink "${_uvr_cli_target}")" == "${_uvr_cli_source}" ]]; then
    : # already installed
elif [[ -e "${_uvr_cli_target}" || -L "${_uvr_cli_target}" ]]; then
    echo "Not replacing existing command at ${_uvr_cli_target}; use ${_uvr_cli_source} directly." >&2
else
    ln -s "${_uvr_cli_source}" "${_uvr_cli_target}" 2>/dev/null || true
fi

# Seed the launcher health stamp so the first post-install run_uvr.sh launch
# does not repeat the GTK import probe install already performed.
_stamp_dir="${XDG_CACHE_HOME:-${HOME}/.cache}/uvr"
mkdir -p "${_stamp_dir}" 2>/dev/null || true
: > "${_stamp_dir}/venv_gtk_ok" 2>/dev/null || true
