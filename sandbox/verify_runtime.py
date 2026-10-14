"""Executed inside the production gVisor image by the installer, with no network."""

import os, tempfile, subprocess, time, signal, urllib.request, json, shutil
from pathlib import Path

root = Path("/work/runtime-check")
root.mkdir(parents=True, exist_ok=True)
for directory in ("/work", "/tmp"):
    if os.statvfs(directory).f_flag & os.ST_NOEXEC:
        raise SystemExit(
            f"{directory} is mounted noexec. The code sandbox requires an explicit exec tmpfs option; changing file permissions cannot fix a noexec mount."
        )
# Exercise the same non-login shell and project environment used by commands/services.
from server import process_env

runtime_env = {**process_env(), "HOME": str(root)}
from verify_toolchains import verify

verify(root, runtime_env)
subprocess.run(
    [
        "/bin/bash",
        "-c",
        "go version && rustc --version && cargo --version && initdb --version && pg_ctl --version",
    ],
    env=runtime_env,
    cwd=root,
    timeout=30,
    check=True,
)
checks = [
    (["python", "-c", "print(2+2)"], "4"),
    (["node", "-e", "console.log(2+2)"], "4"),
    (["php", "-r", "echo 2+2;"], "4"),
    (["ruby", "-e", "puts 2+2"], "4"),
]
for cmd, expected in checks:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
    assert expected in r.stdout, cmd
(root / "hello.c").write_text('#include <stdio.h>\nint main(){puts("C_OK");return 0;}')
subprocess.run(["gcc", str(root / "hello.c"), "-o", str(root / "hello")], check=True)
assert "C_OK" in subprocess.check_output([str(root / "hello")], text=True)
(root / "hello.cpp").write_text('#include <iostream>\nint main(){std::cout<<"CPP_OK";}')
subprocess.run(["g++", str(root / "hello.cpp"), "-o", str(root / "cpp")], check=True)
assert "CPP_OK" in subprocess.check_output([str(root / "cpp")], text=True)
# Go tests and native package build tools also execute temporary binaries.
with tempfile.TemporaryDirectory(prefix="aster-native-check-", dir="/tmp") as temporary:
    for source, expected in [("hello", "C_OK"), ("cpp", "CPP_OK")]:
        executable = Path(temporary) / source
        shutil.copy2(root / source, executable)
        assert expected in subprocess.check_output([str(executable)], text=True)
print("C_CPP_WORK_AND_TMP_EXEC_OK", flush=True)
# Verify the reported PHP workflow through the actual service + preview handlers.
import asyncio, socket, httpx, server as runtime_server


async def verify_php_preview():
    directory = root / "php-preview"
    directory.mkdir()
    (directory / "index.php").write_text(
        '<?php echo "<h1>PHP_PREVIEW_".(6*7)."</h1>"; ?>'
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_server.app), base_url="http://sandbox"
    ) as client:
        try:
            response = await client.post(
                "/terminal", json={"op": "open", "cols": 80, "rows": 24}
            )
            assert response.status_code == 200, response.text
            response = await client.post(
                "/terminal", json={"op": "input", "data": "printf 'PTY_%s\\n' READY\r"}
            )
            assert response.status_code == 200, response.text
            for _ in range(40):
                response = await client.post(
                    "/terminal", json={"op": "read", "cursor": 0}
                )
                if "PTY_READY" in response.json().get("output", ""):
                    break
                await asyncio.sleep(0.05)
            else:
                raise RuntimeError("Interactive terminal did not produce output")
            await client.post("/terminal", json={"op": "close"})
            print("INTERACTIVE_PTY_OK", flush=True)
            response = await client.post(
                "/services",
                json={
                    "op": "start",
                    "name": "php-preview",
                    "port": port,
                    "command": f"php -S 127.0.0.1:{port} -t {directory}",
                },
            )
            assert response.status_code == 200, response.text
            response = await client.post(
                "/dev-action", json={"kind": "open", "args": {"port": port}}
            )
            assert response.status_code == 200, response.text
            assert (
                "PHP_PREVIEW_42"
                in await runtime_server.page.locator("body").inner_text()
            )
            response = await client.get("/dev-frame")
            assert response.status_code == 200 and response.content[:2] == b"\xff\xd8"
            print("PHP_PRIVATE_BROWSER_PREVIEW_OK", flush=True)
        finally:
            await client.post("/services", json={"op": "stop_all"})
            if runtime_server.browser:
                await runtime_server.browser.close()
            if runtime_server.playwright:
                await runtime_server.playwright.stop()


asyncio.run(verify_php_preview())
project = root / "project"
shutil.copytree("/opt/templates/mern", project)
env = {**os.environ, "HOME": str(root)}
log = (root / "service.log").open("wb")
p = subprocess.Popen(
    ["npm", "run", "dev"],
    cwd=project,
    env=env,
    stdout=log,
    stderr=log,
    start_new_session=True,
)
try:
    for _ in range(150):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:3001/api/health", timeout=1
            ) as r:
                if json.load(r)["ok"]:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:3000", timeout=1
                    ) as page:
                        if b"client/main.jsx" in page.read():
                            break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError(
            "MERN startup failed: " + (root / "service.log").read_text()[-2000:]
        )
    request = urllib.request.Request(
        "http://127.0.0.1:3001/api/notes",
        data=b'{"text":"Runtime verified"}',
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=3) as r:
        assert r.status == 201
    with urllib.request.urlopen("http://127.0.0.1:3001/api/notes", timeout=3) as r:
        assert any(n["text"] == "Runtime verified" for n in json.load(r))
    with urllib.request.urlopen("http://127.0.0.1:3000", timeout=3) as r:
        assert b"client/main.jsx" in r.read()
    subprocess.run(
        [
            "mongodump",
            "--host",
            "127.0.0.1",
            "--archive=" + str(root / "db.archive"),
            "--gzip",
        ],
        check=True,
        timeout=30,
        stdout=subprocess.DEVNULL,
    )
    assert (root / "db.archive").stat().st_size > 0
    # Restore into a separate database and read via the same MongoDB driver.
    subprocess.run(
        [
            "mongorestore",
            "--host",
            "127.0.0.1",
            "--archive=" + str(root / "db.archive"),
            "--gzip",
            "--nsFrom=project.*",
            "--nsTo=runtime_restore.*",
        ],
        check=True,
        timeout=30,
    )
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            "import {MongoClient} from 'mongodb'; const c=new MongoClient('mongodb://127.0.0.1:27017'); await c.connect(); try { if(!await c.db('runtime_restore').collection('notes').findOne({text:'Runtime verified'})) throw Error('MongoDB restore lost data'); } finally { await c.close(); }",
        ],
        cwd=project,
        env=env,
        check=True,
        timeout=30,
    )
    print("LANGUAGES_MERN_DATABASE_EXPORT_OK")
finally:
    os.killpg(p.pid, signal.SIGTERM)
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
