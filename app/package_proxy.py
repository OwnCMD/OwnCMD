"""Authenticated public TCP CONNECT / HTTP proxy with live account policy.
No TLS interception. Private/metadata networks are always unreachable.
"""

import asyncio, base64, hashlib, hmac, os, re, socket
from urllib.parse import urlsplit
from . import code_network

HOSTS = frozenset(code_network.DEFAULT_HOSTS)
SECRET = os.environ["ASTER_BROKER_KEY"]
slots = asyncio.Semaphore(32)


def credential(task):
    if not re.fullmatch(r"[a-f0-9-]{36}", task):
        raise ValueError("Invalid task")
    return hmac.new(
        SECRET.encode(), ("packages:" + task).encode(), hashlib.sha256
    ).hexdigest()


def identity(value):
    scheme, data = value.split(" ", 1)
    task, token = base64.b64decode(data, validate=True).decode().split(":", 1)
    if scheme.lower() != "basic" or not hmac.compare_digest(token, credential(task)):
        raise ValueError("Unauthorized")
    return task


def authorized(value):
    try:
        identity(value)
        return True
    except Exception:
        return False


def authority(value):
    parsed = urlsplit("//" + value)
    if (
        parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not parsed.hostname
        or not parsed.port
    ):
        raise ValueError("Invalid target")
    host = parsed.hostname.encode("idna").decode().lower().rstrip(".")
    if "%" in host:
        raise ValueError("Invalid target")
    return host, parsed.port


def target(value):
    # Compatibility helper for the shipped HTTPS-only default policy.
    host, port = authority(value)
    if host not in HOSTS or port != 443:
        raise ValueError("Registry not allowed")
    return host, port


async def public_addresses(host, port):
    addresses = await asyncio.wait_for(
        asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM), 10
    )
    ips = list(dict.fromkeys(a[4][0] for a in addresses))
    if not ips or any(not code_network.public_ip(ip) for ip in ips):
        raise ValueError("Non-public destination address")
    return sorted(ips, key=lambda ip: ":" in ip)


async def public_address(host, port):
    return (await public_addresses(host, port))[0]


async def policy(task):
    return await asyncio.to_thread(code_network.task_policy, task)


async def handle(reader, writer):
    upstream = None
    jobs = []
    try:
        async with slots:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            if len(header) > 8192:
                raise ValueError("Headers too large")
            lines = header.decode("ascii").split("\r\n")
            method, url, version = lines[0].split()
            if version not in ("HTTP/1.0", "HTTP/1.1"):
                raise ValueError("Invalid HTTP version")
            pairs = [line.split(":", 1) for line in lines[1:] if line]
            if any(len(p) != 2 for p in pairs):
                raise ValueError("Invalid headers")
            headers = {k.lower().strip(): v.strip() for k, v in pairs}
            if len(headers) != len(pairs):
                raise ValueError("Duplicate headers")
            if not headers.get("proxy-authorization"):
                writer.write(
                    b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="OwnCMD coding"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'
                )
                await writer.drain()
                return
            task = identity(headers["proxy-authorization"])
            plain = method != "CONNECT"
            if plain:
                if method not in (
                    "GET",
                    "HEAD",
                    "POST",
                    "PUT",
                    "PATCH",
                    "DELETE",
                    "OPTIONS",
                ):
                    raise ValueError("Unsupported method")
                parsed = urlsplit(url)
                if (
                    parsed.scheme != "http"
                    or parsed.username
                    or parsed.password
                    or not parsed.hostname
                    or parsed.fragment
                ):
                    raise ValueError("Use HTTP absolute URI or CONNECT")
                host = parsed.hostname.encode("idna").decode().lower().rstrip(".")
                port = parsed.port or 80
            else:
                host, port = authority(url)
            current = await policy(task)
            ips = await public_addresses(host, port)
            allowed = [
                ip for ip in ips if code_network.permits(current, host, ip, port)
            ]
            if not allowed:
                raise ValueError("Destination not allowed")
            for ip in allowed:
                try:
                    up, upstream = await asyncio.wait_for(
                        asyncio.open_connection(ip, port), 10
                    )
                    break
                except (OSError, asyncio.TimeoutError):
                    continue
            if upstream is None:
                raise ValueError("Destination unavailable")
            if not code_network.permits(await policy(task), host, ip, port):
                raise ValueError("Policy changed")
            if plain:
                # One request per connection. Never forward proxy credentials or honor a
                # second absolute destination on a keepalive/pipelined connection.
                if "transfer-encoding" in headers:
                    raise ValueError("Use Content-Length for HTTP requests")
                length = int(headers.get("content-length", "0"))
                if not 0 <= length <= 512 * 1024 * 1024:
                    raise ValueError("Invalid body length")
                if headers.get("expect"):
                    raise ValueError("Expect is unsupported; use HTTPS")
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                host_header = ("[" + host + "]" if ":" in host else host) + (
                    ":" + str(port) if port != 80 else ""
                )
                blocked = {
                    "host",
                    "connection",
                    "proxy-authorization",
                    "proxy-connection",
                    "keep-alive",
                    "upgrade",
                    "te",
                    "trailer",
                } | {
                    v.strip().lower() for v in headers.get("connection", "").split(",")
                }
                forwarded = "".join(
                    k + ": " + v + "\r\n"
                    for k, v in pairs
                    if k.lower().strip() not in blocked
                )
                upstream.write(
                    (
                        f"{method} {path} HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n"
                        + forwarded
                        + "\r\n"
                    ).encode("ascii")
                )
                await upstream.drain()
            else:
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()

            async def pipe(src, dst, remaining=None):
                total = 0
                while remaining is None or remaining > 0:
                    chunk = await asyncio.wait_for(
                        src.read(
                            min(65536, remaining) if remaining is not None else 65536
                        ),
                        60,
                    )
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 512 * 1024 * 1024:
                        raise ValueError("Transfer limit")
                    dst.write(chunk)
                    await dst.drain()
                    if remaining is not None:
                        remaining -= len(chunk)
                if remaining:
                    raise ValueError("Incomplete HTTP body")

            async def watch():
                while True:
                    await asyncio.sleep(1)
                    if not code_network.permits(await policy(task), host, ip, port):
                        raise ValueError("Network access revoked")

            async def exchange():
                upload = asyncio.create_task(
                    pipe(reader, upstream, length if plain else None)
                )
                download = asyncio.create_task(pipe(up, writer))
                try:
                    if plain:
                        await upload
                        await download
                    else:
                        done, _ = await asyncio.wait(
                            [upload, download], return_when=asyncio.FIRST_COMPLETED
                        )
                        for job in done:
                            job.result()
                finally:
                    upload.cancel()
                    download.cancel()
                    await asyncio.gather(upload, download, return_exceptions=True)

            jobs = [asyncio.create_task(exchange()), asyncio.create_task(watch())]
            done, _ = await asyncio.wait(
                jobs, timeout=600, return_when=asyncio.FIRST_COMPLETED
            )
            for job in done:
                job.result()
    except Exception:
        if upstream is None:
            writer.write(
                b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
    finally:
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        if upstream:
            upstream.close()
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def main():
    server = await asyncio.start_server(handle, "172.31.0.1", 8093, limit=8192)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
