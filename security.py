# -*- coding: utf-8 -*-
"""
Hashing de contraseñas seguro y retrocompatible (sin dependencias externas).

- Hashes nuevos: PBKDF2-HMAC-SHA256 con sal aleatoria por usuario.
  Formato: ``pbkdf2_sha256$<iteraciones>$<sal_hex>$<hash_hex>``
- Verificación retrocompatible con los hashes antiguos SHA-256 sin sal
  (64 caracteres hex) para no invalidar usuarios ya creados.
"""
import hashlib
import hmac
import os
from datetime import datetime, timedelta

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 200_000
_SALT_BYTES = 16

# --- Rate-limiting / bloqueo por fuerza bruta en el login ---
MAX_INTENTOS = 5
BLOQUEO_MINUTOS = 5
_FMT = "%Y-%m-%d %H:%M:%S"


def _ahora():
    return datetime.now()


def _reset_tx(cursor):
    """Deshace una transacción abortada (p. ej. por una tabla inexistente en
    Postgres) para que la conexión siga siendo usable en la siguiente consulta.
    En SQLite es inocuo. Sin esto, un error aquí deja la conexión en estado
    'InFailedSqlTransaction' y el resto del login falla."""
    try:
        cursor.connection.rollback()
    except Exception:
        pass


def verificar_bloqueo(cursor, username):
    """Devuelve (bloqueado: bool, segundos_restantes: int) para un usuario."""
    try:
        row = cursor.execute(
            "SELECT bloqueado_hasta FROM login_intentos WHERE username = ?",
            (username,)).fetchone()
    except Exception:
        _reset_tx(cursor)
        return False, 0
    if not row:
        return False, 0
    bh = row[0]
    if not bh:
        return False, 0
    try:
        hasta = datetime.strptime(bh, _FMT)
    except (ValueError, TypeError):
        return False, 0
    ahora = _ahora()
    if hasta > ahora:
        return True, int((hasta - ahora).total_seconds())
    return False, 0


def registrar_fallo(cursor, username):
    """Suma un intento fallido; bloquea si supera el máximo.
    Devuelve (intentos, bloqueado: bool). El caller debe hacer commit."""
    try:
        row = cursor.execute(
            "SELECT intentos FROM login_intentos WHERE username = ?",
            (username,)).fetchone()
        intentos = (row[0] if row else 0) + 1
        bloqueado_hasta = None
        if intentos >= MAX_INTENTOS:
            bloqueado_hasta = (_ahora() + timedelta(minutes=BLOQUEO_MINUTOS)).strftime(_FMT)
        cursor.execute("""
            INSERT INTO login_intentos (username, intentos, ultimo_intento, bloqueado_hasta)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                intentos = excluded.intentos,
                ultimo_intento = excluded.ultimo_intento,
                bloqueado_hasta = excluded.bloqueado_hasta
        """, (username, intentos, _ahora().strftime(_FMT), bloqueado_hasta))
        return intentos, bloqueado_hasta is not None
    except Exception:
        _reset_tx(cursor)
        return 0, False


def registrar_exito(cursor, username):
    """Limpia los intentos fallidos tras un login correcto."""
    try:
        cursor.execute("DELETE FROM login_intentos WHERE username = ?", (username,))
    except Exception:
        _reset_tx(cursor)


def hash_password(password: str) -> str:
    """Genera un hash PBKDF2 con sal aleatoria para una contraseña nueva."""
    salt = os.urandom(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def _es_legacy_sha256(stored: str) -> bool:
    if not stored or len(stored) != 64:
        return False
    try:
        int(stored, 16)
        return True
    except ValueError:
        return False


def verify_password(stored_hash: str, password: str) -> bool:
    """Verifica una contraseña contra el hash almacenado (PBKDF2 o SHA-256 legacy)."""
    if not stored_hash:
        return False
    password = password or ""

    if stored_hash.startswith(_ALGO + "$"):
        try:
            _algo, iters, salt_hex, hash_hex = stored_hash.split("$", 3)
            dk = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"),
                bytes.fromhex(salt_hex), int(iters),
            )
            return hmac.compare_digest(dk.hex(), hash_hex)
        except (ValueError, TypeError):
            return False

    if _es_legacy_sha256(stored_hash):
        calc = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(calc, stored_hash)

    return False


def needs_rehash(stored_hash: str) -> bool:
    """True si el hash está en formato legacy y conviene re-generarlo (al loguear)."""
    return _es_legacy_sha256(stored_hash or "")
