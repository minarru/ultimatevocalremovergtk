# Ultimate Vocal Remover — Linux (GTK4)

<img src="packaging/org.uvr.UltimateVocalRemover.png" alt="Ultimate Vocal Remover" width="128" />

Linux port of [Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui) with a **GTK4 / libadwaita** interface (PyGObject), built on the upstream **v5.6** codebase including **Apollo** restoration and **BS-Roformer / Mel-Band Roformer** support.

**Source:** [codeberg.org/jawlet/ultimatevocalremovergtk](https://codeberg.org/jawlet/ultimatevocalremovergtk)

## About

This application uses source-separation models to split audio into stems (vocals, instrumental, drums, bass, and more). UVR's core developers trained most of the models in the ecosystem (Demucs v3/v4 weights come from Meta's research release).

Supported separation backends in this port:

- **VR Architecture** — classic UVR models
- **MDX-Net** — including MDX23C and Roformer checkpoints (BS-Roformer, Mel-Band Roformer)
- **Demucs** — v2/v3/v4 multi-stem separation
- **Ensemble** — combine multiple models
- **Audio Tools** — time stretch, pitch shift, and **Apollo** music restoration

- **Original UVR developers**
  - [Anjok07](https://github.com/anjok07)
  - [aufr33](https://github.com/aufr33)
- **Support upstream UVR**
  - [Donate](https://www.buymeacoffee.com/uvr5)

## Requirements

- 64-bit Linux
- System Python **3.13+** (developed and tested on Python 3.14)
- System **PyGObject** with **GTK 4** and **libadwaita** (`gi`)
- **FFmpeg** — required for non-WAV input/output
- **Rubber Band CLI** — required for Time Stretch / Change Pitch
- Optional: [uv](https://docs.astral.sh/uv/) for faster installs or the Python 3.12 fallback path
- Optional: NVIDIA GPU with a working driver for GPU-accelerated MDX/ONNX inference (`./install_packages.sh --cuda`)

## Installation

### 1. Get the source

```bash
git clone https://codeberg.org/jawlet/ultimatevocalremovergtk.git
cd ultimatevocalremovergtk
```

Or download a source archive from the [Codeberg repository](https://codeberg.org/jawlet/ultimatevocalremovergtk).

### 2. Install system packages

Pick the command for your distribution (or run `./install_packages.sh --system-deps` to install them automatically):

**Debian / Ubuntu / Linux Mint**

```bash
sudo apt update
sudo apt install -y ffmpeg python3-venv python3-pip python3-gi gir1.2-gtk-4.0 \
    gir1.2-adw-1 libglib2.0-bin libsndfile1 rubberband-cli
```

**Fedora**

```bash
sudo dnf install -y ffmpeg python3-pip python3-gobject gtk4 libadwaita libsndfile rubberband
```

**Arch / CachyOS / EndeavourOS / Manjaro**

```bash
sudo pacman -Syu --needed ffmpeg python-pip python-virtualenv python-gobject gtk4 \
    libadwaita glib2 libsndfile rubberband
```

**openSUSE**

```bash
sudo zypper install -y ffmpeg python3-pip python3-gobject gtk4 libadwaita libsndfile1 rubberband
```

### 3. Install Python dependencies

The installer creates a `.venv` on the **system Python** with `--system-site-packages` so GTK4/libadwaita resolve from your distro, while the ML stack is installed via pip on top. This avoids modifying PEP 668–protected system Python packages.

```bash
./install_packages.sh
```

**NVIDIA GPU** (swaps in `onnxruntime-gpu` for MDX/ONNX):

```bash
./install_packages.sh --cuda
```

**Specific Python interpreter:**

```bash
./install_packages.sh --python /usr/bin/python3.14
```

**Fallback** — uv-managed Python 3.12 venv with pip-installed PyGObject (only if the system-Python path is unavailable):

```bash
./install_packages.sh --mode fallback --uv
```

Manual equivalent of the default path:

```bash
/usr/bin/python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

### 4. Run the application

```bash
./run_uvr.sh
```

Or, with the virtual environment activated:

```bash
source .venv/bin/activate
python -m uvr_gtk
```

`run_uvr.sh` also installs a desktop entry under `~/.local/share/applications/` on first launch. A template is provided at `packaging/org.uvr.UltimateVocalRemover.desktop`.

## Models

Most model **weights are not stored in git** (they are large binary files). The repository ships only bundled metadata and one small VR model:

| Shipped in git | Purpose |
|---|---|
| `models/*/model_data/*.json` | Model hash maps and parameters |
| `models/MDX_Net_Models/model_data/mdx_c_configs/*.yaml` | MDX-C / Roformer config templates |
| `models/Apollo_Models/model_configs/` and `model_data/` | Apollo recognition metadata |
| `models/VR_Models/UVR-DeNoise-Lite.pth` | Built-in denoiser (~17 MB) |

Everything else must be downloaded or placed manually:

1. Launch the app and open **Download Center** from the menu (or use the banner when no models are installed for the selected method).
2. Download the models you need for VR, MDX-Net, or Demucs.
3. For **Apollo** restoration, place checkpoint files (`.ckpt` or `.bin`) in `models/Apollo_Models/`.
4. **Roformer** checkpoints download like other MDX models; enable the *Roformer Model* flag in MDX-C model parameters when using them.

Downloaded weights are ignored by git (see `.gitignore`). Runtime data (settings, temp files) lives under the project directory in portable mode, or under `~/.local/share/ultimatevocalremover` when the install directory is read-only.

## Notes

- This port uses the **GTK4 / libadwaita** UI. The original Tkinter application is not included.
- Do **not** delete `/usr/lib/python*/EXTERNALLY-MANAGED`; that file protects your distro Python installation.
- Keep pip-installed dependencies inside the project `.venv` — avoid `sudo pip install`.
- If the environment breaks after a system Python or GTK upgrade, re-run `./install_packages.sh`. `run_uvr.sh` detects stale venvs and can rebuild them when launched from a terminal.
- GPU conversions generally need an NVIDIA GPU with sufficient VRAM (8 GB+ recommended). CPU inference works but is slower.
- Conversion time depends heavily on your hardware and the models selected.

## Troubleshooting

| Problem | What to try |
|---|---|
| FFmpeg errors on non-WAV files | Install `ffmpeg` and ensure it is on your `PATH` |
| Time Stretch / Pitch Shift unavailable | Install `rubberband-cli` |
| `gi` / GTK import errors | Install distro GTK4, libadwaita, and `python3-gi`; recreate the venv with `./install_packages.sh` |
| Out-of-memory during separation | Lower segment or window size in model settings |
| No models in a dropdown | Open **Download Center** and fetch models for that process method |
| Errors during processing | Open **Error Log** from the menu or press `Ctrl+E`; details are also shown in the log panel |

For distro-specific install issues, check upstream [GitHub Issues](https://github.com/Anjok07/ultimatevocalremovergui/issues) — many Linux dependency problems are shared between the original app and this port.

When reporting issues for **this GTK fork**, include your distribution, Python version, GPU (if any), the model and settings used, and the text from **Error Log**.

## License

Ultimate Vocal Remover is **MIT-licensed**. If you use UVR models or code in unrelated projects, please credit the UVR developers.

## Credits

- [ZFTurbo](https://github.com/ZFTurbo) — MDX23C model weights
- [DilanBoskan](https://github.com/DilanBoskan) — early project contributions
- [Bas Curtiz](https://www.youtube.com/user/bascurtiz) — UVR logo and branding
- [tsurumeso](https://github.com/tsurumeso) — original VR Architecture code
- [Kuielab & Woosung Choi](https://github.com/kuielab) — original MDX-Net code
- [Adefossez & Demucs](https://github.com/facebookresearch/demucs) — Demucs code and models
- [KimberleyJSN](https://github.com/KimberleyJensen) — MDX-Net and Demucs training scripts
- [Hv](https://github.com/NaJeongMo/Colab-for-MDX_B) — MDX-Net chunking implementation

## References

- Takahashi et al., ["Multi-scale Multi-band DenseNets for Audio Source Separation"](https://arxiv.org/pdf/1706.09588.pdf)
