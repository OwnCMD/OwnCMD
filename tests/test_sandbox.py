import os, tempfile, importlib.util, base64, zipfile, io
import pytest
from fastapi.testclient import TestClient

os.environ["ASTER_SANDBOX_ROOT"] = tempfile.mkdtemp(prefix="sandbox-test-")
spec = importlib.util.spec_from_file_location("sandbox_server", "sandbox/server.py")
sandbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sandbox)


@pytest.fixture
def sc(monkeypatch):
    monkeypatch.setenv("ASTER_SANDBOX_KIND", "code")

    # Unit tests execute on the host, not in a sandbox network namespace.
    # Real checkpoint behavior is covered with isolated database/process fixtures.
    async def no_host_database(port):
        return False

    monkeypatch.setattr(sandbox, "database_available", no_host_database)
    with TestClient(sandbox.app) as c:
        yield c


def test_code_sandbox_cannot_control_browser(sc):
    assert sc.post("/action", json={"kind": "observe"}).status_code == 403
    assert sc.get("/frame").status_code == 403


def test_browser_sandbox_cannot_execute_code(sc, monkeypatch):
    monkeypatch.setenv("ASTER_SANDBOX_KIND", "browser")
    assert sc.post("/run", json={"command": "id"}).status_code == 403
    assert sc.post("/file", json={"op": "list"}).status_code == 403


def test_file_traversal_rejected(sc):
    for path in ["../etc/passwd", "/etc/passwd", "a/../../bad"]:
        assert sc.post("/file", json={"op": "read", "path": path}).status_code == 400


def test_file_roundtrip_and_preview(sc):
    assert (
        sc.post(
            "/file",
            json={"op": "write", "path": "index.html", "content": "<h1>Working</h1>"},
        ).status_code
        == 200
    )
    r = sc.get("/preview/index.html")
    assert r.status_code == 200
    assert r.text == "<h1>Working</h1>"
    r = sc.post("/file", json={"op": "download", "path": "index.html"})
    assert base64.b64decode(r.json()["data"]) == b"<h1>Working</h1>"


def test_command_result_and_timeout(sc):
    r = sc.post("/run", json={"command": "python3 -c 'print(2+2)'"}).json()
    assert r["exit_code"] == 0 and r["output"].strip() == "4"
    r = sc.post("/run", json={"command": "sleep 5", "timeout": 1}).json()
    assert r["exit_code"] == 124 and r["timed_out"]


def test_snapshot_restore_and_traversal(sc):
    sc.post("/file", json={"op": "write", "path": "memo.txt", "content": "persist me"})
    r = sc.post("/snapshot", json={})
    assert r.status_code == 200
    sandbox.safe("memo.txt").unlink()
    assert sc.post("/snapshot", json={"restore": r.json()["data"]}).status_code == 200
    assert sandbox.safe("memo.txt").read_text() == "persist me"
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("../escape.txt", "bad")
    # Invalid snapshot paths must fail and never write outside the task root.
    with pytest.raises(ValueError):
        sc.post("/snapshot", json={"restore": base64.b64encode(b.getvalue()).decode()})
    assert not (sandbox.root.parent / "escape.txt").exists()


def test_symlink_cannot_read_outside_workspace(sc):
    link = sandbox.root / "link"
    link.symlink_to("/etc/passwd")
    assert sc.post("/file", json={"op": "read", "path": "link"}).status_code == 400
    link.unlink()


def test_file_read_returns_live_viewer_metadata_and_bounds_preview(sc):
    content = "line\n" * 12000
    assert (
        sc.post(
            "/file", json={"op": "write", "path": "large.txt", "content": content}
        ).status_code
        == 200
    )
    data = sc.post("/file", json={"op": "read", "path": "large.txt"}).json()
    assert data["size"] == len(content.encode())
    assert data["truncated"] is True
    assert len(data["content"].encode()) <= 50000
    assert data["lines"] > 0


def test_resumable_attachment_staging_and_snapshot_exclusion(sc):
    import base64, uuid, io, zipfile

    path = ".aster/attachments/" + str(uuid.uuid4()) + "/source.csv"
    body = {"path": path, "total": 8}
    r = sc.post("/file", json={"op": "attachment_status", **body})
    assert r.status_code == 200 and r.json()["received"] == 0
    for offset, data in [(0, b"abcd"), (0, b"abcd"), (4, b"efgh")]:
        r = sc.post(
            "/file",
            json={
                "op": "attachment_part",
                **body,
                "offset": offset,
                "data": base64.b64encode(data).decode(),
            },
        )
        assert r.status_code == 200, r.text
    assert r.json()["complete"]
    assert (sandbox.root / path).read_bytes() == b"abcdefgh"
    assert path not in zipfile.ZipFile(io.BytesIO(sandbox.project_zip())).namelist()
    assert (
        sc.post(
            "/file", json={"op": "attachment_status", "path": "outside.csv", "total": 8}
        ).status_code
        == 400
    )
