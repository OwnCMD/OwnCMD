"""Exercise OpenPGP verification and restricted-user file access independently."""

import os
import base64
import hashlib
import pathlib
import pwd
import subprocess
import tempfile
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/gvisor_repository.sh"


@pytest.fixture(scope="module")
def signing_key():
    # Generate a small RFC 4880 test fixture without a gpg-agent socket, which
    # restricted CI hosts may prohibit. GnuPG independently verifies it below.
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_numbers()
    timestamp = int(time.time()).to_bytes(4, "big")

    def mpi(number):
        bits = number.bit_length()
        return bits.to_bytes(2, "big") + number.to_bytes((bits + 7) // 8, "big")

    def packet(tag, body):
        return bytes([0xC0 | tag, 255]) + len(body).to_bytes(4, "big") + body

    public_body = b"\x04" + timestamp + b"\x01" + mpi(public.n) + mpi(public.e)
    public_prefix = b"\x99" + len(public_body).to_bytes(2, "big") + public_body
    fingerprint = hashlib.sha1(public_prefix).digest()

    def sign(data, kind=0):
        hashed = b"\x05\x02" + timestamp
        header = bytes([4, kind, 1, 8]) + len(hashed).to_bytes(2, "big") + hashed
        signed = data + header + b"\x04\xff" + len(header).to_bytes(4, "big")
        digest = hashlib.sha256(signed).digest()
        issuer = b"\x09\x10" + fingerprint[-8:]
        signature = private.sign(signed, padding.PKCS1v15(), hashes.SHA256())
        return packet(
            2,
            header
            + len(issuer).to_bytes(2, "big")
            + issuer
            + digest[:2]
            + mpi(int.from_bytes(signature, "big")),
        )

    uid = b"OwnCMD repository test <test@example.invalid>"
    binary = (
        packet(6, public_body)
        + packet(13, uid)
        + sign(public_prefix + b"\xb4" + len(uid).to_bytes(4, "big") + uid, 0x13)
    )
    encoded = base64.b64encode(binary)
    crc = 0xB704CE
    for byte in binary:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    armor = (
        b"-----BEGIN PGP PUBLIC KEY BLOCK-----\n\n"
        + b"\n".join(encoded[i : i + 64] for i in range(0, len(encoded), 64))
        + b"\n="
        + base64.b64encode(crc.to_bytes(3, "big"))
        + b"\n-----END PGP PUBLIC KEY BLOCK-----\n"
    )
    return sign, armor


def prepare_host_root(root):
    # Model the already-existing public system parents on a real Ubuntu host.
    # Do not rely on install -d assigning a mode to implicit parent components:
    # with a restrictive umask those can be 0700 on the target coreutils build.
    for relative in ("", "usr", "usr/share", "etc", "etc/apt"):
        directory = root / relative
        directory.mkdir(exist_ok=True)
        directory.chmod(0o755)


@pytest.fixture
def host(signing_key):
    # A public parent lets the real _apt uid reach the test keyring.
    with tempfile.TemporaryDirectory(prefix="aster-gvisor-test-") as directory:
        root = pathlib.Path(directory)
        prepare_host_root(root)
        tools = root / "tools"
        tools.mkdir(mode=0o755)
        (root / "download.asc").write_bytes(signing_key[1])
        curl = tools / "curl"
        curl.write_text("""#!/usr/bin/env python3
import os, pathlib, shutil, sys
assert 'https://gvisor.dev/archive.key' in sys.argv
assert '--proto' in sys.argv and '--proto-redir' in sys.argv
if os.getenv('FAIL_DOWNLOAD'): sys.exit(22)
shutil.copyfile(os.environ['TEST_ARCHIVE'], sys.argv[sys.argv.index('-o') + 1])
""")
        curl.chmod(0o755)
        env = {
            **os.environ,
            "PATH": str(tools) + os.pathsep + os.environ["PATH"],
            "TEST_ARCHIVE": str(root / "download.asc"),
        }
        yield root, env


def run(host, function="configure_gvisor_repository"):
    root, env = host
    return subprocess.run(
        [
            "bash",
            "-c",
            'set -euo pipefail; umask 077; source "$1"; '
            + function
            + ' "$2"; test "$(umask)" = 0077',
            "test",
            str(HELPER),
            str(root),
        ],
        env=env,
        capture_output=True,
        text=True,
    )


def paths(root):
    return (
        root / "usr/share/keyrings/gvisor-archive-keyring.gpg",
        root / "etc/apt/sources.list.d/gvisor.list",
    )


def test_fake_host_repairs_private_system_parents(host):
    root, _ = host
    parents = [root / name for name in ("usr", "usr/share", "etc", "etc/apt")]
    for parent in parents:
        parent.chmod(0o700)
        assert parent.stat().st_mode & 0o005 == 0
    private = root / "private-fixture"
    private.mkdir(mode=0o700)
    prepare_host_root(root)
    for parent in parents:
        assert parent.stat().st_mode & 0o777 == 0o755
    assert private.stat().st_mode & 0o777 == 0o700
    result = run(host)
    assert result.returncode == 0, result.stderr
    key, source = paths(root)
    assert key.stat().st_mode & 0o777 == source.stat().st_mode & 0o777 == 0o644


def test_public_key_and_source_readable_despite_private_umask(host):
    result = run(host)
    assert result.returncode == 0, result.stderr
    key, source = paths(host[0])
    assert key.stat().st_mode & 0o777 == source.stat().st_mode & 0o777 == 0o644
    assert not key.read_bytes().startswith(b"-----BEGIN")
    assert (
        "signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg" in source.read_text()
    )
    assert "trusted=yes" not in source.read_text()
    assert not list(key.parent.glob(".aster-gvisor.*"))
    assert not list(source.parent.glob(".aster-gvisor.*"))


@pytest.mark.parametrize("contents", [b"broken partial key", b""])
def test_existing_failed_install_repaired_before_apt(host, contents):
    key, source = paths(host[0])
    key.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    key.write_bytes(contents)
    source.write_text("previous repository")
    key.chmod(0o600)
    source.chmod(0o600)
    result = run(host, "repair_existing_gvisor_repository")
    assert result.returncode == 0, result.stderr
    assert key.stat().st_mode & 0o777 == source.stat().st_mode & 0o777 == 0o644
    assert key.read_bytes() != contents
    installer = (ROOT / "install.sh").read_text()
    assert installer.index("repair_existing_gvisor_repository\n") < installer.index(
        "\napt-get update"
    )


@pytest.mark.parametrize("failure", ["download", "format"])
def test_failed_refresh_preserves_previous_files(host, failure):
    assert run(host).returncode == 0
    key, source = paths(host[0])
    before = key.read_bytes(), source.read_bytes()
    if failure == "download":
        host[1]["FAIL_DOWNLOAD"] = "1"
    else:
        (host[0] / "download.asc").write_text("<html>upstream error</html>")
    assert run(host).returncode != 0
    assert (key.read_bytes(), source.read_bytes()) == before
    assert not list(key.parent.glob(".aster-gvisor.*"))


def test_fresh_host_repair_does_not_require_download(host):
    host[1]["FAIL_DOWNLOAD"] = "1"
    result = run(host, "repair_existing_gvisor_repository")
    assert result.returncode == 0, result.stderr
    assert not paths(host[0])[0].exists()


@pytest.mark.parametrize("as_apt", [False, True])
def test_key_access_and_signature_verification(host, signing_key, as_apt):
    assert run(host).returncode == 0
    root, _ = host
    key, _ = paths(root)
    release = root / "Release"
    release.write_text("Origin: OwnCMD local verification fixture\n")
    release.chmod(0o644)
    signature = root / "Release.gpg"
    signature.write_bytes(signing_key[0](release.read_bytes()))
    signature.chmod(0o644)
    if as_apt and os.geteuid() != 0:
        pytest.skip("Restricted _apt uid verification requires root")
    apt = pwd.getpwnam("_apt") if as_apt else None

    def read_key():
        # Test the OS read permission directly. Running gpgv with a root-owned
        # synthetic GNUPGHOME as _apt also tests unrelated GnuPG host behavior.
        identity = (
            dict(user=apt.pw_uid, group=apt.pw_gid, extra_groups=[]) if as_apt else {}
        )
        try:
            return subprocess.run(
                ["/bin/cat", str(key)], cwd=root, **identity, capture_output=True
            )
        except PermissionError:
            if as_apt:
                pytest.skip("This host does not allow switching to the _apt uid")
            raise

    def verify():
        return subprocess.run(
            [
                "gpgv",
                "--homedir",
                str(root),
                "--keyring",
                str(key),
                str(signature),
                str(release),
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

    if as_apt:
        key.chmod(0o600)
        assert read_key().returncode != 0  # Reproduce the original permission failure.
    assert run(host, "repair_existing_gvisor_repository").returncode == 0
    assert key.is_file() and key.stat().st_mode & 0o777 == 0o644
    for parent in (root, root / "usr", root / "usr/share", key.parent):
        assert parent.stat().st_mode & 0o005 == 0o005, str(parent)
    readable = read_key()
    assert readable.returncode == 0, readable.stderr.decode(errors="replace")
    assert readable.stdout == key.read_bytes()
    result = verify()
    assert result.returncode == 0, result.stderr
    release.write_text("tampered metadata\n")
    assert verify().returncode != 0
