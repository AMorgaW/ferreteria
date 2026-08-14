# -*- coding: utf-8 -*-
"""Reconstruye FERREPRO_PG_TEST_DSN desde ferrepro-pg-test sin imprimir secretos."""
from __future__ import annotations

import os
import subprocess
from urllib.parse import quote


def _dsn_from_container() -> str:
    proc = subprocess.run(
        [
            "docker",
            "inspect",
            "ferrepro-pg-test",
            "--format",
            "{{range .Config.Env}}{{println .}}{{end}}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        return ""
    env = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            env[key] = value
    user = env.get("POSTGRES_USER") or "postgres"
    password = env.get("POSTGRES_PASSWORD") or ""
    dbname = env.get("POSTGRES_DB") or "ferrepro_test"
    if not password:
        return ""
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@127.0.0.1:55432/{dbname}"
    )


def ensure_pg_test_dsn() -> str:
    """Devuelve el DSN. Nunca imprime el valor. No usa SUPABASE_URI."""
    current = (os.environ.get("FERREPRO_PG_TEST_DSN") or "").strip()
    if current:
        return current
    rebuilt = _dsn_from_container()
    if rebuilt:
        os.environ["FERREPRO_PG_TEST_DSN"] = rebuilt
    return rebuilt
