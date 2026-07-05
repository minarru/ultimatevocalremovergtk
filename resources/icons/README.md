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

Icons are registered at app startup and searched **before** the system theme, so
a bundled name overrides Adwaita when present.
