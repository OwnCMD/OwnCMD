import asyncio, io, json, time, zipfile
from pathlib import Path
import pytest
from app import core, accounts, documents, providers, billing
from conftest import login


def make_owner(email="admin@example.com"):
    id = core.ident()
    with core.db() as c:
        c.execute(
            "INSERT INTO users VALUES(%s,%s,%s,%s)", (id, email, "unused", time.time())
        )
    return id


@pytest.fixture
def catalog(monkeypatch):
    async def models():
        return {
            id: {
                "name": id,
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                "supported_parameters": ["tools"],
                "architecture": {"input_modalities": ["text", "image"]},
            }
            for id in [
                "test/one",
                "test/two",
                providers.configured_model("chat"),
                providers.configured_model("work"),
            ]
        }

    monkeypatch.setattr(providers, "catalog", models)
    return asyncio.run(models())


def test_inheritance_override_and_auto(catalog):
    owner = make_owner()
    p = accounts.defaults()
    p["models"]["chat"] = {"allowed": ["test/one", "test/two"], "auto": "test/one"}
    accounts.save_global("operator", asyncio.run(accounts.validate_policy(p)), 0)
    assert accounts.resolve_model(owner, "chat") == "test/one"
    accounts.save_account(
        "operator",
        owner,
        {
            "version": 0,
            "role": "user",
            "disabled": False,
            "overrides": {
                "models": {"work": {"allowed": ["test/two"], "auto": "test/two"}}
            },
        },
    )
    assert accounts.resolve_model(owner, "work") == "test/two"
    assert accounts.resolve_model(owner, "chat", "test/two") == "test/two"
    with pytest.raises(ValueError):
        accounts.resolve_model(owner, "work", "test/one")
    p["models"]["chat"]["auto"] = "test/two"
    accounts.save_global("operator", p, 1)
    assert accounts.resolve_model(owner, "chat") == "test/two"
    assert accounts.resolve_model(owner, "work") == "test/two"
    with pytest.raises(ValueError, match="changed"):
        accounts.save_global("operator", p, 1)


@pytest.mark.parametrize(
    "policy",
    [
        {"models": {"work": {"allowed": ["missing/model"], "auto": "missing/model"}}},
        {"models": {"chat": {"allowed": ["test/one"], "auto": "test/two"}}},
        {"features": {"foo": True}},
        {"limits": {"file_mb": 513}},
        {"limits": {"file_mb": True}},
        {"features": {"chat": "false"}},
    ],
)
def test_invalid_policies_rejected(policy, catalog):
    with pytest.raises(ValueError):
        asyncio.run(accounts.validate_policy(policy, True))


def test_admin_security_sessions_audit_and_credit(client, catalog):
    h = login(client)
    assert client.get("/api/admin/users").status_code == 403
    with core.db() as c:
        owner = c.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    accounts.bootstrap("a@example.com")
    assert client.get("/api/admin/settings").status_code == 200
    assert (
        client.put(
            "/api/admin/settings", headers={"Origin": "https://testserver"}, json={}
        ).status_code
        == 403
    )
    assert client.get("/api/me").json()["account"]["role"] == "admin"
    body = {"role": "user", "disabled": False, "overrides": {}, "version": 1}
    assert (
        client.put("/api/admin/users/" + owner, headers=h, json=body).status_code == 400
    )
    other = make_owner("other@example.com")
    key = core.ident()
    payload = {"key": key, "amount": "12.30", "reason": "Support adjustment"}
    assert (
        client.post(
            f"/api/admin/users/{other}/credit", headers=h, json=payload
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/admin/users/{other}/credit",
            headers=h,
            json={**payload, "amount": "99999", "key": core.ident()},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/admin/users/" + owner + "/revoke-sessions", headers=h, json={}
        ).status_code
        == 200
    )
    assert client.get("/api/me").status_code == 401


def test_suspended_and_feature_disabled_execution(catalog):
    owner = make_owner()
    accounts.save_account(
        "operator",
        owner,
        {
            "role": "user",
            "disabled": False,
            "overrides": {"features": {"work": False, "search": False}},
            "version": 0,
        },
    )
    with pytest.raises(ValueError, match="Work is disabled"):
        core.create_task(owner, "test", mode="work")
    with pytest.raises(ValueError):
        accounts.check_tool(owner, "search_web")
    accounts.save_account(
        "operator",
        owner,
        {"role": "user", "disabled": True, "overrides": {}, "version": 1},
    )
    with pytest.raises(ValueError, match="suspended"):
        billing.reserve(owner, "task", 0.01)


def test_selected_model_billing_and_revocation(catalog):
    owner = make_owner()
    p = accounts.defaults()
    p["models"]["chat"] = {"allowed": ["test/one", "test/two"], "auto": "test/two"}
    accounts.save_global("operator", p, 0)
    task = core.create_task(owner, "Hello", mode="chat", model_choice="test/one")
    row = core.owned(owner, task)
    state = core.state(row)
    selected, body, rid, estimate = asyncio.run(
        providers._prepare_model(row, state, [], "system")
    )
    assert selected == body["model"] == "test/one"
    billing.settle(rid, 0.001)
    assert billing.activity(owner)["totals"]["charge"] == 0.001
    p["models"]["chat"] = {"allowed": ["test/two"], "auto": "test/two"}
    accounts.save_global("operator", p, 1)
    with pytest.raises(ValueError, match="no longer"):
        asyncio.run(providers._prepare_model(row, state, [], "system"))


def upload(owner, data, name="report.txt"):
    r = documents.create(owner, {"name": name, "size": len(data)})
    for n, start in enumerate(range(0, len(data), documents.PART)):
        documents.put(owner, r["id"], n, data[start : start + documents.PART])
    documents.finish(owner, r["id"])
    assert documents.process_one()
    return documents.owned(owner, r["id"])


def test_large_resumable_upload_encrypted_and_scoped():
    owner = make_owner()
    data = b"Important evidence: zebra metric 4500.\n" * 90000
    r = documents.create(owner, {"name": "big.csv", "size": len(data)})
    id = r["id"]
    part = data[: documents.PART]
    documents.put(owner, id, 0, part)
    documents.put(owner, id, 0, part)
    assert documents.owned(owner, id)["received"] == len(part)
    with pytest.raises(ValueError, match="different"):
        documents.put(owner, id, 0, b"X" * len(part))
    with pytest.raises(ValueError, match="incomplete"):
        documents.finish(owner, id)
    for n, start in enumerate(range(documents.PART, len(data), documents.PART), 1):
        documents.put(owner, id, n, data[start : start + documents.PART])
    assert b"Important evidence" not in (documents.directory(id) / "0.enc").read_bytes()
    documents.finish(owner, id)
    assert documents.process_one()
    r = documents.owned(owner, id)
    assert r["status"] == "ready"
    task = core.create_task(owner, "Find zebra", mode="chat", attachments=[id])
    row = core.owned(owner, task)
    found = documents.retrieve(row, {"action": "search", "id": id, "query": "zebra"})
    assert len(found["matches"]) == 3 and found["next_offset"] == 3
    assert "4500" in found["matches"][0]["text"]
    assert b"".join(documents.bytes_iter(r)) == data
    other = make_owner("other@example.com")
    other_task = core.create_task(other, "Find zebra", mode="chat")
    with pytest.raises(ValueError):
        documents.retrieve(core.owned(other, other_task), {"action": "read", "id": id})
    with pytest.raises(KeyError):
        core.create_task(other, "Read private", mode="chat", attachments=[id])
    with pytest.raises(ValueError, match="Sent attachments"):
        documents.remove(owner, id)
    assert documents.owned(owner, id)["status"] == "ready"
    # Deleting the conversation still releases its documents for normal cleanup.
    with core.db() as c:
        c.execute("DELETE FROM events WHERE task=%s", (task,))
        c.execute("DELETE FROM tasks WHERE id=%s", (task,))
    documents.remove(owner, id)
    with pytest.raises(KeyError):
        documents.owned(owner, id)
    assert not (core.DATA / "uploads" / id).exists()


def test_office_text_and_formulas_are_not_executed():
    owner = make_owner()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="word"><w:body><w:p><w:r><w:t>Quarterly revenue 3500</w:t></w:r></w:p></w:body></w:document>',
        )
    r = upload(owner, out.getvalue(), "brief.docx")
    assert r["status"] == "ready"
    task = core.create_task(owner, "Read brief", mode="chat", attachments=[r["id"]])
    found = documents.retrieve(
        core.owned(owner, task), {"action": "read", "id": r["id"]}
    )
    assert "3500" in found["matches"][0]["text"]


def test_pdf_text_and_actual_page_image():
    owner = make_owner()
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    stream = b"BT /F1 18 Tf 70 700 Td (Revenue 12500 with a blue chart below) Tj ET 0.1 0.3 0.9 rg 70 400 120 200 re f"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 2 /Kids [3 0 R 4 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 7\n0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    r = upload(owner, out.getvalue(), "report.pdf")
    assert r["status"] == "ready", documents.public(r)
    task = core.create_task(owner, "Analyze chart", mode="chat", attachments=[r["id"]])
    row = core.owned(owner, task)
    result = documents.retrieve(row, {"action": "image", "id": r["id"], "page": 1})
    assert result["image_ref"]["page"] == 1
    state = core.state(row)
    state["messages"].append(
        {"role": "tool", "content": json.dumps(result), "tool_call_id": "one"}
    )
    prompt, images = documents.model_context(row, state)
    assert r["id"] in prompt
    assert images[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert documents.render_page(r, 1).startswith(b"\xff\xd8")
    with pytest.raises(ValueError):
        documents.retrieve(row, {"action": "image", "id": r["id"], "page": 3})


@pytest.mark.parametrize(
    "name,data",
    [
        ("broken.pdf", b"not a PDF"),
        ("binary.txt", b"\x00x"),
        ("malicious.docx", b"not a zip"),
    ],
)
def test_bad_documents_fail_cleanly(name, data):
    owner = make_owner()
    r = upload(owner, data, name)
    assert r["status"] == "failed"
    assert documents.public(r)["info"]["error"]


def test_limits_temporary_and_cleanup():
    owner = make_owner()
    p = {"limits": {"file_mb": 1, "storage_mb": 1}}
    accounts.save_account(
        "operator",
        owner,
        {"role": "user", "disabled": False, "overrides": p, "version": 0},
    )
    with pytest.raises(ValueError):
        documents.create(owner, {"name": "huge.txt", "size": 1048577})
    r = upload(owner, b"evidence")
    id = r["id"]
    with pytest.raises(ValueError):
        core.create_task(
            owner, "test", mode="chat", temporary_chat=True, attachments=[id]
        )
    with core.db() as c:
        c.execute(
            "UPDATE documents SET updated=%s WHERE id=%s", (time.time() - 90000, id)
        )
    documents.cleanup()
    with pytest.raises(KeyError):
        documents.owned(owner, id)


def test_upload_http_auth_and_size(client):
    h = login(client)
    r = client.post(
        "/api/attachments", headers=h, json={"name": "readme.txt", "size": 5}
    )
    assert r.status_code == 200
    id = r.json()["id"]
    assert (
        client.put(
            f"/api/attachments/{id}/parts/0", headers=h, content=b"hello"
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/attachments/{id}/parts/0", headers=h, content=b"hello"
        ).status_code
        == 200
    )
    assert client.get(f"/api/attachments/{id}/download").content == b"hello"
    assert (
        client.put(
            f"/api/attachments/{id}/parts/1",
            headers=h,
            content=b"x" * (documents.PART + 1),
        ).status_code
        == 413
    )
    assert client.delete(f"/api/attachments/{id}", headers=h).status_code == 200


def test_sent_attachments_cannot_be_removed_through_either_endpoint(client):
    h = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    doc = upload(owner, b"Permanent conversation evidence")
    id = doc["id"]
    task = core.create_task(owner, "Read evidence", mode="chat", attachments=[id])
    assert (
        client.delete(f"/api/tasks/{task}/attachments/{id}", headers=h).status_code
        == 409
    )
    assert client.delete(f"/api/attachments/{id}", headers=h).status_code == 400
    assert (
        client.get(f"/api/attachments/{id}/download").content
        == b"Permanent conversation evidence"
    )
    assert (
        client.get(f"/api/tasks/{task}/attachments").json()["attachments"][0]["id"]
        == id
    )
    with core.db() as c:
        c.execute(
            "UPDATE documents SET updated=%s WHERE id=%s", (time.time() - 90000, id)
        )
    documents.cleanup()
    assert (
        client.get(f"/api/attachments/{id}/download").content
        == b"Permanent conversation evidence"
    )


def test_office_embedded_images_reach_vision_context():
    import base64

    owner = make_owner()
    out = io.BytesIO()
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jY9sAAAAASUVORK5CYII="
    )
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="word"><w:p><w:t>Chart follows</w:t></w:p></w:document>',
        )
        z.writestr("word/media/image1.png", png)
    r = upload(owner, out.getvalue(), "illustrated.docx")
    assert r["status"] == "ready"
    assert documents.public(r)["info"]["image_types"] == {"2": "image/png"}
    task = core.create_task(owner, "Inspect chart", mode="chat", attachments=[r["id"]])
    row = core.owned(owner, task)
    result = documents.retrieve(row, {"action": "image", "id": r["id"], "page": 2})
    state = core.state(row)
    state["messages"].append({"role": "tool", "content": json.dumps(result)})
    _, images = documents.model_context(row, state)
    assert images[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert documents.render_page(r, 2) == png


def test_malformed_new_api_payloads_fail_as_client_errors(client, catalog):
    h = login(client)
    accounts.bootstrap("a@example.com")
    assert client.post("/api/attachments", headers=h, json=[]).status_code == 400
    assert client.put("/api/admin/settings", headers=h, json=[]).status_code == 400
    with core.db() as c:
        owner = c.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    for value in ("garbage", "NaN", None):
        assert (
            client.post(
                "/api/admin/users/" + owner + "/credit",
                headers=h,
                json={"amount": value, "key": core.ident(), "reason": "test request"},
            ).status_code
            == 404
        )


def test_rate_card_follows_account_models_and_auto(client, catalog):
    h = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    accounts.save_account(
        "operator",
        owner,
        {
            "role": "user",
            "disabled": False,
            "version": 0,
            "overrides": {
                "models": {
                    "chat": {"allowed": ["test/one", "test/two"], "auto": "test/two"}
                }
            },
        },
    )
    r = client.get("/api/pricing")
    assert r.status_code == 200
    rows = [m for m in r.json()["models"] if m["mode"] == "chat"]
    assert [m["model"] for m in rows] == ["test/one", "test/two"]
    assert [m["auto"] for m in rows] == [False, True]
    assert rows[0]["pricing"]["prompt"] == 0.000001


def test_installation_probes_have_explicit_service_policy():
    from app.operations import prepare_smoke_account

    p = accounts.defaults()
    p["features"].update(chat=False, work=False, browser=False, code=False)
    accounts.save_global("operator", p, 0)
    owner = prepare_smoke_account()
    tid = core.create_task(owner, "Installation probe", mode="chat")
    assert core.owned(owner, tid)["owner"] == owner
    assert accounts.require(owner, "browser")["role"] == "user"
    normal = make_owner()
    with pytest.raises(ValueError, match="disabled"):
        core.create_task(normal, "Hello", mode="chat")
