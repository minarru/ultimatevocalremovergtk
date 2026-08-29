# Ultimate Vocal Remover — Linux (GTK4)

<img src="packaging/org.uvr.UltimateVocalRemover.png" alt="Ultimate Vocal Remover" width="128" />

Ultimate Vocal Remover for Linux is a local GTK4/libadwaita application for
splitting audio into vocals, instrumental, drums, bass, and other stems. It is
based on [Ultimate Vocal Remover v5.6](https://github.com/Anjok07/ultimatevocalremovergui)
and also provides a headless `uvr` command-line interface.

**GTK release v1.2.0** · [Source](https://github.com/minarru/ultimatevocalremovergtk) ·
[Releases](https://github.com/minarru/ultimatevocalremovergtk/releases) ·
[Report an issue](https://github.com/minarru/ultimatevocalremovergtk/issues)

GitHub is the canonical home for this fork. The former Codeberg repository is
archived; see [docs/mirroring.md](docs/mirroring.md).

## Highlights

- Separate vocals/instrumental pairs or multi-stem sources such as drums, bass,
  guitar, speech, music, and effects.
- Run VR Architecture, MDX-Net, MDX23C, Band-Split/Mel-Band RoFormer, SCNet,
  BandIt, and Demucs models.
- Find and install supported models through the built-in **Download Center**.
- Combine models with curated or custom ensembles.
- Inspect, stretch, pitch-shift, align, or match audio, and restore it with
  **Apollo**.
- Use the GTK application interactively or automate the same core workflows
  through the `uvr` CLI.

Support the original UVR project: [Donate](https://www.buymeacoffee.com/uvr5).

## Requirements

- 64-bit Linux
- System Python **3.13+** (developed and tested on Python 3.14)
- System **PyGObject**, **GTK 4**, and **libadwaita** (`gi`)
- **FFmpeg** for non-WAV input and output
- **Rubber Band CLI** for Time Stretch and Change Pitch
- Optional: [uv](https://docs.astral.sh/uv/) for faster installs or the Python
  3.12 fallback path
- Optional: an NVIDIA GPU and working driver for accelerated MDX/ONNX inference

## Quick start

```bash
git clone https://github.com/minarru/ultimatevocalremovergtk.git
cd ultimatevocalremovergtk
./install_packages.sh --system-deps
./run_uvr.sh
```

Run the installer as your normal user. With `--system-deps` it uses `sudo` only
for distro packages, then creates a user-owned `.venv` on the system Python
with `--system-site-packages`. This lets GTK come from your distribution while
the machine-learning stack stays inside the project environment and leaves
PEP 668-protected system Python packages untouched.

`run_uvr.sh` launches the app and installs its desktop entry under
`~/.local/share/applications/` when needed. After activating the environment,
you can also launch directly with `python -m ui`.

## Installation options

### Install system packages manually

If you do not want the installer to invoke your package manager, install the
system dependencies yourself and then run `./install_packages.sh` without
`--system-deps`.

<details>
<summary>Debian, Ubuntu, and Linux Mint</summary>

```bash
sudo apt update
sudo apt install -y ffmpeg python3-venv python3-pip python3-gi gir1.2-gtk-4.0 \
    gir1.2-adw-1 libglib2.0-bin libsndfile1 rubberband-cli
```

</details>

<details>
<summary>Fedora</summary>

```bash
sudo dnf install -y ffmpeg python3-pip python3-gobject gtk4 libadwaita libsndfile rubberband
```

</details>

<details>
<summary>Arch, CachyOS, EndeavourOS, and Manjaro</summary>

```bash
sudo pacman -Syu --needed ffmpeg python-pip python-virtualenv python-gobject gtk4 \
    libadwaita glib2 libsndfile rubberband
```

</details>

<details>
<summary>openSUSE</summary>

```bash
sudo zypper install -y ffmpeg python3-pip python3-gobject gtk4 libadwaita libsndfile1 rubberband
```

</details>

### NVIDIA GPU

Add `--cuda` to replace CPU ONNX Runtime with the CUDA overlay:

```bash
./install_packages.sh --system-deps --cuda
```

If the distro packages are already installed, use
`./install_packages.sh --cuda` instead.

### Choose a system Python

```bash
./install_packages.sh --python /usr/bin/python3.14
```

### Python 3.12 fallback

Use this only when the system-Python/PyGObject path is unavailable. It creates
an uv-managed Python 3.12 environment and installs PyGObject with pip.

```bash
./install_packages.sh --mode fallback --uv
```

Keep pip-installed packages inside `.venv`; do not use `sudo pip` or delete
your distribution's `/usr/lib/python*/EXTERNALLY-MANAGED` marker.

## Your first separation

1. Start the application with `./run_uvr.sh`.
2. Open **Download Center** from the application menu.
3. Choose a supported model for the output you want and download it.
4. Return to Separation, choose the input audio, model, output folder, and
   stems to save.
5. Review the resolved plan and start processing.

Model weights are generally not stored in git. Downloaded files stay local and
are ignored by git. See [Models and stems](docs/models.md) for model families,
catalogue behavior, stem meanings, canonical IDs, and custom-model handling.

## Command-line quick start

The installer links the checkout's `uvr` launcher into `~/.local/bin` when that
name is available. Use `./uvr` from the checkout if `uvr` is not on `PATH`.

```bash
uvr models catalog --family mdx --query karaoke
uvr models download "MelBand Roformer — Karaoke · Gabox"
uvr models list --family mdx
uvr separate song.wav -o ~/stems --model mdx:UVR-MDX-NET-Inst_HQ_4
```

Use the exact installed ID printed by `uvr models list` in place of the example
model. Add `--dry-run` to resolve and validate a job without loading weights or
processing audio. CLI jobs start from clean defaults unless you explicitly
select `--profile gui`, a named profile, or a profile JSON file.

See the [CLI guide](docs/cli.md) for ensembles, Audio Tools, stem selection,
profiles, validation, batch safety, manifests, and JSON/JSONL automation.

## Documentation

| Guide | Contents |
| --- | --- |
| [Models and stems](docs/models.md) | Download Center, model families, stem behavior, canonical IDs, compatibility, and architecture notes |
| [CLI](docs/cli.md) | Commands, profiles, dry runs, batches, manifests, reports, and exit codes |
| [Environment and troubleshooting](docs/environment.md) | Data paths, diagnostics, catalogue switches, external tools, launcher settings, and development controls |

## Upgrading

This fork is distributed as source; it does not install binary updates in the
application.

```bash
cd ultimatevocalremovergtk
git pull
./install_packages.sh   # re-run when requirements change
./run_uvr.sh
```

Check [Releases](https://github.com/minarru/ultimatevocalremovergtk/releases)
for release notes. **Application Version** in the Settings menu compares the
running version with the current GitHub release metadata.

## Troubleshooting and support

| Problem | What to try |
| --- | --- |
| `gi` or GTK import errors | Install your distro's GTK4, libadwaita, and Python GObject packages, then recreate `.venv` with `./install_packages.sh` |
| FFmpeg errors on non-WAV files | Install `ffmpeg` and confirm it is on `PATH` |
| Time Stretch or Change Pitch unavailable | Install `rubberband-cli` |
| No models in a picker | Open Download Center and install a supported model for that method |
| Processing fails | Open **Error Log** or press `Ctrl+E`; enable Debug or Trace under **Preferences → General → Diagnostics** when more detail is needed |

The full troubleshooting and diagnostic reference is in
[docs/environment.md](docs/environment.md#troubleshooting). Model-specific
problems are covered in [docs/models.md](docs/models.md).

Report GTK-fork bugs on [GitHub Issues](https://github.com/minarru/ultimatevocalremovergtk/issues).
The Error Log's **Report Issue** action pre-fills version and log details.
Shared upstream dependency discussions may also be relevant in the original
[UVR issue tracker](https://github.com/Anjok07/ultimatevocalremovergui/issues).
Known upstream-applicable bugs and roadmap gaps are tracked in
[docs/tracked-issues.md](docs/tracked-issues.md).

## License

The repository's root project licence is the [MIT License](LICENSE).
Third-party code, model weights, and other material retain their own licences
and terms. Catalogue links identify external providers; they neither relicense
those downloads nor imply that this repository rehosts the external weights.

## Credits

### Upstream UVR

- [Anjok07](https://github.com/anjok07) and [aufr33](https://github.com/aufr33) — Ultimate Vocal Remover
- [DilanBoskan](https://github.com/DilanBoskan) — early project contributions
- [Bas Curtiz](https://www.youtube.com/user/bascurtiz) — UVR logo and branding
- [KimberleyJSN](https://github.com/KimberleyJensen) — MDX-Net and Demucs training scripts
- [Hv](https://github.com/NaJeongMo/Colab-for-MDX_B) — MDX-Net chunking implementation

### Architectures and code

- [tsurumeso](https://github.com/tsurumeso) — original VR Architecture
- [Kuielab](https://github.com/kuielab) and Woosung Choi — original MDX-Net
- [ZFTurbo/Music-Source-Separation-Training](https://github.com/ZFTurbo/Music-Source-Separation-Training)
  — MDX23C and the MSST implementations used for the SCNet Masked/Tran
  variants and related MDX-C support
- [lucidrains](https://github.com/lucidrains/BS-RoFormer) — Band-Split and
  Mel-Band RoFormer PyTorch implementations adapted in `ml/`
- [starrytong/SCNet](https://github.com/starrytong/SCNet) and Tong et al. —
  the official original SCNet implementation; Masked and Tran variants come
  through ZFTurbo's training project
- [Karn Watcharasupat et al.](https://github.com/kwatcharasupat/bandit) —
  BandIt cinematic separation and its
  [v2 reimplementation](https://github.com/kwatcharasupat/bandit-v2)
- [JusperLee/Apollo](https://github.com/JusperLee/Apollo), Kai Li, and Yi Luo
  — Apollo audio-restoration code and architecture
- [pcunwa/BS-Roformer-HyperACE](https://huggingface.co/pcunwa/BS-Roformer-HyperACE)
  / Unwa — HyperACE reference implementation and weights used by the port
- Gopalakrishnan et al. and
  [PoPE-pytorch](https://pypi.org/project/PoPE-pytorch/) — Polar Coordinate
  Positional Embedding used by PolarFormer checkpoints
- [Alexandre Défossez and Meta](https://github.com/facebookresearch/demucs) —
  Demucs code and models; vendored Conv-TasNet files retain
  [Kaituo Xu's](https://github.com/kaituoxu/Conv-TasNet) attribution
- [Sergree / Matchering](https://github.com/sergree/matchering) — Audio Match
  processing and the retained `ml/results.py` provenance

### Model and catalogue sources

- [TRvlvr/application_data](https://github.com/TRvlvr/application_data) and
  [TRvlvr/model_repo](https://github.com/TRvlvr/model_repo) — official UVR
  catalogue metadata and public model distribution
- [Politrees/UVR_resources](https://github.com/Politrees/UVR_resources) —
  community catalogue, configurations, and model mirror
- [noblebarkrr/mvsepless_resources](https://huggingface.co/noblebarkrr/mvsepless_resources)
  — additional community catalogue index
- [Aname](https://huggingface.co/Aname-Tommy/Huge-SCNet-4stems), Unwa, and
  essid — creators of the fork-curated Huge SCNet, HyperACE, and Apollo EDM
  weights, respectively, listed in
  [`bundled/extra_models.json`](bundled/extra_models.json)

Individual downloadable models retain the authors shown in their reviewed
catalogue labels; this list documents the project's direct sources rather than
attempting to enumerate every model creator.

## References

- Takahashi et al., ["Multi-scale Multi-band DenseNets for Audio Source Separation"](https://arxiv.org/abs/1706.09588)
- Lu et al., ["Music Source Separation with Band-Split RoPE Transformer"](https://arxiv.org/abs/2309.02612)
- Wang, Lu, and Won, ["Mel-Band RoFormer for Music Source Separation"](https://arxiv.org/abs/2310.01809)
- Tong et al., ["SCNet: Sparse Compression Network for Music Source Separation"](https://arxiv.org/abs/2401.13276)
- Watcharasupat et al., ["A Generalized Bandsplit Neural Network for Cinematic Audio Source Separation"](https://arxiv.org/abs/2309.02539)
- Li and Luo, ["Apollo: Band-sequence Modeling for High-Quality Audio Restoration"](https://arxiv.org/abs/2409.08514)
- Gopalakrishnan et al., ["Decoupling the What and Where With Polar Coordinate Positional Embeddings"](https://arxiv.org/abs/2509.10534)
