# Bundled symbolic icons

Drop SVG files under the **hicolor** layout (this is what GTK expects in
GResource bundles). The filename without `.svg` is the `icon_name` passed to
the row helpers.

Examples:

```
scalable/devices/pci-card-symbolic.svg    # device icons (GPU, etc.)
scalable/actions/bullhorn-symbolic.svg    # action/status symbolic icons
```

Then recompile the GResource bundle:

```bash
./resources/compile_resources.sh
```

Restart the app so the new `ui/data/uvr.gresource` is loaded.

Icons are registered at app startup. A system theme can take precedence over
a bundled icon with the same name; use an `uvr-` prefix for collisions so the
application reliably displays its bundled artwork.


## GNOME Icon Development Kit exports

The following assets are static outline exports from the [GNOME Icon Development
Kit](https://teams.pages.gitlab.gnome.org/Design/icon-development-kit/), retrieved
2026-09-10. Their upstream SVG metadata retains the creators and CC0-1.0 license.
Source files are under `icons/<source>.svg` in the
[upstream repository](https://gitlab.gnome.org/Teams/Design/icon-development-kit).

Exports select the outline state (filled for Stop), remove inactive geometry,
and resolve the foreground paint to `#2e3436`. Strokes are then converted into
filled paths using Inkscape's `object-stroke-to-path` action and plain SVG export.
This preserves the artwork without relying on GTK's treatment of SVG strokes
or Devkit-specific symbolic classes. Creator and license metadata remain intact.
Small status glyphs retain centered, compact geometry. Local filenames remain
stable aliases; some describe the previous artwork.

Validate through `GtkSymbolicPaintable`, not only GdkPixbuf or a browser: ordinary
SVG rendering can look correct while symbolic rendering fills outline shapes.
Compare alpha masks against the source SVG at 16px and 32px, and check both light
and dark foreground colors.

| Local filename (without `.svg`) | Devkit source | Scale within 16px canvas |
| --- | --- | --- |
| `cogged-wheel-symbolic` | `cogged-wheel` | 1 |
| `processor-symbolic` | `processor` | 1 |
| `export-symbolic` | `export` | 1 |
| `wrench-symbolic` | `wrench` | 1 |
| `vertical-arrows-up-symbolic` | `view-sort-ascending` | 1 |
| `vertical-arrows-down-symbolic` | `view-sort-descending` | 1 |
| `error-outline-symbolic` | `cross` | 1 |
| `bullhorn-symbolic` | `sound-wave` | 1 |
| `pci-card-symbolic` | `pci` | 1 |
| `ungroup-symbolic` | `ungroup` | 1 |
| `check-round-outline-symbolic` | `circle-check` | 1 |
| `exclamation-mark-symbolic` | `round-exclamation` | 1 |
| `warning-outline-symbolic` | `dialog-warning` | 1 |
| `bookmark-outline-symbolic` | `bookmark` | 1 |
| `info-outline-symbolic` | `info-outline` | 1 |
| `uvr-edit-clear-all-symbolic` | `edit-clear-all` | 1 |
| `uvr-go-bottom-symbolic` | `go-bottom` | 1 |
| `cross-small-symbolic` | `cross` | 0.625 |
| `success-small-symbolic` | `object-select` | 0.625 |
| `stop-small-symbolic` | `media-playback-stop` (filled state) | 1 |
| `uvr-mixer-sliders-symbolic` | `mixer-sliders` | 1 |
| `uvr-api-symbolic` | `api` | 1 |
| `uvr-stopwatch-symbolic` | `stopwatch` | 1 |
| `uvr-speaker-symbolic` | `speaker` | 1 |

The report bubble and speaking-person icons retain their existing artwork.
