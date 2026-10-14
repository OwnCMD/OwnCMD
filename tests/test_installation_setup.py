"""TLS setup and destructive reset regressions; host mutations are never executed."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import configure_site as site
import reset_installation as reset


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("", "letsencrypt"),
        ("yes", "letsencrypt"),
        ("Y", "letsencrypt"),
        ("no", "internal"),
        ("n", "internal"),
    ],
)
def test_certificate_choice(answer, expected):
    assert site.choose_tls("aster.example.com", lambda _: answer) == expected


def test_invalid_choice_reprompts_and_ip_skips_prompt():
    answers = iter(["invalid", "no"])
    assert site.choose_tls("aster.example.com", lambda _: next(answers)) == "internal"
    assert (
        site.choose_tls(
            "203.0.113.5", lambda _: pytest.fail("IP should not prompt for LE")
        )
        == "internal"
    )


@pytest.mark.parametrize(
    "host",
    [
        "https://example.com",
        "example.com/path",
        "bad:443",
        "*.example.com",
        "foo\n{",
        "a..com",
        "-bad.com",
        "999.1.2.3",
        "host.local",
    ],
)
def test_reject_unsafe_hosts(host):
    with pytest.raises(ValueError):
        site.normalize_host(host)


def test_setup_persists_choice_and_generates_unique_secrets(tmp_path):
    paths = [tmp_path / name for name in ("one.env", "two.env")]
    for path in paths:
        answers = iter(["OwnCMD.Example.COM.", "yes", "yes"])
        site.setup(path, lambda _: next(answers), lambda _: "test-api-key")
        assert path.stat().st_mode & 0o777 == 0o600
    first, second = map(site.read_config, paths)
    assert first["ASTER_ORIGIN"] == "https://owncmd.example.com"
    assert first["ASTER_TLS_MODE"] == "letsencrypt"
    assert first["ASTER_CHAT_MODEL"] == "google/gemini-3.5-flash-lite"
    assert first["ASTER_WORK_MODEL"] == "openai/gpt-5.6-luna"
    assert "ASTER_INVITE_CODE" not in first
    for key in ("ASTER_MASTER_KEY", "ASTER_BROKER_KEY"):
        assert first[key] != second[key]
    before = paths[0].read_bytes()
    site.setup(
        paths[0],
        lambda _: pytest.fail("Upgrade must not prompt"),
        lambda _: pytest.fail("Upgrade must not replace keys"),
    )
    assert paths[0].read_bytes() == before


def test_caddy_modes_and_legacy_defaults():
    values = {"ASTER_ORIGIN": "https://aster.example.com"}
    public = site.render_caddy(values)
    assert "issuer acme" in public and site.LE_DIRECTORY in public
    assert "tls internal" not in public
    assert "max_size 26MB" in public and "reverse_proxy 127.0.0.1:8000" in public
    private = site.render_caddy(values | {"ASTER_TLS_MODE": "internal"})
    assert "tls internal" in private and "issuer acme" not in private
    assert "tls internal" in site.render_caddy({"ASTER_ORIGIN": "https://203.0.113.5"})
    with pytest.raises(ValueError):
        site.render_caddy(values | {"ASTER_TLS_MODE": "http"})


def test_caddy_validation_failure_preserves_previous_config(tmp_path, monkeypatch):
    path = tmp_path / "Caddyfile"
    path.write_text("old configuration")
    monkeypatch.setattr(site, "CADDYFILE", path)
    monkeypatch.setattr(site.shutil, "chown", lambda *args, **kwargs: None)

    def command(args, **kwargs):
        if "validate" in args:
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(site.subprocess, "run", command)
    with pytest.raises(subprocess.CalledProcessError):
        site.configure({"ASTER_ORIGIN": "https://aster.example.com"})
    assert path.read_text() == "old configuration"
    assert not path.with_name("Caddyfile.aster-new").exists()


def test_tls_failure_never_reports_success_and_retry_is_bounded(capsys):
    now = [0]

    def probe(*args):
        raise OSError("not ready")

    with pytest.raises(RuntimeError, match="HTTPS verification failed"):
        site.verify(
            {"ASTER_ORIGIN": "https://aster.example.com"},
            timeout=10,
            probe=probe,
            clock=lambda: now[0],
            wait=lambda n: now.__setitem__(0, now[0] + n),
        )
    assert now[0] == 10
    assert "readiness verified" not in capsys.readouterr().out


class Host:
    def __init__(self):
        self.calls = []
        self.pgstate = {
            "database_owner": "aster_app",
            "role_exists": True,
            "privileged": False,
            "other_dependencies": False,
        }
        self.fail_drop = False

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == "runuser":
            assert "--no-password" in args
            statement = args[-1]
            if statement == reset.PG_SQL:
                return json.dumps(self.pgstate)
            if self.fail_drop and statement.startswith("DROP DATABASE"):
                raise subprocess.CalledProcessError(1, args)
            return ""
        if args[:2] == ["systemctl", "list-unit-files"]:
            return "aster-api.service enabled\naster-broker.service enabled\naster-worker@.service indirect\naster-worker@2.service enabled\nssh.service enabled"
        if args[:2] == ["systemctl", "list-units"]:
            return "aster-worker@3.service loaded active running worker\nssh.service loaded active running ssh"
        if args[:2] == ["docker", "ps"]:
            return ""
        if args[:3] == ["docker", "network", "ls"]:
            return "bridge\nhost\naster-code\naster-sandbox"
        if args[:3] == ["docker", "network", "inspect"]:
            return '[{"Containers":{}}]'
        if args[:3] == ["docker", "image", "ls"]:
            return "aster-sandbox:2"
        return ""


@pytest.fixture
def installed(tmp_path):
    config = tmp_path / "etc/aster/config.env"
    config.parent.mkdir(parents=True)
    values = {
        "ASTER_DATA": "/var/lib/aster",
        "ASTER_ORIGIN": "https://aster.example.com",
        "ASTER_TLS_MODE": "letsencrypt",
        "ASTER_DATABASE_URL": "postgresql://aster_app:secret@127.0.0.1:5432/aster",
    }
    config.write_text("".join(k + "=" + v + "\n" for k, v in values.items()))
    (config.parent / "installed").touch()
    for folder in (
        "var/lib/aster/backups",
        "opt/aster/releases/old",
        "etc/caddy",
        "etc/systemd/system",
        "var/lib/unrelated",
    ):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / "var/lib/aster/backups/old.db").write_text("old data")
    (tmp_path / "var/lib/unrelated/keep").write_text("unrelated")
    (tmp_path / "etc/caddy/Caddyfile").write_text(site.render_caddy(values))
    (tmp_path / "etc/systemd/system/aster-api.service").write_text("old unit")
    return tmp_path, config, Host()


def make_reset(installed):
    root, _, host = installed
    return reset.Reset(
        root, host, lambda name: "/bin/" + name if name != "iptables" else None
    )


def test_reset_dry_run_is_read_only_and_excludes_secrets(installed, capsys):
    root, config, host = installed
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    plan = make_reset(installed).preflight()
    plan.describe()
    assert {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    assert all(
        "DROP " not in " ".join(call)
        and not any(x in call for x in ("disable", "rm", "stop"))
        for call in host.calls
    )
    assert ":secret@" not in capsys.readouterr().out


def test_reset_stops_all_workers_removes_app_data_and_preserves_other_data(installed):
    root, config, host = installed
    plan = make_reset(installed).preflight()
    plan.apply()
    assert not config.exists()
    assert not (root / "var/lib/aster").exists()
    assert not (root / "opt/aster").exists()
    assert not (root / "etc/caddy/Caddyfile").exists()
    assert (root / "var/lib/unrelated/keep").read_text() == "unrelated"
    stop = next(
        i
        for i, c in enumerate(host.calls)
        if c[:3] == ["systemctl", "disable", "--now"]
    )
    drop = next(
        i for i, c in enumerate(host.calls) if c[-1].startswith("DROP DATABASE")
    )
    assert stop < drop
    assert {"aster-worker@2.service", "aster-worker@3.service"}.issubset(
        host.calls[stop]
    )
    assert "ssh.service" not in host.calls[stop]
    assert ["docker", "image", "rm", "aster-sandbox:2"] in host.calls
    assert not any("prune" in c or "--volumes" in c for c in host.calls)


@pytest.mark.parametrize(
    "replacement",
    [
        "postgresql://aster_app:secret@db.example.com/aster",
        "postgresql://admin:secret@127.0.0.1/aster",
        "postgresql://aster_app:secret@localhost/other",
        "postgresql://aster_app:secret@localhost/aster?host=db.example.com",
    ],
)
def test_reset_refuses_custom_databases_before_any_mutation(installed, replacement):
    _, config, host = installed
    config.write_text(
        config.read_text().replace(
            "postgresql://aster_app:secret@127.0.0.1:5432/aster", replacement
        )
    )
    with pytest.raises(ValueError, match="remote or custom"):
        make_reset(installed).preflight()
    assert not host.calls and config.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("database_owner", "postgres"),
        ("privileged", True),
        ("other_dependencies", True),
    ],
)
def test_reset_refuses_shared_role_or_database(installed, field, value):
    _, config, host = installed
    host.pgstate[field] = value
    with pytest.raises(ValueError, match="shared or"):
        make_reset(installed).preflight()
    assert config.exists()
    assert not any("disable" in c or c[-1].startswith("DROP ") for c in host.calls)


def test_reset_refuses_shared_caddy_and_symlinked_data(installed):
    root, config, _ = installed
    caddyfile = root / "etc/caddy/Caddyfile"
    original = caddyfile.read_text()
    caddyfile.write_text(original + '\nother.example.com { respond "shared" }')
    with pytest.raises(ValueError, match="customized"):
        make_reset(installed).preflight()
    caddyfile.write_text(original)
    import shutil

    shutil.rmtree(root / "var/lib/aster")
    (root / "var/lib/aster").symlink_to(
        root / "var/lib/unrelated", target_is_directory=True
    )
    with pytest.raises(ValueError, match="symlink"):
        make_reset(installed).preflight()
    assert (root / "var/lib/unrelated/keep").exists()


def test_reset_keeps_keys_and_data_if_database_drop_fails(installed):
    root, config, host = installed
    host.fail_drop = True
    with pytest.raises(subprocess.CalledProcessError):
        make_reset(installed).preflight().apply()
    assert config.exists() and (root / "var/lib/aster/backups/old.db").exists()
    assert not any(c[-1].startswith("DROP ROLE") for c in host.calls)


def test_reset_postgresql_catalog_query_is_valid():
    from app import core

    with core.db() as connection:
        state = connection.execute(reset.PG_SQL).fetchone()[0]
    assert set(state) == {
        "database_owner",
        "role_exists",
        "privileged",
        "other_dependencies",
    }


def test_https_probe_checks_real_certificate_hostname_health_and_redirect(
    tmp_path, monkeypatch
):
    import datetime
    import http.server
    import ssl
    import threading
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

    # Python 3.13+ enables these flags by default. Exercise the same validation
    # on older CI interpreters so incomplete test certificates cannot slip through.
    original_context = ssl.create_default_context

    def strict_context(*args, **kwargs):
        context = original_context(*args, **kwargs)
        context.verify_flags |= ssl.VERIFY_X509_STRICT | ssl.VERIFY_X509_PARTIAL_CHAIN
        return context

    monkeypatch.setattr(site.ssl, "create_default_context", strict_context)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OwnCMD test CA")])
    now = datetime.datetime.now(datetime.timezone.utc)
    ca = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "aster.example.com")])
        )
        .issuer_name(name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("aster.example.com")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path = tmp_path / "leaf.pem"
    cert_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_path = tmp_path / "leaf.key"
    key_path.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setattr(site, "LOCAL_CA", ca_path)
    state = {"redirect": True, "health": True}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.server.is_tls:
                body = json.dumps({"ok": state["health"]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(308 if state["redirect"] else 200)
                self.send_header("Location", "https://aster.example.com/health")
                self.end_headers()

        def log_message(self, *args):
            pass

    servers = []
    for tls in (False, True):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.is_tls = tls
        if tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_path, key_path)
            server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(
            target=lambda s=server: s.serve_forever(poll_interval=0.05), daemon=True
        )
        thread.start()
        servers.append((server, thread))
    original = site.socket.create_connection
    ports = {80: servers[0][0].server_port, 443: servers[1][0].server_port}
    monkeypatch.setattr(
        site.socket,
        "create_connection",
        lambda address, *a, **k: original(
            (address[0], ports.get(address[1], address[1])), *a, **k
        ),
    )
    try:
        site.probe_https("aster.example.com", "internal")
        with pytest.raises(ssl.SSLCertVerificationError):
            site.probe_https("wrong.example.com", "internal")
        with pytest.raises(ssl.SSLCertVerificationError):
            site.probe_https("aster.example.com", "letsencrypt")
        state["health"] = False
        with pytest.raises(ValueError, match="readiness"):
            site.probe_https("aster.example.com", "internal")
        state["health"] = True
        state["redirect"] = False
        with pytest.raises(ValueError, match="redirect"):
            site.probe_https("aster.example.com", "internal")
    finally:
        for server, thread in servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)


def test_reset_on_net_new_server_has_nothing_to_erase(tmp_path):
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        return ""

    plan = reset.Reset(tmp_path, command, lambda _: None).preflight()
    plan.apply()
    assert not any(c[0] == "docker" or c[0] == "runuser" or "stop" in c for c in calls)


def test_reset_refuses_unrelated_container_on_app_network(installed):
    _, config, host = installed

    def command(args, **kwargs):
        if args[:3] == ["docker", "network", "inspect"]:
            return '[{"Containers":{"foreign":{"Name":"other-app"}}}]'
        return host(args, **kwargs)

    with pytest.raises(ValueError, match="unrelated container"):
        reset.Reset(installed[0], command, lambda name: "/bin/" + name).preflight()
    assert config.exists()
    assert not any("disable" in c or c[-1].startswith("DROP ") for c in host.calls)


def test_reset_preserves_external_files_referenced_inside_data(installed):
    root, _, _ = installed
    (root / "var/lib/aster/link").symlink_to(
        root / "var/lib/unrelated", target_is_directory=True
    )
    make_reset(installed).preflight().apply()
    assert (root / "var/lib/unrelated/keep").read_text() == "unrelated"


@pytest.mark.parametrize("mode", ["letsencrypt", "internal"])
def test_native_caddy_accepts_exact_generated_configuration(tmp_path, mode):
    import os, shutil

    binary = os.environ.get("ASTER_CADDY_BIN") or shutil.which("caddy")
    if not binary:
        pytest.skip(
            "Native Caddy unavailable; installer runs this after installing Caddy"
        )
    path = tmp_path / "Caddyfile"
    path.write_text(
        site.render_caddy(
            {"ASTER_ORIGIN": "https://aster.example.com", "ASTER_TLS_MODE": mode}
        )
    )
    result = subprocess.run(
        [binary, "adapt", "--adapter", "caddyfile", "--config", str(path)],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=20,
    )
    config = json.loads(result.stdout)
    issuers = config["apps"]["tls"]["automation"]["policies"][0]["issuers"]
    assert issuers == (
        [{"module": "acme", "ca": site.LE_DIRECTORY}]
        if mode == "letsencrypt"
        else [{"module": "internal"}]
    )
    assert (
        config["apps"]["pki"]["certificate_authorities"]["local"]["install_trust"]
        is False
    )


def test_reset_refuses_nested_bind_mount_before_mutations(installed, monkeypatch):
    root, config, host = installed
    monkeypatch.setattr(reset, "mount_points", lambda: {root / "var/lib/aster/backups"})
    with pytest.raises(ValueError, match="mounted data"):
        make_reset(installed).preflight()
    assert config.exists() and not host.calls


def test_reset_handles_untouched_packaged_caddy_after_partial_install(installed):
    import hashlib

    root, config, host = installed
    config.unlink()
    caddyfile = root / "etc/caddy/Caddyfile"
    caddyfile.write_text(":80 {\n file_server\n}\n")

    def command(args, **kwargs):
        if args[0] == "dpkg-query":
            return (
                "/etc/caddy/Caddyfile "
                + hashlib.md5(caddyfile.read_bytes()).hexdigest()
            )
        return host(args, **kwargs)

    plan = reset.Reset(
        root, command, lambda name: "/bin/" + name if name != "iptables" else None
    ).preflight()
    assert caddyfile in plan.paths
    plan.apply()
    assert not caddyfile.exists()


def test_community_http_setup_without_provider_keys(tmp_path):
    path = tmp_path / "community.env"
    answers = iter(["", "no"])
    site.setup(path, lambda _: next(answers), lambda _: "")
    values = site.read_config(path)
    assert values["ASTER_ORIGIN"] == "http://localhost"
    assert values["OWNCMD_EDITION"] == "community"
    assert len(values["OWNCMD_SETUP_TOKEN"]) >= 40
    assert values["OPENROUTER_API_KEY"] == values["EXA_API_KEY"] == ""
    rendered = site.render_caddy(values)
    assert "http://localhost" in rendered and "bind 127.0.0.1" in rendered
    assert "tls " not in rendered


def test_community_http_private_ip():
    values = {"ASTER_ORIGIN": "http://192.168.1.10", "ASTER_TLS_MODE": "none"}
    assert site.site_settings(values) == ("192.168.1.10", "none")
    assert "http://192.168.1.10" in site.render_caddy(values)


def test_upgrade_preserves_previous_release_for_backup_and_rollback(tmp_path):
    script = (SCRIPTS.parent / "install.sh").read_text()
    start = script.index('previous=""')
    block = script[start : script.index("# Back up existing application data", start)]
    base = tmp_path / "aster"
    old = base / "releases" / "previous"
    old.mkdir(parents=True)
    (base / "current").symlink_to(old)
    script = block.replace("/opt/aster", str(base)) + '\nprintf "%s" "$previous"\n'
    result = subprocess.run(
        ["bash", "-eu", "-c", script], text=True, capture_output=True, check=True
    )
    assert result.stdout == str(old)
