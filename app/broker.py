# The only host process allowed to talk to Docker. Fixed image, runtime, paths and options.
import asyncio, os, re, json, time, hmac, hashlib, base64, io, zipfile, mimetypes
from pathlib import Path
from . import core, browser_state, billing
from .package_proxy import credential
from .workspace_storage import workspace_mount
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
import httpx

app = FastAPI()
gate = asyncio.Lock()
touch = {}
urls = {}
inuse = set()
uses = {}
session_base = {}
retiring = set()
started_at = {}
stopping = {}
starting = {}
SECRET = os.environ["ASTER_BROKER_KEY"]
SOFT_MAX = max(2, int(os.getenv("ASTER_SANDBOXES", "2")))


def sandbox_headers(task, kind="code"):
    token = hmac.new(
        SECRET.encode(), ("sandbox:" + kind + ":" + task).encode(), hashlib.sha256
    ).hexdigest()
    return {"X-Aster-Sandbox": token}


async def cmd(*args):
    p = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        o, e = await asyncio.wait_for(p.communicate(), 60)
    except asyncio.TimeoutError:
        p.kill()
        await p.wait()
        raise HTTPException(503, "Container operation timed out")
    except BaseException:
        if p.returncode is None:
            try:
                p.kill()
            except ProcessLookupError:
                pass
            await p.wait()
        raise
    if p.returncode:
        raise HTTPException(
            503, "Container operation failed: " + e.decode(errors="replace")[:500]
        )
    return o.decode().strip()


def name(task, kind="code"):
    if not re.fullmatch(r"[a-f0-9-]{36}", task):
        raise HTTPException(400, "Invalid task ID")
    return "aster-" + kind + "-" + task


def forget(n):
    billing.stop_runtime(n, now=stopping.get(n))
    human_session_saved.pop(n.removeprefix("aster-browser-"), None)
    key = n.removeprefix("aster-browser-")
    lock = session_save_locks.get(key)
    if lock is not None and not lock.locked():
        session_save_locks.pop(key, None)
    touch.pop(n, None)
    urls.pop(n, None)
    started_at.pop(n, None)
    inuse.discard(n)
    uses.pop(n, None)
    stopping.pop(n, None)


def victim_key(n):
    # Code workspaces are checkpointed after mutations, so evict them before browser sessions.
    return (0 if n.startswith("aster-code-") else 1, touch.get(n, 0))


def use(n):
    uses[n] = uses.get(n, 0) + 1
    inuse.add(n)


def unuse(n):
    uses[n] = max(0, uses.get(n, 1) - 1)
    if not uses[n]:
        inuse.discard(n)


def task_owner(task):
    with core.db() as c:
        r = c.execute("SELECT owner FROM tasks WHERE id=%s", (task,)).fetchone()
    return r["owner"] if r else None


session_save_locks = {}


async def save_session(task, url):
    # A periodic checkpoint and the final stop must never persist snapshots out of order.
    async with session_save_locks.setdefault(task, asyncio.Lock()):
        owner = task_owner(task)
        if not owner:
            return
        async with httpx.AsyncClient(
            timeout=12, headers=sandbox_headers(task, "browser")
        ) as c:
            response = await c.post(url + "/session", json={})
            response.raise_for_status()
        current = response.json()
        session_base[task] = browser_state.save(
            owner, session_base.get(task, browser_state.EMPTY), current
        )


def saved_archive(task):
    name(task)  # Validate task identity before deriving the checkpoint filename.
    path = core.DATA / "snapshots" / (task + ".enc")
    if not path.exists():
        return None
    try:
        data = base64.b64decode(core.dec(path.read_text()), validate=True)
        if len(data) > 128 * 1024 * 1024:
            raise ValueError("Checkpoint exceeds archive limit")
        return data
    except Exception:
        raise HTTPException(503, "Saved project checkpoint could not be read")


def saved_file(task, body):
    data = saved_archive(task)
    op = body.get("op")
    path = str(body.get("path", ""))
    if path.startswith("/work/"):
        path = path[6:]
    if path.startswith("./"):
        path = path[2:]
    if op != "list" and (
        not path
        or path.startswith("/")
        or any(p in ("", "..") for p in path.split("/"))
        or "\\" in path
    ):
        raise HTTPException(400, "Invalid workspace path")
    if data is None:
        if op == "list":
            return {"files": []}
        raise HTTPException(404, "Saved file not found")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if op == "list":
            return {
                "files": sorted(
                    i.filename
                    for i in archive.infolist()
                    if not i.is_dir()
                    and not i.filename.startswith(".config/go/telemetry/")
                )[:5000]
            }
        try:
            entry = archive.getinfo(path)
        except KeyError:
            raise HTTPException(404, "Saved file not found")
        limit = 50000 if op == "read" else 20 * 1024 * 1024
        if op == "download" and entry.file_size > limit:
            raise HTTPException(
                413, "File too large to download individually; export the project"
            )
        with archive.open(entry) as f:
            raw = f.read(limit + 1)
        if op == "download":
            return {"name": Path(path).name, "data": base64.b64encode(raw).decode()}
        if b"\x00" in raw[:4096]:
            raise HTTPException(400, "Binary files can be downloaded but not previewed")
        content = raw[:limit].decode(errors="replace")
        return {
            "content": content,
            "size": entry.file_size,
            "lines": content.count("\n") + 1,
            "truncated": entry.file_size > limit,
        }


async def checkpoint_container(n):
    url = urls.get(n)
    if not url:
        return
    task = n.removeprefix("aster-code-").removeprefix("aster-browser-")
    if n.startswith("aster-browser-"):
        await save_session(task, url)
        return
    async with httpx.AsyncClient(timeout=60, headers=sandbox_headers(task)) as c:
        result = await c.post(url + "/snapshot", json={})
        result.raise_for_status()
        data = result.json()["data"]
    path = core.DATA / "snapshots"
    path.mkdir(mode=0o700, exist_ok=True)
    tmp = path / (task + ".broker.tmp")
    tmp.write_text(core.enc(data))
    tmp.chmod(0o600)
    # The broker is root, but API/worker processes run as the data directory owner.
    if os.geteuid() == 0:
        owner = core.DATA.stat()
        os.chown(path, owner.st_uid, owner.st_gid)
        os.chown(tmp, owner.st_uid, owner.st_gid)
    tmp.replace(path / (task + ".enc"))


def stop_meter(n, at=None):
    # Freeze the cutoff before any slow checkpoint/removal. Cleanup failures never
    # renew a stopped meter; the maintenance loop will retry resource cleanup.
    stopping.setdefault(n, time.time() if at is None else at)
    billing.stop_runtime(n, now=stopping[n])


async def retire(n, at=None):
    if n in retiring:
        raise HTTPException(503, "Workspace is being saved; retry shortly")
    retiring.add(n)
    warning = None
    try:
        stop_meter(n, at)
        try:
            await checkpoint_container(n)
        except Exception:
            if not n.startswith("aster-browser-"):
                raise
            import logging

            logging.exception("Final browser session save failed")
            warning = "Browser stopped and runtime ended. The last sign-in changes could not be saved."
        try:
            await cmd("rm", "-f", "-v", n)
        except HTTPException as e:
            if "No such container" not in str(e.detail):
                raise
        forget(n)
        return {"stopped": True, **({"session_warning": warning} if warning else {})}
    finally:
        retiring.discard(n)


def existing_endpoint(task, kind):
    n = name(task, kind)
    if n in starting and n not in stopping and n not in retiring:
        raise HTTPException(
            503, "Browser is starting" if kind == "browser" else "Workspace is starting"
        )
    if n in stopping or n in retiring or n not in urls:
        raise HTTPException(
            410,
            (
                "Browser stopped; runtime stopped. Start it to continue."
                if kind == "browser"
                else "Workspace stopped. Reopen it from Workspace."
            ),
        )
    return urls[n]


async def inspect_url(n, kind):
    data = json.loads(await cmd("inspect", n))[0]
    try:
        started_at[n] = (
            __import__("datetime")
            .datetime.fromisoformat(data["State"]["StartedAt"].replace("Z", "+00:00"))
            .timestamp()
        )
    except (ValueError, KeyError):
        started_at.setdefault(n, time.time())
    network = "aster-sandbox" if kind == "browser" else "aster-code"
    ip = (data.get("NetworkSettings", {}).get("Networks", {}).get(network) or {}).get(
        "IPAddress"
    )
    if not ip:
        raise HTTPException(
            503, f"{kind.capitalize()} sandbox has no {network} address"
        )
    return "http://" + ip + ":8001"


async def endpoint(task, create=True, kind="code"):
    n = name(task, kind)
    track = create and n not in urls
    if track:
        starting[n] = starting.get(n, 0) + 1
    try:
        return await _endpoint(task, create, kind)
    finally:
        if track:
            starting[n] -= 1
            if starting[n] <= 0:
                starting.pop(n, None)


async def _endpoint(task, create=True, kind="code"):
    from . import accounts

    owner = task_owner(task)
    if owner:
        try:
            accounts.require(owner, kind)
        except ValueError as e:
            raise HTTPException(403, str(e))
    n = name(task, kind)
    if n in retiring or n in stopping:
        raise HTTPException(503, "Workspace is stopping; retry shortly")
    touch[n] = time.time()
    if n in urls:
        try:
            billing.start_runtime(n, task, kind)
        except billing.CreditError as e:
            raise HTTPException(402, str(e))
        return urls[n]
    deadline = time.monotonic() + 115
    while True:
        wait = False
        async with gate:
            if n in urls:
                return urls[n]
            running = (
                await cmd(
                    "ps", "--filter", "label=aster.sandbox=1", "--format", "{{.Names}}"
                )
            ).splitlines()
            for stale in list(urls):
                if stale not in running:
                    forget(stale)
            newly_created = n not in running
            if n not in running:
                if not create:
                    raise HTTPException(404, "Sandbox is not running")
                if len(running) >= SOFT_MAX:
                    candidates = [
                        x
                        for x in running
                        if x not in inuse and x not in retiring and x != n
                    ]
                    if candidates:
                        victim = min(candidates, key=victim_key)
                        await retire(victim)
                        running = [x for x in running if x != victim]
                    else:
                        wait = True
                if not wait:
                    runtime = "runsc-browser" if kind == "browser" else "runsc"
                    network = "aster-sandbox" if kind == "browser" else "aster-code"
                    execution = "exec" if kind == "code" else "noexec"
                    limits = (
                        accounts.effective(owner)["limits"]
                        if owner
                        else accounts.defaults()["limits"]
                    )
                    work_mb = limits["workspace_mb"] if kind == "code" else 1536
                    work_files = limits["workspace_files"] if kind == "code" else 100000
                    args = [
                        "run",
                        "-d",
                        "--rm",
                        "--name",
                        n,
                        "--label",
                        "aster.sandbox=1",
                        "--runtime=" + runtime,
                        "--network",
                        network,
                        "--memory",
                        (
                            os.getenv("ASTER_CODE_MEMORY", "2048m")
                            if kind == "code"
                            else "1024m"
                        ),
                        "--cpus",
                        os.getenv("ASTER_CODE_CPUS", "2") if kind == "code" else "1",
                        "--pids-limit",
                        "512",
                        "--cap-drop=ALL",
                        "--security-opt",
                        "no-new-privileges",
                        "--read-only",
                        "-e",
                        "ASTER_SANDBOX_KIND=" + kind,
                        "-e",
                        "ASTER_SANDBOX_KEY="
                        + sandbox_headers(task, kind)["X-Aster-Sandbox"],
                        "--tmpfs",
                        "/tmp:rw,nosuid,nodev,"
                        + execution
                        + ",size=256m,uid=1000,gid=1000",
                        "--shm-size",
                        "128m",
                    ]
                    if kind == "code":
                        args += ["--mount", workspace_mount(work_mb, work_files)]
                    else:
                        args += [
                            "--tmpfs",
                            "/work:rw,nosuid,nodev,noexec,size=1536m,uid=1000,gid=1000",
                        ]
                    if kind == "code":
                        args += [
                            "-e",
                            "ASTER_WORKSPACE_MB=" + str(work_mb),
                            "-e",
                            "ASTER_WORKSPACE_FILES=" + str(work_files),
                        ]
                    if kind == "browser":
                        args += ["--dns", "1.1.1.1", "--dns", "8.8.8.8"]
                    if kind == "code":
                        proxy = (
                            "http://"
                            + task
                            + ":"
                            + credential(task)
                            + "@172.31.0.1:8093"
                        )
                        for key, value in {
                            "ASTER_CODE_PROXY": proxy,
                            "NODE_USE_ENV_PROXY": "1",
                            "HTTPS_PROXY": proxy,
                            "HTTP_PROXY": proxy,
                            "https_proxy": proxy,
                            "http_proxy": proxy,
                            "NO_PROXY": "localhost,127.0.0.1,::1",
                            "no_proxy": "localhost,127.0.0.1,::1",
                            "PIP_INDEX_URL": "https://pypi.org/simple",
                        }.items():
                            args += ["-e", key + "=" + value]
                    with core.db() as c:
                        display_row = c.execute(
                            "SELECT state FROM tasks WHERE id=%s", (task,)
                        ).fetchone()
                    display = (
                        core.state(display_row).get("browser_display")
                        if display_row
                        else None
                    )
                    if display:
                        args += [
                            "-e",
                            "ASTER_BROWSER_DISPLAY="
                            + json.dumps(display, separators=(",", ":")),
                        ]
                    args += ["aster-sandbox:3"]
                    try:
                        await cmd(*args)
                    except Exception:
                        await discard_failed_start(n)
                        raise
            if not wait:
                try:
                    url = await inspect_url(n, kind)
                except Exception:
                    if newly_created:
                        await discard_failed_start(n)
                    raise
                async with httpx.AsyncClient(
                    timeout=2, headers=sandbox_headers(task, kind)
                ) as c:
                    for _ in range(35):
                        try:
                            if (await c.get(url + "/health")).status_code == 200:
                                if kind == "code" and newly_created:
                                    from pathlib import Path
                                    from cryptography.fernet import Fernet

                                    snapshot = (
                                        Path(os.getenv("ASTER_DATA", "/var/lib/aster"))
                                        / "snapshots"
                                        / (task + ".enc")
                                    )
                                    if snapshot.exists():
                                        data = (
                                            Fernet(
                                                os.environ["ASTER_MASTER_KEY"].encode()
                                            )
                                            .decrypt(snapshot.read_bytes())
                                            .decode()
                                        )
                                        async with httpx.AsyncClient(
                                            timeout=30,
                                            headers=sandbox_headers(task, kind),
                                        ) as restore_client:
                                            rr = await restore_client.post(
                                                url + "/snapshot",
                                                json={"restore": data},
                                            )
                                            if rr.status_code == 409:
                                                await discard_failed_start(n)
                                                raise HTTPException(
                                                    409,
                                                    rr.json().get(
                                                        "detail",
                                                        "Saved workspace exceeds the account limits",
                                                    ),
                                                )
                                            rr.raise_for_status()
                                if kind == "browser" and newly_created:
                                    owner = task_owner(task)
                                    if owner:
                                        saved = browser_state.load(owner)
                                        session_base[task] = saved
                                        rr = await c.post(
                                            url + "/session",
                                            json={"restore": saved},
                                            timeout=15,
                                        )
                                        rr.raise_for_status()
                                try:
                                    billing.start_runtime(n, task, kind)
                                except billing.CreditError as e:
                                    await discard_failed_start(n)
                                    raise HTTPException(402, str(e))
                                urls[n] = url
                                started_at.setdefault(n, time.time())
                                return url
                        except httpx.HTTPError:
                            pass
                        await asyncio.sleep(0.25)
                try:
                    logs = await cmd("logs", "--tail", "30", n)
                except Exception:
                    logs = ""
                await discard_failed_start(n)
                raise HTTPException(
                    503, "Sandbox did not start" + (": " + logs[-400:] if logs else "")
                )
        if time.monotonic() > deadline:
            raise HTTPException(503, "Workspace capacity is busy; retry shortly")
        await asyncio.sleep(0.2)


async def discard_failed_start(n):
    # --rm handles normal exit; -v also releases the anonymous tmpfs volume on
    # explicit removal, including containers left behind by a failed docker run.
    # Keep failed removals visible to maintenance, without starting a charge.
    stop_meter(n)
    try:
        await cmd("rm", "-f", "-v", n)
    except HTTPException as e:
        if "No such container" not in str(e.detail):
            import logging

            logging.exception("Failed sandbox startup cleanup for %s", n)
            return
    forget(n)


@app.middleware("http")
async def auth(req, call_next):
    if not hmac.compare_digest(
        req.headers.get("authorization", ""), "Bearer " + SECRET
    ):
        return JSONResponse({"detail": "Unauthorized"}, 401)
    return await call_next(req)


human_session_saved = {}

_telemetry_cache = None
_telemetry_lock = asyncio.Lock()
_telemetry_history = []


@app.get("/telemetry")
async def telemetry_snapshot():
    global _telemetry_cache
    from . import telemetry

    async with _telemetry_lock:
        if _telemetry_cache and time.time() - _telemetry_cache["checked_at"] < 5:
            return _telemetry_cache
        host = telemetry.host_snapshot(core.DATA)
        host["cpu_percent"] = None
        try:
            before = telemetry.cpu_ticks()
            await asyncio.sleep(0.15)
            host["cpu_percent"] = telemetry.cpu_percent(before, telemetry.cpu_ticks())
        except (OSError, ValueError, IndexError):
            pass
        raw = await asyncio.wait_for(
            cmd("ps", "--filter", "label=aster.sandbox=1", "--format", "{{json .}}"), 5
        )
        rows = []
        for line in raw.splitlines():
            item = json.loads(line)
            n = item.get("Names", "")
            if not re.fullmatch(r"aster-(?:code|browser)-[a-f0-9-]{36}", n):
                continue
            kind = "browser" if n.startswith("aster-browser-") else "code"
            task = n.removeprefix("aster-" + kind + "-")
            rows.append(
                {
                    "name": n,
                    "task": task,
                    "kind": kind,
                    "owner": task_owner(task),
                    "status": item.get("Status", "Running"),
                    "started_at": started_at.get(n),
                    "stopping": n in stopping,
                    "cpu_percent": None,
                    "memory_percent": None,
                }
            )
        try:
            if rows:
                stats = await asyncio.wait_for(
                    cmd(
                        "stats",
                        "--no-stream",
                        "--format",
                        "{{json .}}",
                        *[r["name"] for r in rows],
                    ),
                    5,
                )
                by_name = {r["name"]: r for r in rows}
                for line in stats.splitlines():
                    item = json.loads(line)
                    r = by_name.get(item.get("Name"))
                    if r:
                        r["cpu_percent"] = float(item["CPUPerc"].rstrip("%"))
                        r["memory_percent"] = float(item["MemPerc"].rstrip("%"))
        except (HTTPException, asyncio.TimeoutError, ValueError, KeyError):
            pass
        with core.db() as c:
            metered = {r[0] for r in c.execute("SELECT name FROM runtime_meters")}
        for row in rows:
            row["billing_active"] = row["name"] in metered and not row["stopping"]
        _telemetry_history.append(
            {
                "time": host["checked_at"],
                "cpu": host["cpu_percent"],
                "memory": host["memory"]["percent"] if host["memory"] else None,
                "code": sum(r["kind"] == "code" for r in rows),
                "browser": sum(r["kind"] == "browser" for r in rows),
            }
        )
        del _telemetry_history[:-120]
        _telemetry_cache = {
            "available": True,
            "checked_at": host["checked_at"],
            "host": host,
            "runtimes": rows,
            "history": list(_telemetry_history),
        }
        return _telemetry_cache


@app.post("/task/{task}/{operation}")
async def dispatch(task: str, operation: str, req: Request):
    if operation in ("stop", "release", "stop-browser", "stop-code"):
        kinds = (
            (operation.removeprefix("stop-"),)
            if operation in ("stop-browser", "stop-code")
            else ("browser", "code")
        )
        retained = False
        warning = None
        for kind in kinds:
            n = name(task, kind)
            if operation in ("stop-browser", "stop-code") and n in inuse:
                raise HTTPException(
                    409, "Wait for the current browser action to finish"
                )
            if operation == "release" and n in inuse:
                continue
            if operation == "release" and kind == "browser":
                with core.db() as c:
                    row = c.execute(
                        "SELECT control FROM tasks WHERE id=%s", (task,)
                    ).fetchone()
                if row and row["control"] != "ai":
                    continue
            if operation == "release" and kind == "code" and n in urls:
                async with httpx.AsyncClient(
                    timeout=5, headers=sandbox_headers(task, kind)
                ) as c:
                    state = await c.post(urls[n] + "/services", json={"op": "list"})
                    state.raise_for_status()
                if any(
                    v.get("status") == "running"
                    for v in state.json().get("services", [])
                ):
                    await checkpoint_container(n)
                    retained = True
                    continue
            result = await retire(n)
            warning = result.get("session_warning") or warning
        return {
            "stopped": not retained,
            "retained": retained,
            "scope": (
                operation.removeprefix("stop-")
                if operation in ("stop-browser", "stop-code")
                else "all"
            ),
            **({"session_warning": warning} if warning else {}),
        }
    if operation == "resources":
        # Read-only: do not allocate, touch idle deadlines or start a billing meter.
        actual = set(
            (
                await cmd(
                    "ps", "--filter", "label=aster.sandbox=1", "--format", "{{.Names}}"
                )
            ).splitlines()
        )
        with core.db() as c:
            meters = {
                r["name"]: r
                for r in c.execute(
                    "SELECT name,started,expires FROM runtime_meters WHERE task=%s",
                    (task,),
                )
            }
        return {
            "runtimes": [
                {
                    "kind": kind,
                    "status": (
                        "stopping"
                        if name(task, kind) in stopping or name(task, kind) in retiring
                        else "running" if name(task, kind) in actual else "stopped"
                    ),
                    "billing_active": name(task, kind) in actual
                    and name(task, kind) in meters
                    and name(task, kind) not in stopping,
                    "started_at": started_at.get(name(task, kind)),
                }
                for kind in ("code", "browser")
            ]
        }
    if operation == "status":
        n = name(task)
        running = n in urls and n not in retiring and n not in stopping
        return {
            "status": (
                "stopping"
                if n in retiring or n in stopping
                else "running" if running else "stopped"
            ),
            "started_at": started_at.get(n),
            "uptime_seconds": (
                max(0, time.time() - started_at[n]) if n in started_at else 0
            ),
            "idle_timeout_seconds": 900,
            "hourly_rate": float(billing.runtime_rate("code")),
            "billing_active": running,
        }
    if operation not in (
        "action",
        "run",
        "file",
        "frame",
        "snapshot",
        "services",
        "dev-action",
        "terminal",
    ):
        raise HTTPException(400, "Unsupported operation")
    kind = "browser" if operation in ("action", "frame") else "code"
    n = name(task, kind)
    body = await req.json()
    if operation == "services" and body.get("op") == "list" and n not in urls:
        return {"services": []}
    if operation == "terminal" and body.get("op") != "open" and n not in urls:
        raise HTTPException(
            410, "Workspace stopped. Open a terminal to start a new session."
        )
    if operation == "dev-action" and n not in urls:
        raise HTTPException(
            410, "Workspace stopped. Start the app from Workspace services first."
        )
    if (
        operation == "file"
        and body.get("op") in ("list", "read", "download")
        and n not in urls
    ):
        return saved_file(task, body)
    passive = (
        operation == "frame"
        or (operation in ("action", "dev-action") and body.get("kind") == "resize")
        or (operation == "services" and body.get("op") == "list")
        or (operation == "terminal" and body.get("op") == "read")
    )
    if not passive:
        use(n)
    try:
        url = (
            existing_endpoint(task, kind)
            if passive
            else await endpoint(task, kind=kind)
        )
        async with httpx.AsyncClient(
            timeout=125, headers=sandbox_headers(task, kind)
        ) as c:
            try:
                r = (
                    await c.get(url + "/frame")
                    if operation == "frame"
                    else await c.post(url + "/" + operation, json=await req.json())
                )
            except httpx.HTTPError as e:
                stop_meter(n)
                raise HTTPException(503, "Sandbox connection failed: " + str(e)[:300])
        if (
            kind == "browser"
            and operation == "action"
            and body.get("kind") not in ("resize", "input", "selection")
            and r.is_success
        ):
            try:
                await save_session(task, url)
                human_session_saved[task] = time.monotonic()
            except Exception:
                # The website action has already happened. Never turn a successful purchase
                # or submission into a retryable action error because session saving failed.
                result = r.json()
                result["session_warning"] = (
                    "The browser action completed, but sign-in state could not be saved. You may need to sign in again after this browser closes."
                )
                return JSONResponse(result, status_code=r.status_code)
        return Response(
            r.content,
            status_code=r.status_code,
            media_type=r.headers.get("content-type", "application/json"),
        )
    finally:
        if not passive:
            if n not in stopping:
                touch[n] = time.time()
            unuse(n)


@app.get("/task/{task}/frame.jpg")
async def frame_jpg(task: str):
    url = existing_endpoint(task, "browser")
    async with httpx.AsyncClient(
        timeout=8, headers=sandbox_headers(task, "browser")
    ) as c:
        try:
            r = await c.get(url + "/frame.jpg")
        except httpx.HTTPError as e:
            raise HTTPException(503, "Browser frame unavailable: " + str(e)[:250])
    return Response(
        r.content,
        status_code=r.status_code,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            **{
                key: r.headers.get(key, "")
                for key in (
                    "X-Aster-Frame-Seq",
                    "X-Aster-Frame-Age",
                    "X-Aster-Frame-URL",
                )
            },
        },
    )


@app.get("/task/{task}/frame-stream")
async def browser_stream(task: str):
    from .preview_stream import relay

    url = existing_endpoint(task, "browser")
    return await relay(
        url + "/frame-stream",
        sandbox_headers(task, "browser"),
        lambda: existing_endpoint(task, "browser"),
    )


@app.get("/task/{task}/dev-stream")
async def development_stream(task: str):
    from .preview_stream import relay

    url = existing_endpoint(task, "code")
    return await relay(
        url + "/dev-stream",
        sandbox_headers(task),
        lambda: existing_endpoint(task, "code"),
    )


@app.get("/task/{task}/preview/{path:path}")
async def preview(task: str, path: str):
    n = name(task, "code")
    use(n)
    try:
        url = await endpoint(task, False)
        async with httpx.AsyncClient(timeout=15, headers=sandbox_headers(task)) as c:
            r = await c.get(url + "/preview/" + path)
        return Response(
            r.content,
            status_code=r.status_code,
            media_type=r.headers.get("content-type"),
        )
    finally:
        unuse(n)


BROWSER_IDLE_SECONDS = 900
BROWSER_INPUT_IDLE_SECONDS = 900
CODE_IDLE_SECONDS = 900


def runtime_cutoff(n, now):
    if n in stopping:
        return stopping[n]
    kind = "browser" if n.startswith("aster-browser-") else "code"
    owner = task_owner(n.removeprefix("aster-" + kind + "-"))
    if owner:
        from . import accounts

        p = accounts.effective(owner)
        if p["disabled"] or not p["features"][kind]:
            return now
    last = touch.get(n)
    idle = BROWSER_IDLE_SECONDS if kind == "browser" else CODE_IDLE_SECONDS
    if last is None or n not in urls:
        return now  # unclaimed/orphaned container
    if kind == "browser":
        task = n.removeprefix("aster-browser-")
        with core.db() as c:
            row = c.execute(
                "SELECT status,control,updated FROM tasks WHERE id=%s", (task,)
            ).fetchone()
        if not row:
            return now
        if row["control"] == "ai" and row["status"] in (
            "completed",
            "failed",
            "cancelled",
        ):
            return min(now, max(last, row["updated"]))
        if row["status"] == "approval":
            # A real request gives time to switch to chat and fill in details. No
            # preview/approval polling updates this deadline; abandonment still expires.
            last = max(last, row["updated"])
            idle = BROWSER_INPUT_IDLE_SECONDS
        if row["control"] == "ai" and row["status"] in ("queued", "running"):
            last = max(
                last, row["updated"]
            )  # real agent progress, never preview polling
    cutoff = last + idle
    return cutoff if now >= cutoff else None


async def maintain_runtimes():
    names = (
        await cmd("ps", "--filter", "label=aster.sandbox=1", "--format", "{{.Names}}")
    ).splitlines()
    with core.db() as c:
        meters = [r["name"] for r in c.execute("SELECT name FROM runtime_meters")]
    for n in set(urls) | set(meters) | set(stopping):
        if n not in names:
            forget(n)
    for n in names:
        if n in retiring:
            continue
        kind = "browser" if n.startswith("aster-browser-") else "code"
        task = n.removeprefix("aster-" + kind + "-")
        try:
            cutoff = runtime_cutoff(n, time.time())
            if cutoff is not None and (n not in inuse or n in stopping):
                await retire(n, cutoff)
                continue
            billing.start_runtime(n, task, kind)
        except billing.CreditError:
            try:
                await retire(n)
            except Exception:
                stop_meter(n)
                await cmd("rm", "-f", "-v", n)
                forget(n)
            if task_owner(task):
                core.event(
                    task,
                    "credit_paused",
                    {
                        "text": "Workspace stopped because the configured usage limit was reached. Saved checkpoints remain available."
                    },
                )
                with core.db() as c:
                    c.execute(
                        "UPDATE tasks SET status='paused' WHERE id=%s AND status IN ('queued','running')",
                        (task,),
                    )
        except Exception:
            import logging

            logging.exception("Runtime maintenance failed for %s", n)


@app.on_event("startup")
async def startup():
    with core.db() as c:
        previous = [r["name"] for r in c.execute("SELECT name FROM runtime_meters")]
    for n in previous:
        billing.stop_runtime(n)
    # Recover for checkpoint/cleanup only. A broker restart cannot count as user
    # activity or silently restart charging for previously abandoned containers.
    try:
        existing = (
            await cmd(
                "ps", "--filter", "label=aster.sandbox=1", "--format", "{{.Names}}"
            )
        ).splitlines()
        for n in existing:
            kind = "browser" if n.startswith("aster-browser-") else "code"
            try:
                urls[n] = await inspect_url(n, kind)
                stop_meter(n)
            except HTTPException:
                pass
        await maintain_runtimes()
    except HTTPException:
        pass

    async def meter():
        while True:
            await asyncio.sleep(5)
            try:
                await maintain_runtimes()
            except Exception:
                import logging

                logging.exception("Runtime maintenance failed")

    asyncio.create_task(meter())

    async def checkpoint_loop():
        while True:
            await asyncio.sleep(30)
            for n in list(urls):
                if n in inuse or n in retiring or n in stopping:
                    continue
                use(n)
                try:
                    await checkpoint_container(n)
                except Exception:
                    import logging

                    logging.exception("Periodic workspace checkpoint failed for %s", n)
                finally:
                    unuse(n)

    asyncio.create_task(checkpoint_loop())


@app.get("/task/{task}/dev-frame")
async def development_frame(task: str):
    url = existing_endpoint(task, "code")
    async with httpx.AsyncClient(timeout=8, headers=sandbox_headers(task)) as c:
        r = await c.get(url + "/dev-frame")
    return Response(
        r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "image/jpeg"),
        headers={
            "Cache-Control": "no-store",
            **{
                key: r.headers.get(key, "")
                for key in (
                    "X-Aster-Frame-Seq",
                    "X-Aster-Frame-Age",
                    "X-Aster-Frame-URL",
                )
            },
        },
    )


@app.get("/task/{task}/archive")
async def project_archive(task: str):
    n = name(task, "code")
    if n not in urls:
        data = saved_archive(task)
        if data is None:
            raise HTTPException(404, "No saved project yet")
        return Response(data, media_type="application/zip")
    use(n)
    try:
        url = await endpoint(task, kind="code")
        async with httpx.AsyncClient(timeout=60, headers=sandbox_headers(task)) as c:
            r = await c.get(url + "/archive")
        return Response(
            r.content,
            status_code=r.status_code,
            media_type=r.headers.get("content-type", "application/zip"),
        )
    finally:
        unuse(n)


@app.post("/owner/{owner}/forget-browser")
async def forget_browser(owner: str):
    # Close live contexts before deleting the saved state so they cannot write it back.
    with core.db() as c:
        tasks = [
            r["id"] for r in c.execute("SELECT id FROM tasks WHERE owner=%s", (owner,))
        ]
    async with gate:
        for task in tasks:
            n = name(task, "browser")
            if n in inuse:
                raise HTTPException(409, "Wait for current browser actions to finish")
        names = [name(task, "browser") for task in tasks]
        retiring.update(names)
        try:
            for task, n in zip(tasks, names):
                try:
                    await cmd("rm", "-f", n)
                except HTTPException as e:
                    if "No such container" not in str(e.detail):
                        raise
                forget(n)
                session_base.pop(task, None)
            browser_state.clear(owner)
        finally:
            retiring.difference_update(names)
    return {"ok": True}
