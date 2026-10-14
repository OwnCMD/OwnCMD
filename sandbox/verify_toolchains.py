"""Offline acceptance checks, executed as agent in the actual restricted image."""

import json
import os
from pathlib import Path
import platform
import pwd
import subprocess
import sys
import time
import zipfile


def run(argv, *, env, cwd, timeout=90):
    result = subprocess.run(
        argv,
        env=env,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(
            f"{argv[0]} failed ({result.returncode}): {result.stdout[-4000:]}"
        )
    return result.stdout.strip()


def verify(root, env):
    root = Path(root) / "toolchains"
    root.mkdir()
    env = {**env, "HOME": str(root), "GOTOOLCHAIN": "local", "GOTELEMETRY": "off"}
    release = platform.freedesktop_os_release()
    assert release["ID"] == "ubuntu" and release["VERSION_ID"] == "26.04", release
    assert sys.version_info[:2] == (3, 14), sys.version
    versions = {
        "os": release["PRETTY_NAME"],
        "python": sys.version.split()[0],
        "sandbox_kernel_compatibility": platform.release(),
    }
    for name, command, expected in [
        ("node", ["node", "--version"], "v24."),
        ("go", ["go", "version"], "go1.27."),
        ("rust", ["rustc", "--version"], "rustc 1.98."),
        ("postgresql", ["initdb", "--version"], "18."),
        ("java", ["javac", "-version"], "javac 25"),
        ("mongodb", ["mongod", "--version"], "v8.0."),
    ]:
        versions[name] = run(command, env=env, cwd=root)
        assert expected in versions[name], (name, versions[name])
    print("RUNTIME_VERSIONS " + json.dumps(versions), flush=True)
    run(["python", "-m", "pip", "check"], env=env, cwd=root)
    # Verify native Python extensions, document libraries and browser bindings load.
    run(
        [
            "python",
            "-c",
            "import numpy,pandas,matplotlib,lxml.etree,PIL.Image,cryptography,greenlet,pydantic_core; import docx,pptx,openpyxl,reportlab,playwright.async_api",
        ],
        env=env,
        cwd=root,
    )
    # Install a tiny offline wheel to HOME, as real non-root user package installs do.
    wheel = root / "aster_runtime_probe-1.0-py3-none-any.whl"
    prefix = "aster_runtime_probe-1.0.dist-info/"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("aster_runtime_probe.py", "VALUE = 42\n")
        archive.writestr(
            prefix + "METADATA",
            "Metadata-Version: 2.1\nName: aster-runtime-probe\nVersion: 1.0\n",
        )
        archive.writestr(
            prefix + "WHEEL",
            "Wheel-Version: 1.0\nGenerator: aster\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(prefix + "RECORD", "")
    run(
        [
            "python",
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--user",
            str(wheel),
        ],
        env=env,
        cwd=root,
    )
    run(
        [
            "python",
            "-c",
            "import aster_runtime_probe; assert aster_runtime_probe.VALUE == 42",
        ],
        env=env,
        cwd=root,
    )
    run(["python", "-m", "venv", str(root / "project-venv")], env=env, cwd=root)
    run(
        [str(root / "project-venv/bin/python"), "-c", "assert 6*7 == 42"],
        env=env,
        cwd=root,
    )
    (root / "hello.go").write_text(
        'package main\nimport "fmt"\nfunc main(){fmt.Print("GO_OK")}\n'
    )
    assert run(["go", "run", "hello.go"], env=env, cwd=root, timeout=120) == "GO_OK"
    (root / "hello.rs").write_text('fn main(){print!("RUST_OK");}\n')
    run(["rustc", "hello.rs", "-o", "rust-probe"], env=env, cwd=root)
    assert run([str(root / "rust-probe")], env=env, cwd=root) == "RUST_OK"
    (root / "Hello.java").write_text(
        'class Hello { public static void main(String[] args) { System.out.print("JAVA_OK"); } }\n'
    )
    run(["javac", "Hello.java"], env=env, cwd=root)
    assert "JAVA_OK" in run(
        ["java", "-Xmx128m", "-cp", str(root), "Hello"], env=env, cwd=root
    )
    verify_postgres(root, env)
    verify_redis(root, env)
    print("PYTHON_PACKAGES_VENV_GO_RUST_JAVA_POSTGRES_REDIS_OK", flush=True)


def verify_postgres(root, env):
    data = root / "pgdata"
    sockets = root / "pgsocket"
    sockets.mkdir()
    user = pwd.getpwuid(os.getuid()).pw_name
    run(
        [
            "initdb",
            "-D",
            str(data),
            "--no-sync",
            "--auth-local=trust",
            "--auth-host=reject",
            "--no-locale",
            "-E",
            "UTF8",
        ],
        env=env,
        cwd=root,
    )
    # Only a private Unix socket: this must never connect to a host database.
    run(
        [
            "pg_ctl",
            "-D",
            str(data),
            "-l",
            str(root / "postgres.log"),
            "-o",
            f"-k {sockets} -c listen_addresses='' -c fsync=off",
            "-w",
            "start",
        ],
        env=env,
        cwd=root,
    )
    try:
        connection = ["-h", str(sockets), "-U", user, "--no-password"]
        psql = ["psql", "-X", "-v", "ON_ERROR_STOP=1", *connection]
        run(
            [
                *psql,
                "-d",
                "postgres",
                "-c",
                "CREATE TABLE probe(value text); INSERT INTO probe VALUES ('POSTGRES_OK');",
            ],
            env=env,
            cwd=root,
        )
        dump = root / "postgres.dump"
        run(
            ["pg_dump", *connection, "-d", "postgres", "-Fc", "-f", str(dump)],
            env=env,
            cwd=root,
        )
        run(["createdb", *connection, "restore_probe"], env=env, cwd=root)
        run(
            [
                "pg_restore",
                *connection,
                "--exit-on-error",
                "-d",
                "restore_probe",
                str(dump),
            ],
            env=env,
            cwd=root,
        )
        assert (
            run(
                [*psql, "-d", "restore_probe", "-Atc", "SELECT value FROM probe"],
                env=env,
                cwd=root,
            )
            == "POSTGRES_OK"
        )
    finally:
        run(
            ["pg_ctl", "-D", str(data), "-m", "immediate", "-w", "stop"],
            env=env,
            cwd=root,
        )


def verify_redis(root, env):
    sock = root / "redis.sock"
    with (root / "redis.log").open("w") as log:
        proc = subprocess.Popen(
            [
                "redis-server",
                "--port",
                "0",
                "--unixsocket",
                str(sock),
                "--dir",
                str(root),
                "--save",
                "",
                "--appendonly",
                "no",
            ],
            env=env,
            cwd=root,
            stdout=log,
            stderr=log,
        )
        try:
            for _ in range(100):
                if sock.exists():
                    break
                if proc.poll() is not None:
                    raise RuntimeError((root / "redis.log").read_text())
                time.sleep(0.05)
            cli = ["redis-cli", "-s", str(sock), "--raw"]
            assert run([*cli, "SET", "probe", "REDIS_OK"], env=env, cwd=root) == "OK"
            assert run([*cli, "GET", "probe"], env=env, cwd=root) == "REDIS_OK"
            run([*cli, "SAVE"], env=env, cwd=root)
            assert (root / "dump.rdb").stat().st_size > 0
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
