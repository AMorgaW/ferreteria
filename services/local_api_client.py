# -*- coding: utf-8 -*-
import json
import socket
import ssl
from urllib import error, parse, request


class LocalAPIError(Exception):
    pass


class LocalAPIClient:
    def __init__(self, base_url, timeout=4):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.token = None
        self.user = None
        # El servidor LAN usa un certificado autofirmado: ciframos el tráfico
        # pero no verificamos la cadena (red local de confianza).
        self._ssl_ctx = ssl._create_unverified_context()

    def set_base_url(self, base_url):
        self.base_url = base_url.rstrip("/")

    def health(self):
        return self._request("GET", "/health", authenticated=False)

    def server_info(self):
        return self._request("GET", "/server/info", authenticated=False)

    def login(self, username, password):
        result = self._request(
            "POST",
            "/auth/login",
            {"username": username, "password": password},
            authenticated=False,
        )
        self.token = result["token"]
        self.user = result["user"]
        return result

    def get_products(self, search=None, limit=100, offset=0):
        return self._request(
            "GET",
            "/products",
            query={"search": search or "", "limit": limit, "offset": offset},
        )["products"]

    def get_product(self, product_id):
        return self._request("GET", f"/products/{int(product_id)}")["product"]

    def get_product_by_code(self, code):
        encoded = parse.quote(str(code), safe="")
        return self._request("GET", f"/products/code/{encoded}")["product"]

    def get_customers(self, search=None, limit=100, offset=0):
        return self._request(
            "GET",
            "/customers",
            query={"search": search or "", "limit": limit, "offset": offset},
        )["customers"]

    def create_customer(self, payload):
        return self._request("POST", "/customers", payload)["customer"]

    def create_sale(self, payload):
        return self._request("POST", "/sales", payload)

    def get_sale(self, sale_id):
        return self._request("GET", f"/sales/{int(sale_id)}")

    def get_sync_status(self):
        return self._request("GET", "/sync/status")

    def get_sync_queue(self, limit=100):
        return self._request("GET", "/sync/queue", query={"limit": limit})["queue"]

    def run_sync(self):
        return self._request("POST", "/sync/run", {})

    def retry_sync(self):
        return self._request("POST", "/sync/retry", {})

    def test_supabase(self):
        return self._request("POST", "/sync/test", {})

    def _request(self, method, path, payload=None, query=None, authenticated=True):
        url = self.base_url + path
        if query:
            url += "?" + parse.urlencode(query)

        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        if authenticated:
            if not self.token:
                raise LocalAPIError("Debes iniciar sesion.")
            headers["Authorization"] = f"Bearer {self.token}"

        req = request.Request(url, data=body, headers=headers, method=method)
        ctx = self._ssl_ctx if url.lower().startswith("https") else None
        try:
            with request.urlopen(req, timeout=self.timeout, context=ctx) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            message = f"Error HTTP {exc.code}"
            try:
                data = json.loads(exc.read().decode("utf-8"))
                message = data.get("error") or message
            except (ValueError, UnicodeDecodeError):
                pass
            raise LocalAPIError(message) from exc
        except error.URLError as exc:
            if isinstance(exc.reason, socket.timeout):
                raise LocalAPIError("Tiempo de espera agotado al conectar con el servidor local.") from exc
            raise LocalAPIError(
                "Servidor local no encontrado. Verifica que el PC administrador este encendido y que la IP sea correcta."
            ) from exc
        except socket.timeout as exc:
            raise LocalAPIError("Tiempo de espera agotado al conectar con el servidor local.") from exc
        except json.JSONDecodeError as exc:
            raise LocalAPIError("El servidor respondio, pero devolvio datos invalidos.") from exc
        except (ConnectionError, ssl.SSLError, OSError) as exc:
            raise LocalAPIError(
                "No se pudo establecer la conexion con el servidor local "
                "(verifica si el servidor usa HTTP o HTTPS)."
            ) from exc
