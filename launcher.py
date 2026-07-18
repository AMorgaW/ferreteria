# -*- coding: utf-8 -*-
"""
Launcher unificado del Sistema de Ferreteria.

Un solo ejecutable que permite ingresar como:
  - Administrador  (main.py)
  - Cliente        (client_app.py)

Tambien expone un modo interno "--serve" usado por el ejecutable para
levantar el servidor local-first como subproceso de si mismo (sin requerir
Python instalado en la maquina).

Cuando corre como .exe (PyInstaller onedir) copia la base de datos, el .env
y la config al directorio de datos en el primer arranque, de modo que los datos
persistan fuera de la carpeta portable.
"""
import os
import shutil
import sys
from pathlib import Path


def _app_base_dir() -> Path:
    """Carpeta donde viven los datos (db, .env, config, logs, backups, certs).

    En modo congelado se usa una carpeta ESCRIBIBLE y compartida
    (%PROGRAMDATA%\\FERREPRO), de modo que el ejecutable pueda instalarse en
    Program Files (solo lectura) sin impedir la creación de la base de datos.
    Si no se puede usar ProgramData, cae a la carpeta del ejecutable.
    """
    if getattr(sys, "frozen", False):
        programdata = os.environ.get("PROGRAMDATA") or os.environ.get("ALLUSERSPROFILE")
        if programdata:
            base = Path(programdata) / "FERREPRO"
            try:
                base.mkdir(parents=True, exist_ok=True)
                # Verificar que sea escribible
                probe = base / ".write_test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
                return base
            except OSError:
                pass
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _bundle_dir() -> Path:
    """Carpeta de recursos empaquetados."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", _app_base_dir()))
    return Path(__file__).resolve().parent


def _seed_file(name: str, base: Path) -> None:
    """Copia un recurso del bundle junto al ejecutable si no existe."""
    dest = base / name
    if dest.exists():
        return
    src = _bundle_dir() / name
    try:
        if src.is_dir():
            shutil.copytree(src, dest)
        elif src.exists():
            shutil.copy2(src, dest)
    except OSError:
        pass


def _prepare_runtime() -> Path:
    base = _app_base_dir()
    try:
        os.chdir(base)
    except OSError:
        pass

    if getattr(sys, "frozen", False):
        for name in ("ferreteria.db", ".env", "config"):
            _seed_file(name, base)

    # Datos locales junto al ejecutable, no dentro del bundle temporal.
    os.environ.setdefault("LOCAL_DB_PATH", str(base / "ferreteria.db"))

    # Cargar variables del .env ubicado junto al ejecutable.
    env_path = base / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
        except OSError:
            pass

    # ── Modo de base de datos ────────────────────────────────────────────
    # Por defecto LOCAL (local-first): cada equipo trabaja sobre su SQLite local
    # (rápido) y sincroniza con Supabase (pull al login + push cada 10 s). Debe
    # fijarse ANTES de importar pg_compat/database (leen DB_MODE al importarse).
    if not os.environ.get("DB_MODE"):
        modo = "local"
        try:
            from local_first_config import load_config
            modo = str(load_config().get("db_mode", "local")).strip().lower()
        except Exception:
            pass
        os.environ["DB_MODE"] = modo

    return base


BASE_DIR = _prepare_runtime()


def _run_server() -> int:
    """Modo interno: levanta el servidor local-first."""
    import argparse
    from local_server import run_server

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--host", default=os.environ.get("LOCAL_SERVER_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("LOCAL_SERVER_PORT", "8000")))
    parser.add_argument("--no-sync", action="store_true")
    parser.add_argument("--https", action="store_true")
    args, _ = parser.parse_known_args()

    db_path = os.environ.get("LOCAL_DB_PATH", str(BASE_DIR / "ferreteria.db"))
    run_server(args.host, args.port, db_path, start_sync=not args.no_sync,
               usar_https=args.https)
    return 0


def _choose_mode():
    """Muestra el selector Administrador / Cliente. Devuelve 'admin', 'client' o None."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                                   QPushButton, QVBoxLayout)

    app = QApplication.instance() or QApplication(sys.argv)

    dialog = QDialog()
    dialog.setWindowTitle("Sistema Ferreteria")
    dialog.setMinimumWidth(360)
    layout = QVBoxLayout(dialog)

    title = QLabel("Sistema de Ferreteria")
    title.setAlignment(Qt.AlignCenter)
    title.setStyleSheet("font-size: 18px; font-weight: bold; margin: 8px 0 4px 0;")
    layout.addWidget(title)

    subtitle = QLabel("Selecciona como deseas ingresar")
    subtitle.setAlignment(Qt.AlignCenter)
    subtitle.setStyleSheet("color: #555; margin-bottom: 12px;")
    layout.addWidget(subtitle)

    choice = {"mode": None}

    def pick(mode):
        choice["mode"] = mode
        dialog.accept()

    btn_admin = QPushButton("Administrador")
    btn_admin.setMinimumHeight(46)
    btn_admin.setStyleSheet(
        "QPushButton{background:#1565c0;color:white;font-size:15px;font-weight:bold;"
        "border-radius:8px;} QPushButton:hover{background:#0d47a1;}")
    btn_admin.clicked.connect(lambda: pick("admin"))

    btn_client = QPushButton("Cliente")
    btn_client.setMinimumHeight(46)
    btn_client.setStyleSheet(
        "QPushButton{background:#2e7d32;color:white;font-size:15px;font-weight:bold;"
        "border-radius:8px;} QPushButton:hover{background:#1b5e20;}")
    btn_client.clicked.connect(lambda: pick("client"))

    row = QHBoxLayout()
    row.addWidget(btn_admin)
    row.addWidget(btn_client)
    layout.addLayout(row)

    dialog.exec()
    return choice["mode"], app


def _run_admin(app) -> int:
    import main as admin_main

    try:
        app.setStyleSheet(admin_main.GLOBAL_QSS)
    except Exception:
        pass

    admin_main.show_login_and_run(reuse_app=True)

    # Si no quedo ninguna ventana visible (login cancelado), salir sin colgar.
    if not any(w.isVisible() for w in app.topLevelWidgets()):
        return 0
    return app.exec()


def _run_client() -> int:
    import client_app
    return client_app.main()


def main() -> int:
    try:
        from app_logging import setup_logging
        setup_logging(componente="launcher")
    except Exception:
        pass
    if "--serve" in sys.argv:
        return _run_server()

    # La app abre SIEMPRE directamente la aplicación principal (login FERREPRO)
    # contra la base remota. Ya no se muestra el antiguo selector
    # "Administrador / Cliente" ni el cliente LAN por IP: cada equipo usa la
    # misma base central en Supabase.
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    # Compatibilidad opcional: el modo cliente LAN sólo si se pide explícito.
    if "--client" in sys.argv:
        return _run_client()

    return _run_admin(app)


if __name__ == "__main__":
    raise SystemExit(main())
