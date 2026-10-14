from source_checks import read_source

"""Runtime refresh regressions; no Docker daemon or application database needed."""
from pathlib import Path
import os
import subprocess
import sys
import zipfile
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
from verify_toolchains import run


def test_image_selection_matches_installer_and_preserves_old_image():
    installer = read_source(ROOT / "install.sh")
    broker = read_source(ROOT / "app/broker.py")
    assert "['aster-sandbox:3']" in broker
    commands = [
        line for line in installer.splitlines() if line.startswith("docker run ")
    ]
    assert all(
        ("aster-sandbox:3" in line for line in commands if "aster-sandbox:" in line)
    )
    assert 'docker build --pull --build-arg "ASTER_RUNTIME_REFRESH=' in installer
    assert "required_disk=18000000" in installer
    assert "required_disk=4000000" not in installer
    assert "docker image rm aster-sandbox:2" not in installer
    assert "if ! command -v runsc" not in installer
    assert "apt-get install -y runsc" in installer
    assert '"$runsc_bin" install' in installer
    assert "path=sys.argv[1]" in installer


def test_runtime_gate_runs_before_release_activation():
    installer = read_source(ROOT / "install.sh")
    assert installer.index("/opt/verify_runtime.py") < installer.index(
        'atomic_current "$release"'
    )
    dockerfile = read_source(ROOT / "sandbox/Dockerfile")
    assert (
        "COPY verify_runtime.py verify_toolchains.py verify_browser.py /opt/"
        in dockerfile
    )
    assert "verify(root,runtime_env)" in read_source(ROOT / "sandbox/verify_runtime.py")
    assert "USER 1000:1000" in dockerfile
    assert installer.index("/opt/verify_browser.py") < installer.index(
        'atomic_current "$release"'
    )


def test_toolchain_command_failures_are_not_hidden(tmp_path):
    with pytest.raises(RuntimeError, match="failed.*17"):
        run(
            [sys.executable, "-c", 'print("broken runtime"); raise SystemExit(17)'],
            env=os.environ,
            cwd=tmp_path,
        )
    with pytest.raises(subprocess.TimeoutExpired):
        run(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            env=os.environ,
            cwd=tmp_path,
            timeout=0.05,
        )


def test_python_user_packages_work_with_system_site_venv(tmp_path):
    """Exercise the chosen venv policy with an offline install and import."""
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "PYTHONUSERBASE": str(tmp_path / "user"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    }
    env.pop("PYTHONNOUSERSITE", None)
    venv = tmp_path / "python"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv)],
        check=True,
        env=env,
    )
    wheel = tmp_path / "aster_package_probe-1.0-py3-none-any.whl"
    prefix = "aster_package_probe-1.0.dist-info/"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("aster_package_probe.py", "VALUE = 42\n")
        archive.writestr(
            prefix + "METADATA",
            "Metadata-Version: 2.1\nName: aster-package-probe\nVersion: 1.0\n",
        )
        archive.writestr(
            prefix + "WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(prefix + "RECORD", "")
    python = str(venv / "bin/python")
    subprocess.run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--user",
            str(wheel),
        ],
        env=env,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            python,
            "-c",
            "import aster_package_probe; assert aster_package_probe.VALUE == 42",
        ],
        env=env,
        check=True,
    )
