# Ultimate Vocal Remover — Linux (GTK4)

<img src="packaging/org.uvr.UltimateVocalRemover.png" alt="Ultimate Vocal Remover" width="128" />

Linux port of [Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui) with a **GTK4 / libadwaita** interface (PyGObject). **GTK release v1.0.0**, based on upstream **v5.6**, including **Apollo** restoration and **BS-Roformer / Mel-Band Roformer** support.

**Source:** [github.com/minarru/ultimatevocalremovergtk](https://github.com/minarru/ultimatevocalremovergtk) · **Releases:** [github.com/minarru/ultimatevocalremovergtk/releases](https://github.com/minarru/ultimatevocalremovergtk/releases)

Report bugs and open pull requests on **GitHub**. The former Codeberg repo is archived — see [docs/mirroring.md](docs/mirroring.md).

## About

This application uses source-separation models to split audio into stems (vocals, instrumental, drums, bass, and more). UVR's core developers trained most of the models in the ecosystem (Demucs v3/v4 weights come from Meta's research release).

Supported separation backends in this port:

- **VR Architecture** — classic UVR models
- **MDX-Net** — including MDX23C, Roformer, **SCNet**, and **Bandit** checkpoints
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
git clone https://github.com/minarru/ultimatevocalremovergtk.git
cd ultimatevocalremovergtk
```

Or download a source archive from the [GitHub repository](https://github.com/minarru/ultimatevocalremovergtk).

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

**NVIDIA GPU** (installs `requirements-cuda-linux.txt` — ONNX GPU + CUDA wheels):

```bash
./install_packages.sh --cuda
```

Windows optional overlays: `requirements-cuda-windows.txt`, `requirements-directml.txt`.

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
python -m ui
```

`run_uvr.sh` also installs a desktop entry under `~/.local/share/applications/` on first launch. A template is provided at `packaging/org.uvr.UltimateVocalRemover.desktop`.

### Command-line interface

The installer adds the source-tree `uvr` launcher to `~/.local/bin` when that
name is available. The launcher uses the project virtual environment; `./uvr`
always works directly from the checkout.

```bash
uvr models list --family mdx
uvr separate song.wav -o ~/stems --model mdx:UVR-MDX-NET-Inst_HQ_4
uvr separate ~/Music -o ~/stems --recursive --include '*.flac' --dry-run
uvr ensemble song.wav -o ~/stems --ensemble "Curated: Vocal Clean"
uvr ensemble song.wav -o ~/stems --model mdx:model-a \
  --model demucs:hdemucs_mmi --main-stem pair.vocals_instrumental
uvr audio inspect song.wav
uvr audio stretch song.wav -o ~/processed --rate 1.1 --dry-run
uvr audio restore song.wav -o ~/processed --model apollo:apollo_edm_by_essid
uvr models catalog --family apollo --query restoration
uvr ensembles create my-mix --member mdx:model-a --member demucs:model-b \
  --main-stem pair.vocals_instrumental --algorithm 'Max Spec/Min Spec'
uvr update check
```

CLI runs start from clean defaults. Use `--profile gui`, a named sparse profile,
or a profile JSON path to inherit settings. A profile-supplied model or ensemble
identity is previewed and confirmed; scripts must add `--accept-inherited`.
Named flags and `--set section.field=value` are ephemeral and never modify GUI
settings.

`--dry-run` verifies inputs, model hashes, and configuration without loading
weights, creating the output directory, or starting inference. Automation can
select `--report json` for one result document or `--report jsonl` for progress
events. Batch directories, collision policies, partial-failure handling,
manifests, validation levels, model registration, devices, profiles, shell
completion, and A/B benchmarking are described in
[docs/environment.md](docs/environment.md#command-line-interface).
That section also documents migration from the earlier experimental CLI;
compatibility aliases are intentionally not shipped before release.

## Upgrading

This fork is distributed as **source** (no in-app binary update). To upgrade to a newer release:

```bash
cd ultimatevocalremovergtk
git pull
./install_packages.sh   # re-run if requirements.txt changed
./run_uvr.sh
```

Check [Releases](https://github.com/minarru/ultimatevocalremovergtk/releases) for release notes. The app’s **Application Version** dialog (Settings menu) compares your running version against `packaging/release.json` on GitHub.

## Models

Most model **weights are not stored in git** (they are large binary files). The repository ships only bundled metadata and one small VR model:

| Shipped in git | Purpose |
|---|---|
| `models/*/model_data/*.json` | Model hash maps and parameters |
| `models/MDX_Net_Models/model_data/mdx_c_configs/*.yaml` | MDX-C / Roformer / SCNet / Bandit config templates |
| `models/Apollo_Models/model_configs/` and `model_data/` | Apollo recognition metadata |
| `models/VR_Models/UVR-DeNoise-Lite.pth` | Built-in denoiser (~17 MB) |

Everything else must be downloaded or placed manually:

1. Launch the app and open **Download Center** from the menu (or use the banner when no models are installed for the selected method).
2. Download the models you need for VR, MDX-Net, or Demucs.
3. For **Apollo** restoration, place checkpoint files (`.ckpt` or `.bin`) in `models/Apollo_Models/`.
4. **Roformer**, **SCNet**, and **Bandit** checkpoints download like other MDX models; enable the *Roformer Model* flag in MDX-C model parameters when using them. See [docs/models.md](docs/models.md) for stem layouts.
5. **Download Center** merges the official TRvlvr catalogue, [Politrees UVR_resources](https://github.com/Politrees/UVR_resources), bundled fork extras, and [mvsepless_resources](https://huggingface.co/noblebarkrr/mvsepless_resources). Weights download from Hugging Face; YAML configs are fetched automatically. Models this build cannot run yet show as **Unsupported** (grayed). Set `UVR_DISABLE_POLITREES=1`, `UVR_DISABLE_EXTRA_MODELS=1`, and/or `UVR_DISABLE_MVSEPLESS=1` to disable individual supplements (see [docs/environment.md](docs/environment.md)); disabling Politrees alone does not leave only TRvlvr. TRvlvr download URLs that fail fall back to the Politrees Hugging Face mirror when available.

Downloaded weights are ignored by git (see `.gitignore`). Runtime data (settings, temp files) lives under the project directory in portable mode, or under `~/.local/share/ultimatevocalremover` when the install directory is read-only. The machine-specific model registry is also untracked: portable checkouts use `.uvr-runtime/registered_models.json`, while explicit `UVR_DATA_DIR` and read-only installs store it in their resolved data directory.

## Project layout

Source code is grouped by layer at the repository root:

| Path | Role |
|---|---|
| `ui/` | GTK4 / libadwaita interface (`python -m ui`) |
| `cli/` | Headless command-line interface (`uvr`; internal `python -m cli`) |
| `core/` | Frontend-neutral identities, discovery, planning, settings, devices, presets, registry, naming, and job execution |
| `engines/` | Separation orchestration (VR, MDX, Demucs) |
| `ml/` | Neural networks and audio DSP helpers |
| `bundled/` | Read-only constants, changelog, download metadata |
| `vendor/demucs/` | Vendored Demucs fork |
| `models/` | Model weights and hash maps (mostly downloaded locally) |
| `resources/` | Icon sources compiled into `ui/data/uvr.gresource` |

**Bundled (shipped with the repo):** `bundled/`, model metadata under `models/`, `ml/` VR parameter JSON, `vendor/`.

**Runtime (your machine, not in git):** `settings.json`, `profiles/*.json`, `ensembles/*.json`, `ensemble_temps/`, downloaded model weights, and model registry state. In a writable checkout most of these live at the repo root, while the registry uses `.uvr-runtime/`; otherwise they resolve under the configured or platform data directory (see `core/paths.py`). Legacy `data.pkl` is imported once when present. A legacy root `registered_models.json` is merged on reads and migrated to runtime storage on the next registry mutation.

The GUI and CLI share canonical model IDs (`vr:…`, `mdx:…`, `demucs:…`, and `apollo:…`)
and the same frontend-neutral job resolver. Stored model references are not
silently migrated: a malformed or unavailable ID remains stored until the user
repicks it in the relevant picker; see [docs/models.md](docs/models.md#model-identity).
CLI profile operations remain separate and never rewrite GUI storage. The GUI
performs runtime preflight before Separation, Ensemble, and Audio Tools jobs and, by default,
asks for confirmation of Separation and Ensemble plans. This confirmation can
be disabled in Settings without disabling preflight; Audio Tools never adds a
confirmation dialog.

## Notes

- Optional tuning and debug switches are listed in [docs/environment.md](docs/environment.md).
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
| `cannot import name 'InferenceSession' from 'onnxruntime'` | Leftover CUDA overlay in `.venv`. Rerun `./install_packages.sh --cuda` (it now uninstalls both CPU and GPU wheels and verifies the import). |
| Out-of-memory during separation | Lower segment or window size in model settings |
| No models in a dropdown | Open **Download Center** and fetch models for that process method |
| Errors during processing | Open **Error Log** from the menu or press `Ctrl+E`; details are also shown in the log panel |

For shared dependency questions (FFmpeg, Rubber Band, etc.), upstream [GitHub Issues](https://github.com/Anjok07/ultimatevocalremovergui/issues) may still be useful.

Report bugs in **this GTK fork** on [GitHub Issues](https://github.com/minarru/ultimatevocalremovergtk/issues). Use **Report Issue** in the Error Log to pre-fill version and log details.

Known upstream-applicable bugs and roadmap gaps are tracked in [docs/tracked-issues.md](docs/tracked-issues.md), including numbered findings F1–F24 and product gaps.

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
- [Politrees](https://github.com/Politrees/UVR_resources) — community model mirror and extended roformer configs
- [Hv](https://github.com/NaJeongMo/Colab-for-MDX_B) — MDX-Net chunking implementation

## References

- Takahashi et al., ["Multi-scale Multi-band DenseNets for Audio Source Separation"](https://arxiv.org/pdf/1706.09588.pdf)
