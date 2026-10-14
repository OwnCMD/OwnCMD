"""Interactive site setup and Caddy-managed HTTPS, using only the standard library."""

import argparse
import getpass
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import time
from urllib.parse import urlsplit

CONFIG = Path("/etc/aster/config.env")
CADDYFILE = Path("/etc/caddy/Caddyfile")
LOCAL_CA = Path("/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt")
LE_DIRECTORY = "https://acme-v02.api.letsencrypt.org/directory"


def read_config(path=CONFIG):
    return dict(
        line.split("=", 1)
        for line in path.read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )


def normalize_host(value):
    host = value.strip().lower().rstrip(".")
    if host == "localhost":
        return host
    try:
        address = ipaddress.ip_address(host)
        if address.version != 4:
            raise ValueError("Use a domain or public IPv4 address.")
        return str(address)
    except ValueError:
        if re.fullmatch(r"[0-9.]+", host):
            raise ValueError("Invalid IPv4 address.")
    if (
        len(host) > 253
        or "." not in host
        or not all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")
        )
    ):
        raise ValueError(
            "Enter a domain name only (no scheme, path, port, wildcard or spaces)."
        )
    if host.rsplit(".", 1)[-1] in {
        "localhost",
        "local",
        "internal",
        "invalid",
        "test",
        "example",
    }:
        raise ValueError("Use a public domain name or IPv4 address.")
    return host


def site_settings(values):
    origin = urlsplit(values["ASTER_ORIGIN"])
    host = normalize_host(origin.hostname or "")
    if (
        origin.scheme not in {"http", "https"}
        or origin.netloc != host
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError(
            "Use http:// or https:// followed by a hostname or IPv4 address, without a port or path."
        )
    if origin.scheme == "http":
        if values.get("ASTER_TLS_MODE", "none") != "none":
            raise ValueError("HTTP requires TLS mode none")
        return host, "none"
    try:
        ipaddress.ip_address(host)
        default = "internal"
    except ValueError:
        default = "letsencrypt"
    mode = values.get("ASTER_TLS_MODE", default)
    if mode not in {"letsencrypt", "internal"}:
        raise ValueError("Invalid ASTER_TLS_MODE.")
    if mode == "letsencrypt" and default == "internal":
        raise ValueError(
            "This installer uses Let's Encrypt for domains; IPv4 setup uses a private certificate."
        )
    return host, mode


def choose_tls(host, ask=input):
    if host == "localhost": return "internal"
    try:
        ipaddress.ip_address(host)
    except ValueError:
        while True:
            answer = (
                ask(
                    "Install a trusted Let's Encrypt certificate with automatic renewal? [Y/n] (No uses a private HTTPS certificate): "
                )
                .strip()
                .lower()
            )
            if answer in {"", "y", "yes"}:
                return "letsencrypt"
            if answer in {"n", "no"}:
                return "internal"
            print("Please enter yes or no.")
    print(
        "IP address selected: HTTPS will use a private certificate, which browsers do not trust by default."
    )
    return "internal"


def setup(path=CONFIG, ask=input, secret=getpass.getpass):
    if path.exists():
        return  # Upgrades preserve keys, origin and certificate choice.
    host = normalize_host(
        ask("Server hostname or IPv4 address [localhost]: ").strip() or "localhost"
    )
    use_tls = ask(
        "Enable HTTPS certificates? [y/N] (optional; HTTP works without a domain): "
    ).strip().lower() in {"y", "yes"}
    mode = choose_tls(host, ask) if use_tls else "none"
    if mode == "none":
        print(
            "HTTP selected. Use a trusted local network or SSH tunnel; use HTTPS before sending credentials over the public internet."
        )
    print(
        "API keys are OPTIONAL. Press Enter to skip. Add or change them later in Instance settings > Providers."
    )
    openrouter = secret("OpenRouter API key (optional): ").strip()
    exa = secret("Exa API key (optional): ").strip()
    if any(
        key and not re.fullmatch(r"[A-Za-z0-9_-]+", key) for key in (openrouter, exa)
    ):
        raise ValueError("Invalid API key format.")
    import base64

    values = {
        "ASTER_ORIGIN": ("http://" if mode == "none" else "https://") + host,
        "ASTER_TLS_MODE": mode,
        "OPENROUTER_API_KEY": openrouter,
        "EXA_API_KEY": exa,
        "ASTER_MASTER_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "ASTER_BROKER_KEY": secrets.token_hex(32),
        "OWNCMD_EDITION": "community",
        "OWNCMD_SETUP_TOKEN": secrets.token_urlsafe(32),
        "ASTER_CHAT_MODEL": "google/gemini-3.5-flash-lite",
        "ASTER_WORK_MODEL": "openai/gpt-5.6-luna",
        "ASTER_TASK_BUDGET": "1",
        "ASTER_DAILY_BUDGET": "5",
        "ASTER_SANDBOXES": "2",
        "ASTER_EXA_RESULTS": "8",
        "ASTER_DATA": "/var/lib/aster",
    }
    # Exclusive creation: never replace a configuration created by another process.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("".join(key + "=" + value + "\n" for key, value in values.items()))


def render_caddy(values):
    host, mode = site_settings(values)
    if mode == "none":
        bind = "    bind 127.0.0.1\n" if host == "localhost" else ""
        return (
            "# OwnCMD Community: explicit HTTP disables automatic TLS.\nhttp://"
            + host
            + " {\n"
            + bind
            + "    encode gzip\n    request_body {\n        max_size 26MB\n    }\n    reverse_proxy 127.0.0.1:8000\n}\n"
        )
    tls = (
        "    tls {\n        issuer acme {\n            dir "
        + LE_DIRECTORY
        + "\n        }\n    }\n"
        if mode == "letsencrypt"
        else "    tls internal\n"
    )
    return (
        "# Managed by OwnCMD\n{\n    skip_install_trust\n}\n\n"
        + host
        + " {\n"
        + tls
        + "    encode gzip\n"
        "    request_body {\n        max_size 26MB\n    }\n"
        "    reverse_proxy 127.0.0.1:8000\n}\n"
    )


def configure(values):
    content = render_caddy(values)
    candidate = CADDYFILE.with_name("Caddyfile.aster-new")
    candidate.write_text(content)
    candidate.chmod(0o640)
    shutil.chown(candidate, user="root", group="caddy")
    try:
        subprocess.run(
            ["caddy", "fmt", "--overwrite", str(candidate)], check=True, timeout=20
        )
        subprocess.run(
            [
                "runuser",
                "-u",
                "caddy",
                "--",
                "caddy",
                "validate",
                "--adapter",
                "caddyfile",
                "--config",
                str(candidate),
            ],
            check=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        candidate.replace(CADDYFILE)
    finally:
        candidate.unlink(missing_ok=True)
    # Permit web traffic through an active UFW policy without changing SSH or defaults.
    if shutil.which("ufw"):
        status = subprocess.run(
            ["ufw", "status"], check=True, text=True, capture_output=True, timeout=20
        )
        if "Status: active" in status.stdout:
            for port in ("80/tcp", "443/tcp"):
                subprocess.run(["ufw", "allow", port], check=True, timeout=20)


def probe_https(host, mode):
    if mode == "none":
        connection = http.client.HTTPConnection("127.0.0.1", 80, timeout=5)
        try:
            connection.request("GET", "/health", headers={"Host": host})
            response = connection.getresponse()
            if (
                response.status != 200
                or json.loads(response.read(65536)).get("ok") is not True
            ):
                raise ValueError("HTTP readiness check failed")
        finally:
            connection.close()
        return
    # Connect to this server, retaining SNI/hostname verification; a CDN cannot mask
    # a broken local certificate. Never use an unverified TLS context.
    context = ssl.create_default_context(
        cafile=str(LOCAL_CA) if mode == "internal" else None
    )
    with socket.create_connection(("127.0.0.1", 443), timeout=5) as sock:
        with context.wrap_socket(sock, server_hostname=host) as secured:
            secured.sendall(
                (
                    "GET /health HTTP/1.1\r\nHost: "
                    + host
                    + "\r\nConnection: close\r\n\r\n"
                ).encode("ascii")
            )
            response = http.client.HTTPResponse(secured)
            response.begin()
            if response.status != 200:
                raise ValueError("HTTPS health check returned " + str(response.status))
            body = json.loads(response.read(65536))
            if body.get("ok") is not True:
                raise ValueError("HTTPS health check did not return OwnCMD readiness.")
    connection = http.client.HTTPConnection("127.0.0.1", 80, timeout=5)
    try:
        connection.request("GET", "/health", headers={"Host": host})
        response = connection.getresponse()
        if (
            response.status not in (301, 302, 307, 308)
            or response.getheader("Location") != "https://" + host + "/health"
        ):
            raise ValueError("HTTP-to-HTTPS redirect verification failed.")
    finally:
        connection.close()


def verify(
    values, timeout=180, probe=probe_https, clock=time.monotonic, wait=time.sleep
):
    host, mode = site_settings(values)
    deadline = clock() + timeout
    while True:
        try:
            probe(host, mode)
            print(
                (
                    "HTTP readiness verified for "
                    if mode == "none"
                    else "HTTPS readiness verified for "
                )
                + host
                + "."
            )
            if mode == "letsencrypt":
                print("Caddy manages Let's Encrypt issuance and automatic renewal.")
            elif mode == "internal":
                print(
                    "Private certificate in use; trust the Caddy CA on each client to avoid browser warnings."
                )
            return
        except (OSError, ValueError, http.client.HTTPException):
            if clock() >= deadline:
                raise RuntimeError(
                    "HTTPS verification failed. Check domain DNS A/AAAA records, inbound TCP 80/443, "
                    "CAA permission for letsencrypt.org, and journalctl -u caddy. "
                    "Correct the issue and rerun; existing data and credentials are retained."
                ) from None
            print("Waiting for HTTPS certificate and site readiness...", flush=True)
            wait(min(5, max(0, deadline - clock())))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "configure", "verify"))
    action = parser.parse_args().action
    if action == "setup":
        setup()
    elif action == "configure":
        configure(read_config())
    else:
        verify(read_config())
