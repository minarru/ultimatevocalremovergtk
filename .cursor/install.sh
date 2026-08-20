#!/usr/bin/env bash
# Cloud Agent install: idempotent bootstrap for the GTK4/libadwaita UVR port.
#
# Layers:
#   1. System packages (apt): GTK4 + libadwaita + PyGObject typelibs for the UI,
#      the audio runtime tools the ML stack shells out to (ffmpeg, rubberband,
#      libsndfile), the C toolchain + Python headers that a couple of sdist-only
#      wheels compile against (diffq), Xvfb for headless GTK tests, and
#      glib-compile-resources for the icon bundle.
#   2. A --system-site-packages venv on the system Python so gi/GTK4/libadwaita
#      resolve from the distro (matches install_packages.sh / CI), then the
#      pinned ML + dev + type-stub dependencies on top via pip.
#   3. The compiled GResource bundle (ui/data/uvr.gresource).
#
# Safe to re-run: apt install and venv creation converge, pip is pinned.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

VENV_DIR="${REPO_ROOT}/.venv"
SYSTEM_PYTHON="${UVR_SYSTEM_PYTHON:-/usr/bin/python3}"

echo "==> Installing system dependencies (GTK4, libadwaita, audio tools, build deps)"
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    python3-venv python3-pip python3-dev python3-gi \
    build-essential \
    gir1.2-gtk-4.0 gir1.2-adw-1 \
    libglib2.0-bin libsndfile1 \
    ffmpeg rubberband-cli \
    xvfb

echo "==> Creating --system-site-packages venv at ${VENV_DIR}"
"${SYSTEM_PYTHON}" -m venv --system-site-packages "${VENV_DIR}"
VENV_PYTHON="${VENV_DIR}/bin/python"

echo "==> Installing pinned Python dependencies"
# setuptools is pinned in requirements.txt; only bootstrap pip + wheel here so
# the two steps do not fight over the setuptools version on repeat runs.
"${VENV_PYTHON}" -m pip install --upgrade pip wheel
"${VENV_PYTHON}" -m pip install -r "${REPO_ROOT}/requirements.txt"
"${VENV_PYTHON}" -m pip install -r "${REPO_ROOT}/requirements-dev.txt"
# Type stubs are a deliberate --no-deps install: PyGObject-stubs declares a
# runtime dep on PyGObject that would otherwise build from source. See
# requirements-stubs.txt.
"${VENV_PYTHON}" -m pip install --no-deps -r "${REPO_ROOT}/requirements-stubs.txt"

echo "==> Compiling GResource icon bundle"
"${REPO_ROOT}/resources/compile_resources.sh"

echo "==> Verifying GTK4 / libadwaita + ML stack import"
"${VENV_PYTHON}" - <<'PY'
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
import torch, numpy, onnxruntime, librosa  # noqa: F401
print(f"  GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}  "
      f"Adw {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}  "
      f"torch {torch.__version__}  numpy {numpy.__version__}  ort {onnxruntime.__version__}")
PY

echo "==> UVR Cloud Agent environment ready."
echo "    Tests:      GSK_RENDERER=cairo xvfb-run -a .venv/bin/python -m unittest discover -s tests"
echo "    Typecheck:  .venv/bin/python -m basedpyright"
echo "    CLI:        PYTHONPATH=\$PWD .venv/bin/python -m cli models list"
echo "    GUI:        GSK_RENDERER=cairo .venv/bin/python -m ui"
