# -*- coding: utf-8 -*-
"""
Generación de certificado TLS autofirmado para el servidor local (LAN).

Cifra el tráfico entre las cajas y el servidor (contraseña/token ya no viajan
en claro). Al ser autofirmado, los clientes no verifican la cadena (uso en LAN
de confianza); protege contra sniffing pasivo en la red del local.
"""
import datetime
import ipaddress
import os
import socket


def _cert_dir():
    from local_first_db import DEFAULT_DB_PATH
    d = os.path.join(os.path.dirname(os.path.abspath(DEFAULT_DB_PATH)), "certs")
    os.makedirs(d, exist_ok=True)
    return d


def _detectar_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def crear_cert_si_falta():
    """Devuelve (cert_path, key_path), generándolos si no existen."""
    d = _cert_dir()
    cert_path = os.path.join(d, "server.crt")
    key_path = os.path.join(d, "server.key")
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path

    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ip_lan = _detectar_ip()
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FerreteriaLocal")])
    san = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    try:
        san.append(x509.IPAddress(ipaddress.ip_address(ip_lan)))
    except ValueError:
        pass

    ahora = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - datetime.timedelta(days=1))
        .not_valid_after(ahora + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(key, hashes.SHA256())
    )

    with open(key_path, "wb") as fh:
        fh.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    with open(cert_path, "wb") as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path
