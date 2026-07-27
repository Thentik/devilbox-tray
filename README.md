# Devilbox Tray

Small tray app to control [Devilbox](https://devilbox.org) from any
StatusNotifierItem system tray: start / stop / restart containers, see their
status, open the intranet. Think WAMP's Aestan Tray, but for Linux.

Works with **Noctalia**, Waybar, KDE, GNOME (with the AppIndicator extension),
etc. — Wayland and X11. Auto-configuring, multilingual, single-instance.

## Install

### Arch / CachyOS (AUR)

```bash
yay -S devilbox-tray
```

### Any distro (pipx — recommended)

```bash
pipx install devilbox-tray            # from PyPI
# or, from a clone:
pipx install .
```

### With pip

```bash
pip install --user devilbox-tray
```

The only runtime dependency is **PySide6** (pulled automatically), plus a
working Docker with `docker compose`.

## First run

```bash
devilbox-tray
```

On first launch the app **auto-detects** the Devilbox folder, the compose
command and the services. If nothing is found, the **Settings** panel opens so
you can pick the folder. Everything is saved to
`~/.config/devilbox-tray/config.json` and editable from the app.

## Usage

- **Left-click** the icon: show / hide the window.
- **Right-click**: menu (Start / Stop / Restart / Intranet / Quit).
- Icon color: green = all running, orange = partial, red = stopped.
- The `✕` in the window header hides it to the tray; use *Quit* to exit.

## Autostart

**Hyprland** — in `~/.config/hypr/hyprland.conf`:
```
exec-once = sleep 2 && devilbox-tray
```

**Other (systemd user service)** — create
`~/.config/systemd/user/devilbox-tray.service`:
```ini
[Unit]
Description=Devilbox Tray
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart=%h/.local/bin/devilbox-tray
Restart=on-failure

[Install]
WantedBy=graphical-session.target
```
then `systemctl --user enable --now devilbox-tray.service`.

## Translations

Languages live as JSON files in `devilbox_tray/locales/`. **To add a language**,
copy `en.json` to `<code>.json` (e.g. `it.json`), translate the values, and set
`"_name"` to the display name. It appears automatically in the Settings language
menu — no code change needed. Bundled: English, Français, Español, Deutsch.

## Packaging notes

- `pyproject.toml` (hatchling) builds a wheel; locale JSON files ship inside the
  package and are read via `importlib.resources`.
- `PKGBUILD` builds that wheel and installs the `.desktop` entry + icon for the
  AUR.
- For a self-contained binary instead, `pyinstaller --onefile --windowed
  -n devilbox-tray devilbox_tray/app.py` works, but bundling PySide6 is large
  (~150 MB); the wheel/AUR route is lighter and preferred.

## License

MIT.
