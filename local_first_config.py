# -*- coding: utf-8 -*-
import json
import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _data_dir() -> Path:
    """Carpeta persistente de datos.

    En modo congelado (PyInstaller) — o cuando el launcher define
    LOCAL_DB_PATH — la configuración vive JUNTO a la base de datos persistente
    (p. ej. %PROGRAMDATA%\\FERREPRO), NO dentro del bundle temporal (_MEIPASS),
    que se borra al cerrar la app. Así los ajustes del usuario persisten.
    """
    db = os.environ.get("LOCAL_DB_PATH")
    if db:
        try:
            return Path(db).resolve().parent
        except Exception:
            pass
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return BASE_DIR


def _config_dir() -> Path:
    return _data_dir() / "config"


def _config_path() -> Path:
    return _config_dir() / "local_first_config.json"


# Compatibilidad hacia atrás (dev): constantes calculadas al importar. En modo
# congelado, load_config()/save_config() usan _config_dir()/_config_path().
CONFIG_DIR = _config_dir()
CONFIG_PATH = _config_path()

DEFAULT_CONFIG = {
    "app_mode": "admin",
    # ── Arquitectura local-first ──────────────────────────────────────
    # "local"  -> cada equipo trabaja sobre su SQLite LOCAL (rápido, sin lag de
    #             red). Al iniciar sesión DESCARGA los datos de la nube (pull) y
    #             cada ~10 s SUBE sus cambios a Supabase (push). Así las dos
    #             bases concuerdan sin depender de un servidor LAN ni de estar
    #             siempre en línea para cada operación.
    # "remote" -> conexión directa a Supabase en cada consulta (lento; solo
    #             para diagnóstico).
    "db_mode": "local",
    "supabase_enabled": True,
    "cloud_sync_enabled": True,   # push cada 10s + pull al iniciar sesión
    "pull_interval_seconds": 45,  # cada cuánto revisa cambios nuevos en la nube
    # ── Servidor LAN (LEGADO / desactivado) ───────────────────────────
    # Ya NO se usa: la sincronización con Supabase corre dentro de la app.
    "server_host": "0.0.0.0",
    "server_port": 8000,
    "server_url": "http://127.0.0.1:8000",
    "auto_start_server": False,
    "auto_start_sync": True,
    "last_connected_server": "http://127.0.0.1:8000",
    "client_timeout_seconds": 4,
    "business_name": "Ferreteria",
    # IVA (impuesto). Por defecto APAGADO: cero cambio de comportamiento.
    # Modelo "incluido": el precio_venta ya incluye IVA y solo se desglosa
    # (el monto cobrado NO cambia). Si "iva_incluido": false, el IVA se añade
    # sobre el total.
    "iva_activo": False,
    "iva_tasa": 0.19,
    "iva_incluido": True,
    # Seguridad de red local: HTTPS en el servidor LAN (cert autofirmado).
    "usar_https": False,
}


def load_config():
    cfg_dir = _config_dir()
    cfg_path = _config_path()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    config = dict(DEFAULT_CONFIG)
    if cfg_path.exists():
        try:
            stored = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                config.update(stored)
        except (OSError, ValueError):
            pass
    return config


def save_config(updates):
    cfg_dir = _config_dir()
    cfg_path = _config_path()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    config = load_config()
    config.update(updates)
    cfg_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return config


def server_url(config=None):
    config = config or load_config()
    return (config.get("last_connected_server") or config.get("server_url") or "").rstrip("/")


def server_scheme(config=None):
    config = config or load_config()
    return "https" if config.get("usar_https") else "http"


def admin_server_url(config=None):
    config = config or load_config()
    port = int(config.get("server_port", 8000))
    return f"{server_scheme(config)}://127.0.0.1:{port}"


def apply_environment(config=None):
    config = config or load_config()
    os.environ.setdefault("APP_MODE", str(config.get("app_mode", "admin")))
    os.environ.setdefault("LOCAL_SERVER_HOST", str(config.get("server_host", "0.0.0.0")))
    os.environ.setdefault("LOCAL_SERVER_PORT", str(config.get("server_port", 8000)))
    return config
