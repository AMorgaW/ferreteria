# -*- coding: utf-8 -*-
import ast
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from local_first_config import load_config
from local_first_db import DEFAULT_DB_PATH, connect, ensure_local_first_schema, get_sync_status
from services.local_api_client import LocalAPIClient, LocalAPIError


FORBIDDEN_CLIENT_IMPORTS = {
    "database",
    "pg_compat",
    "local_first_db",
    "local_sync",
    "repositories",
}


def imported_roots(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def main():
    ensure_local_first_schema(DEFAULT_DB_PATH)
    conn = connect(DEFAULT_DB_PATH)
    try:
        products = conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
        users = conn.execute("SELECT COUNT(*) FROM usuarios WHERE activo = 1").fetchone()[0]
    finally:
        conn.close()

    client_imports = imported_roots(BASE_DIR / "client_app.py")
    client_imports |= imported_roots(BASE_DIR / "services" / "local_api_client.py")
    forbidden = sorted(client_imports & FORBIDDEN_CLIENT_IMPORTS)
    if forbidden:
        raise RuntimeError(f"El modo cliente importa modulos locales no permitidos: {', '.join(forbidden)}")

    config = load_config()
    url = f"http://127.0.0.1:{int(config.get('server_port', 8000))}"
    try:
        health = LocalAPIClient(url, timeout=1).health()
        server = f"activo ({health.get('version', 'sin version')})"
    except LocalAPIError:
        server = "inactivo; inicia run_admin.bat o run_local_server.bat para probar HTTP"

    print("Verificacion local-first correcta")
    print(f"- Base local: {DEFAULT_DB_PATH}")
    print(f"- Productos: {products}")
    print(f"- Usuarios activos: {users}")
    print(f"- Cola: {get_sync_status(DEFAULT_DB_PATH)}")
    print(f"- Cliente remoto aislado de SQLite: si")
    print(f"- Servidor HTTP: {server}")


if __name__ == "__main__":
    main()
