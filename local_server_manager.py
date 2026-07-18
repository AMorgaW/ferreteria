# -*- coding: utf-8 -*-
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from local_first_config import admin_server_url, load_config
from services.local_api_client import LocalAPIClient, LocalAPIError


BASE_DIR = Path(__file__).resolve().parent


def detect_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class LocalServerManager:
    def __init__(self, config=None):
        self.config = config or load_config()
        self.process = None
        self._lock = threading.Lock()

    def sync_enabled(self):
        """La sincronización con Supabase se arranca solo si ambos flags están activos."""
        return (bool(self.config.get("auto_start_sync", True))
                and bool(self.config.get("supabase_enabled", True)))

    def is_active(self):
        return self.status().get("active", False)

    @property
    def port(self):
        return int(self.config.get("server_port", 8000))

    @property
    def host(self):
        return str(self.config.get("server_host", "0.0.0.0"))

    @property
    def local_url(self):
        return admin_server_url(self.config)

    @property
    def lan_url(self):
        scheme = "https" if self.config.get("usar_https") else "http"
        return f"{scheme}://{detect_local_ip()}:{self.port}"

    def status(self):
        client = LocalAPIClient(self.local_url, timeout=1.5)
        try:
            info = client.health()
            return {"active": True, "info": info, "url": self.lan_url}
        except LocalAPIError as exc:
            return {"active": False, "error": str(exc), "url": self.lan_url}

    def start(self, wait_ready=False, timeout=8.0):
        """Arranca el servidor local si no está ya activo. Idempotente y
        seguro entre hilos (lock). Si `wait_ready`, espera hasta que responda."""
        with self._lock:
            status = self.status()
            if status.get("active"):
                status["already_running"] = True
                status["sync"] = self.sync_enabled()
                return status

            creation_flags = 0
            if os.name == "nt":
                creation_flags = subprocess.CREATE_NO_WINDOW
            env = os.environ.copy()
            env.setdefault("DB_MODE", "local")
            env.setdefault("LOCAL_SERVER_PORT", str(self.port))
            env.setdefault("LOCAL_SERVER_HOST", self.host)

            if getattr(sys, "frozen", False):
                # Ejecutable empaquetado: relanzar el propio .exe en modo servidor.
                cmd = [sys.executable, "--serve", "--host", self.host, "--port", str(self.port)]
                work_dir = str(Path(sys.executable).resolve().parent)
            else:
                cmd = [sys.executable, str(BASE_DIR / "local_server.py"),
                       "--host", self.host, "--port", str(self.port)]
                work_dir = str(BASE_DIR)

            # Respetar la configuración: si la sync está deshabilitada, no la arranca.
            if not self.sync_enabled():
                cmd.append("--no-sync")

            # HTTPS opcional (cert autofirmado en LAN).
            if self.config.get("usar_https"):
                cmd.append("--https")

            try:
                self.process = subprocess.Popen(
                    cmd,
                    cwd=work_dir,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags,
                )
            except Exception as exc:
                return {"active": False, "started": False,
                        "error": str(exc), "url": self.lan_url}

            result = {"active": False, "started": True, "sync": self.sync_enabled(),
                      "url": self.lan_url, "pid": getattr(self.process, "pid", None)}

        if wait_ready:
            result["active"] = self.wait_ready(timeout)
        return result

    def wait_ready(self, timeout=8.0, interval=0.4):
        """Espera (bloqueante) a que el servidor responda /health. Devuelve bool.
        Pensado para llamarse desde un hilo en segundo plano."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.status().get("active"):
                return True
            # Si el proceso lanzado murió, no tiene sentido seguir esperando.
            if self.process is not None and self.process.poll() is not None:
                break
            time.sleep(interval)
        return self.status().get("active", False)

    def ensure_running(self, wait_ready=True, timeout=8.0):
        """Garantiza que el servidor esté corriendo; lo arranca si hace falta."""
        return self.start(wait_ready=wait_ready, timeout=timeout)

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
            return {"stopped": True}
        return {"stopped": False, "message": "El servidor no fue iniciado por esta sesion."}
