#!/usr/bin/env python3
"""
Devilbox Tray — contrôle Devilbox depuis le tray (StatusNotifierItem).

Auto-configurable, multilingue, instance unique. Fonctionne sur tout hôte SNI
(Noctalia, Waybar, KDE, GNOME + extension…), Wayland comme X11.
"""

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QProcess, QUrl
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QBrush, QFont, QAction, QDesktopServices,
)
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QDialog, QLineEdit, QCheckBox, QScrollArea,
    QFileDialog, QDialogButtonBox, QMessageBox, QSpinBox, QComboBox,
)

from .i18n import tr, set_language, available_languages

APP_ID = "devilbox-tray"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_ID
CONFIG_FILE = CONFIG_DIR / "config.json"

COL_RUNNING = "#3fb950"
COL_PARTIAL = "#d29922"
COL_STOPPED = "#f85149"
COL_UNKNOWN = "#6e7681"

DEFAULT_CONTROLLED = ["httpd", "php", "mysql"]
CANDIDATE_DIRS = [
    "~/devilbox", "~/Devilbox", "~/projects/devilbox", "~/Projects/devilbox",
    "~/dev/devilbox", "~/www/devilbox", "~/docker/devilbox",
    "/opt/devilbox", "/srv/devilbox",
]

_lock_handle = None


def acquire_single_instance() -> bool:
    global _lock_handle
    path = os.path.join(tempfile.gettempdir(), f"{APP_ID}-{os.getuid()}.lock")
    _lock_handle = open(path, "w")
    try:
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------- #
#  Détection d'environnement
# ---------------------------------------------------------------------- #
def detect_compose_cmd():
    if shutil.which("docker"):
        try:
            subprocess.run(["docker", "compose", "version"],
                           capture_output=True, check=True)
            return ["docker", "compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return ["docker", "compose"]


COMPOSE = detect_compose_cmd()


def looks_like_devilbox(path: Path) -> bool:
    if not path.is_dir() or not (path / "docker-compose.yml").is_file():
        return False
    for marker in (".devilbox", "bash", "compose", "cfg"):
        if (path / marker).exists():
            return True
    return (path / ".env").is_file() or path.name.lower() == "devilbox"


def find_devilbox_dir() -> str:
    for raw in CANDIDATE_DIRS:
        p = Path(raw).expanduser()
        if looks_like_devilbox(p):
            return str(p)
    try:
        for child in Path.home().iterdir():
            if child.is_dir() and "devilbox" in child.name.lower() \
                    and looks_like_devilbox(child):
                return str(child)
    except OSError:
        pass
    return ""


def compose_services(devilbox_dir: str) -> list:
    if not devilbox_dir or not Path(devilbox_dir).is_dir():
        return []
    try:
        out = subprocess.run(
            COMPOSE + ["config", "--services"],
            cwd=devilbox_dir, capture_output=True, text=True, timeout=15,
        )
        return sorted(s for s in out.stdout.splitlines() if s.strip())
    except (subprocess.SubprocessError, OSError):
        return []


# ---------------------------------------------------------------------- #
#  Config
# ---------------------------------------------------------------------- #
def default_config() -> dict:
    d = find_devilbox_dir()
    svcs = compose_services(d)
    controlled = [s for s in DEFAULT_CONTROLLED if s in svcs] or svcs[:3]
    return {
        "devilbox_dir": d,
        "services": controlled,
        "intranet_url": "http://localhost",
        "poll_interval_ms": 4000,
        "language": "auto",
    }


def load_config():
    if CONFIG_FILE.is_file():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            cfg.setdefault("intranet_url", "http://localhost")
            cfg.setdefault("poll_interval_ms", 4000)
            cfg.setdefault("services", [])
            cfg.setdefault("devilbox_dir", "")
            cfg.setdefault("language", "auto")
            return cfg
        except (json.JSONDecodeError, OSError):
            pass
    return None


def save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# ---------------------------------------------------------------------- #
#  Icône générée
# ---------------------------------------------------------------------- #
def make_icon(color: str) -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.NoPen)
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(QColor("#ffffff"))
    p.setFont(QFont("Sans", 30, QFont.Bold))
    p.drawText(pix.rect(), Qt.AlignCenter, "D")
    p.end()
    return QIcon(pix)


def parse_ps(output: str) -> dict:
    services = {}
    output = (output or "").strip()
    if not output:
        return services
    rows = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows = []
            break
    if not rows:
        try:
            data = json.loads(output)
            rows = data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            return services
    for row in rows:
        name = row.get("Service") or row.get("Name", "")
        state = (row.get("State") or "").lower()
        if name:
            services[name] = state.startswith("running") or state == "up"
    return services


# ---------------------------------------------------------------------- #
#  Panneau Paramètres
# ---------------------------------------------------------------------- #
class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings_title"))
        self.setMinimumWidth(420)
        self.cfg = dict(cfg)

        root = QVBoxLayout(self)

        root.addWidget(QLabel(tr("lbl_dir")))
        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(self.cfg.get("devilbox_dir", ""))
        browse = QPushButton(tr("browse"))
        browse.clicked.connect(self.browse)
        detect = QPushButton(tr("auto"))
        detect.clicked.connect(self.autodetect)
        dir_row.addWidget(self.dir_edit)
        dir_row.addWidget(browse)
        dir_row.addWidget(detect)
        root.addLayout(dir_row)

        root.addWidget(QLabel(tr("lbl_services")))
        self.svc_area = QScrollArea()
        self.svc_area.setWidgetResizable(True)
        self.svc_area.setFixedHeight(150)
        root.addWidget(self.svc_area)
        self.svc_checks = []
        self.reload_services()

        root.addWidget(QLabel(tr("lbl_intranet_url")))
        self.url_edit = QLineEdit(self.cfg.get("intranet_url", "http://localhost"))
        root.addWidget(self.url_edit)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("lbl_refresh")))
        self.interval = QSpinBox()
        self.interval.setRange(1, 60)
        self.interval.setValue(max(1, self.cfg.get("poll_interval_ms", 4000) // 1000))
        row.addWidget(self.interval)
        row.addStretch()
        row.addWidget(QLabel(tr("lbl_language")))
        self.lang = QComboBox()
        self.lang.addItem(tr("lang_auto"), "auto")
        for code, name in available_languages().items():
            self.lang.addItem(name, code)
        idx = self.lang.findData(self.cfg.get("language", "auto"))
        self.lang.setCurrentIndex(idx if idx >= 0 else 0)
        row.addWidget(self.lang)
        root.addLayout(row)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText(tr("save"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def browse(self):
        start = self.dir_edit.text() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, tr("lbl_dir"), start)
        if chosen:
            self.dir_edit.setText(chosen)
            self.reload_services()

    def autodetect(self):
        found = find_devilbox_dir()
        if found:
            self.dir_edit.setText(found)
            self.reload_services()
        else:
            QMessageBox.information(self, tr("autodetect_title"), tr("autodetect_none"))

    def reload_services(self):
        current = set(self.cfg.get("services", []))
        services = compose_services(self.dir_edit.text())
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(4, 4, 4, 4)
        self.svc_checks = []
        if services:
            for s in services:
                cb = QCheckBox(s)
                cb.setChecked(s in current if current else False)
                lay.addWidget(cb)
                self.svc_checks.append(cb)
        else:
            lay.addWidget(QLabel(tr("services_not_found")))
        lay.addStretch()
        self.svc_area.setWidget(container)

    def result_config(self) -> dict:
        selected = [cb.text() for cb in self.svc_checks if cb.isChecked()]
        return {
            "devilbox_dir": self.dir_edit.text().strip(),
            "services": selected,
            "intranet_url": self.url_edit.text().strip() or "http://localhost",
            "poll_interval_ms": self.interval.value() * 1000,
            "language": self.lang.currentData(),
        }


# ---------------------------------------------------------------------- #
#  Application principale
# ---------------------------------------------------------------------- #
class DevilboxTray(QWidget):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.services_state = {}
        self.busy = False
        self._queue = []
        self._label = ""

        self.icons = {k: make_icon(c) for k, c in {
            "running": COL_RUNNING, "partial": COL_PARTIAL,
            "stopped": COL_STOPPED, "unknown": COL_UNKNOWN,
        }.items()}

        self.status_proc = QProcess(self)
        self.status_proc.finished.connect(self._on_status_finished)
        self.action_proc = QProcess(self)
        self.action_proc.finished.connect(self._on_action_finished)

        self._build_window()
        self._build_tray()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.apply_config()

    @property
    def devilbox_dir(self):
        return self.cfg.get("devilbox_dir", "")

    @property
    def services(self):
        return self.cfg.get("services", [])

    # ---- construction UI --------------------------------------------- #
    def _build_window(self):
        self.setFixedWidth(300)
        self.setStyleSheet("""
            QWidget { background:#1b1e24; color:#e6edf3;
                      font-family:'Sans'; font-size:13px; }
            QLabel#title { font-size:15px; font-weight:bold; }
            QPushButton { background:#2a2f38; border:1px solid #3a3f48;
                          border-radius:6px; padding:6px; }
            QPushButton:hover { background:#343a44; }
            QPushButton:pressed { background:#262b33; }
            QPushButton:disabled { color:#6e7681; }
            QPushButton#close { background:transparent; border:none;
                                color:#9aa4af; font-size:16px; font-weight:bold;
                                padding:0; min-width:22px; max-width:22px;
                                min-height:22px; max-height:22px;
                                border-radius:4px; }
            QPushButton#close:hover { background:#f85149; color:#ffffff; }
            QFrame#sep { background:#2a2f38; max-height:1px; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        self.title = QLabel(tr("app_title"), objectName="title")
        self.btn_close = QPushButton("✕", objectName="close")
        self.btn_close.setToolTip(tr("hide_to_tray"))
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.hide)
        header.addWidget(self.title)
        header.addStretch()
        header.addWidget(self.btn_close)
        root.addLayout(header)

        sep = QFrame(objectName="sep")
        sep.setFrameShape(QFrame.HLine)
        root.addWidget(sep)

        self.svc_box = QVBoxLayout()
        self.svc_box.setSpacing(4)
        root.addLayout(self.svc_box)
        self.rows = {}

        sep2 = QFrame(objectName="sep")
        sep2.setFrameShape(QFrame.HLine)
        root.addWidget(sep2)

        btns = QHBoxLayout()
        self.btn_start = QPushButton(tr("start"))
        self.btn_stop = QPushButton(tr("stop"))
        self.btn_start.clicked.connect(self.action_start)
        self.btn_stop.clicked.connect(self.action_stop)
        btns.addWidget(self.btn_start)
        btns.addWidget(self.btn_stop)
        root.addLayout(btns)

        btns2 = QHBoxLayout()
        self.btn_restart = QPushButton(tr("restart"))
        self.btn_intranet = QPushButton(tr("intranet"))
        self.btn_restart.clicked.connect(self.action_restart)
        self.btn_intranet.clicked.connect(self.open_intranet)
        btns2.addWidget(self.btn_restart)
        btns2.addWidget(self.btn_intranet)
        root.addLayout(btns2)

        self.btn_settings = QPushButton(tr("settings"))
        self.btn_settings.clicked.connect(self.open_settings)
        root.addWidget(self.btn_settings)

    def _build_service_rows(self):
        while self.svc_box.count():
            item = self.svc_box.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
        self.rows = {}
        if not self.services:
            lbl = QLabel(tr("not_configured"))
            lbl.setStyleSheet("color:#9aa4af;")
            self.svc_box.addWidget(lbl)
            return
        for svc in self.services:
            row = QHBoxLayout()
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{COL_UNKNOWN};")
            name = QLabel(svc)
            state = QLabel("—")
            state.setStyleSheet("color:#9aa4af;")
            row.addWidget(dot)
            row.addWidget(name)
            row.addStretch()
            row.addWidget(state)
            self.svc_box.addLayout(row)
            self.rows[svc] = (dot, state)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self.icons["unknown"], self)
        self.tray.setToolTip(tr("app_title"))
        self.tray.activated.connect(self._on_tray_activated)

        menu = QMenu()
        self.act_header = QAction("", self)
        self.act_header.setEnabled(False)
        menu.addAction(self.act_header)
        menu.addSeparator()

        self._actions = {}
        for key, slot in [("start", self.action_start),
                          ("stop", self.action_stop),
                          ("restart", self.action_restart)]:
            a = QAction(tr(key), self)
            a.triggered.connect(slot)
            menu.addAction(a)
            self._actions[key] = a
        menu.addSeparator()
        for key, slot in [("open_intranet", self.open_intranet),
                          ("toggle_window", self.toggle_window),
                          ("settings", self.open_settings)]:
            a = QAction(tr(key), self)
            a.triggered.connect(slot)
            menu.addAction(a)
            self._actions[key] = a
        menu.addSeparator()
        a_quit = QAction(tr("quit"), self)
        a_quit.triggered.connect(QApplication.instance().quit)
        menu.addAction(a_quit)
        self._actions["quit"] = a_quit

        self.tray.setContextMenu(menu)
        self.tray.show()

    def retranslate(self):
        self.title.setText(tr("app_title"))
        self.btn_close.setToolTip(tr("hide_to_tray"))
        self.btn_start.setText(tr("start"))
        self.btn_stop.setText(tr("stop"))
        self.btn_restart.setText(tr("restart"))
        self.btn_intranet.setText(tr("intranet"))
        self.btn_settings.setText(tr("settings"))
        self.tray.setToolTip(tr("app_title"))
        for key, act in self._actions.items():
            act.setText(tr(key))
        self._build_service_rows()
        self.update_ui()

    def apply_config(self):
        self._build_service_rows()
        self.timer.start(max(1000, self.cfg.get("poll_interval_ms", 4000)))
        self.refresh_status()

    # ---- état -------------------------------------------------------- #
    def refresh_status(self):
        if not self.devilbox_dir:
            self.update_ui()
            return
        if self.status_proc.state() != QProcess.NotRunning:
            return
        self.status_proc.setWorkingDirectory(self.devilbox_dir)
        self.status_proc.start(COMPOSE[0], COMPOSE[1:] + ["ps", "--format", "json"])

    def _on_status_finished(self, _c, _s):
        out = bytes(self.status_proc.readAllStandardOutput()).decode("utf-8", "replace")
        self.services_state = parse_ps(out)
        self.update_ui()

    def update_ui(self):
        if not self.devilbox_dir or not Path(self.devilbox_dir).is_dir():
            key, txt = "unknown", tr("status_unconfigured")
        else:
            running = [s for s in self.services if self.services_state.get(s)]
            if self.services and len(running) == len(self.services):
                key, txt = "running", tr("status_running")
            elif running:
                key = "partial"
                txt = tr("status_partial", running=len(running), total=len(self.services))
            else:
                key, txt = "stopped", tr("status_stopped")

        self.tray.setIcon(self.icons[key])
        self.setWindowIcon(self.icons[key])
        self.tray.setToolTip(tr("header_status", status=txt))
        self.act_header.setText(tr("header_status", status=txt))
        for svc, (dot, state) in self.rows.items():
            on = self.services_state.get(svc, False)
            dot.setStyleSheet(f"color:{COL_RUNNING if on else COL_STOPPED};")
            state.setText(tr("svc_active") if on else tr("svc_inactive"))

    # ---- actions ----------------------------------------------------- #
    def _guard(self):
        if not self.devilbox_dir or not Path(self.devilbox_dir).is_dir():
            QMessageBox.warning(self, tr("app_title"), tr("warn_no_dir"))
            return False
        if not self.services:
            QMessageBox.warning(self, tr("app_title"), tr("warn_no_services"))
            return False
        return True

    def _run(self, cmds, label):
        if self.busy or not self._guard():
            return
        self.busy = True
        self._queue = list(cmds)
        self._label = label
        self._set_buttons(False)
        self._run_next()

    def _run_next(self):
        if not self._queue:
            self.busy = False
            self._set_buttons(True)
            self.tray.showMessage("Devilbox", tr("done", label=self._label),
                                  self.icons["running"], 3000)
            self.refresh_status()
            return
        args = self._queue.pop(0)
        self.action_proc.setWorkingDirectory(self.devilbox_dir)
        self.action_proc.start(COMPOSE[0], COMPOSE[1:] + args)

    def _on_action_finished(self, _c, _s):
        self._run_next()

    def _set_buttons(self, enabled):
        for b in (self.btn_start, self.btn_stop, self.btn_restart):
            b.setEnabled(enabled)

    def action_start(self):
        self._run([["up", "-d"] + self.services], tr("label_start"))

    def action_stop(self):
        self._run([["stop"] + self.services], tr("label_stop"))

    def action_restart(self):
        self._run([["stop"] + self.services, ["up", "-d"] + self.services],
                  tr("label_restart"))

    def open_intranet(self):
        QDesktopServices.openUrl(QUrl(self.cfg.get("intranet_url", "http://localhost")))

    # ---- paramètres -------------------------------------------------- #
    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec() == QDialog.Accepted:
            new = dlg.result_config()
            lang_changed = new.get("language") != self.cfg.get("language")
            self.cfg = new
            save_config(self.cfg)
            if lang_changed:
                set_language(self.cfg.get("language", "auto"))
                self.retranslate()
            self.apply_config()

    # ---- fenêtre ----------------------------------------------------- #
    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_window()

    def toggle_window(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def closeEvent(self, event):
        event.ignore()
        self.hide()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Devilbox Tray")
    app.setDesktopFileName("devilbox-tray")
    app.setQuitOnLastWindowClosed(False)

    if not acquire_single_instance():
        set_language("auto")
        print(tr("already_running"), file=sys.stderr)
        sys.exit(0)

    cfg = load_config()
    first_run = cfg is None
    if first_run:
        cfg = default_config()
        save_config(cfg)

    set_language(cfg.get("language", "auto"))

    win = DevilboxTray(cfg)
    if first_run and not cfg.get("devilbox_dir"):
        win.open_settings()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
