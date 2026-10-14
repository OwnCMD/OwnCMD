import os, json, time, re, hmac, base64, secrets, mimetypes, asyncio, hashlib, binascii
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
import httpx
from . import core, billing, profile, scheduling, temporary, accounts
from .tools import broker, checkpoint, SandboxError
from .render import markdown, code_preview
from .chat import turn as chat_turn, work_handoff
from .providers import generate_title, ProviderError

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
STATIC = Path(__file__).parent / "static"
# Next.js static exports contain deterministic inline hydration scripts. Authorize
# only those exact bytes; do not enable arbitrary inline scripts or unsafe-eval.
from html.parser import HTMLParser


class _HydrationHashes(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active = False
        self.parts = []
        self.hashes = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = "src" not in dict(attrs)
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.hashes.append(
                "'sha256-"
                + base64.b64encode(
                    hashlib.sha256("".join(self.parts).encode()).digest()
                ).decode()
                + "'"
            )
            self.active = False


_hydration = _HydrationHashes()
_hydration.feed((STATIC / "index.html").read_text())
SCRIPT_POLICY = "script-src 'self' " + " ".join(_hydration.hashes) + ";"


def auth(req):
    token = req.cookies.get("aster_session", "")
    with core.db() as c:
        r = c.execute(
            "SELECT * FROM sessions WHERE token=%s AND expires>%s",
            (core.digest(token), time.time()),
        ).fetchone()
    if not r:
        raise HTTPException(401, "Please sign in")
    if req.method not in ("GET", "HEAD") and not hmac.compare_digest(
        req.headers.get("x-csrf", ""), r["csrf"]
    ):
        raise HTTPException(403, "CSRF validation failed")
    try:
        path = req.url.path
        feature = next(
            (
                v
                for k, v in (
                    ("/api/skills", "skills"),
                    ("/api/memory", "memory"),
                    ("/api/schedules", "schedules"),
                    ("/api/connectors", "connectors"),
                )
                if path.startswith(k)
            ),
            None,
        )
        accounts.require(r["owner"], feature)
    except ValueError as e:
        raise HTTPException(403, str(e))
    return r["owner"]


def task(req, id):
    try:
        return core.owned(auth(req), id)
    except KeyError:
        raise HTTPException(404, "Conversation not found")


def work_task(req, id):
    r = task(req, id)
    if r.get("mode") != "work":
        raise HTTPException(
            400,
            "Chat mode does not use browser, files, code sandboxes, or computer tools",
        )
    return r


MAX_IMAGES = 8
MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_IMAGE_TOTAL = 18 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_DATA_IMAGE = re.compile(
    r"^data:(image/(?:jpeg|png|webp|gif));base64,([A-Za-z0-9+/=]+)$", re.I
)


def normalize_images(value, owner=None):
    if value and owner:
        accounts.require(owner, "uploads")
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > MAX_IMAGES:
        raise ValueError(f"Attach up to {MAX_IMAGES} images per message.")
    result = []
    total = 0
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Invalid image attachment")
        url = str(item.get("data_url") or item.get("url") or "").strip()
        match = _DATA_IMAGE.fullmatch(url)
        if not match or match.group(1).lower() not in IMAGE_TYPES:
            raise ValueError("Images must be JPEG, PNG, WebP, or GIF files.")
        try:
            raw = base64.b64decode(match.group(2), validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Invalid image data")
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("Each image must be smaller than 6 MB.")
        total += len(raw)
        if total > MAX_IMAGE_TOTAL:
            raise ValueError("Combined images must be smaller than 18 MB.")
        mime = match.group(1).lower()
        result.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{base64.b64encode(raw).decode()}",
                    "detail": "auto",
                },
            }
        )
    return result


def content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(x.get("text", ""))
            for x in content
            if isinstance(x, dict) and x.get("type") == "text"
        )
    return ""


def public_messages(s, task=None):
    out = []
    for m in s.get("messages", []):
        role = m.get("role")
        content = m.get("content")
        text = content_text(content)
        images = []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "image_url":
                    url = (block.get("image_url") or {}).get("url", "")
                    if _DATA_IMAGE.fullmatch(url):
                        images.append({"url": url})
        if not text.strip() and not images:
            continue
        if role == "user":
            item = {
                "role": "user",
                "text": text,
                "html": markdown(text),
                "images": images,
            }
            out.append(item)
        elif role == "assistant" and not m.get("tool_calls"):
            item = {
                "role": "assistant",
                "text": text,
                "html": markdown(
                    text, task, m.get("artifacts", s.get("artifacts", []))
                ),
                "id": m.get("id"),
            }
            if task:
                from . import artifacts

                item["artifacts"] = [
                    {**x, "url": artifacts.url(task, x["path"])}
                    for x in m.get("artifacts", [])
                    if isinstance(x, dict) and x.get("path")
                ]
            if isinstance(m.get("sources"), list):
                item["sources"] = m["sources"][:30]
            out.append(item)
    return out[-80:]


def public_error(value):
    if not value:
        return value
    text = str(value)
    if re.search(r"openrouter|api\.exa\.ai|google/gemini|openai/gpt", text, re.I):
        return "An OwnCMD service could not complete this request. Please retry or contact support."
    return text


def public_event(e):
    body = json.loads(core.dec(e["body"]))
    for key in (
        "model",
        "provider",
        "provider_id",
        "pricing",
        "cost",
        "provider_cost",
        "reported_cost",
    ):
        body.pop(key, None)
    if body.get("error"):
        body["error"] = public_error(body["error"])
    return {"id": e["id"], "kind": e["kind"], "body": body, "created": e["created"]}


def ai_busy(r):
    # Workspace input uses the action mutex too; it is not an AI generation.
    return r["busy"] > time.time() and (
        r["mode"] == "chat"
        or r["status"] in ("queued", "running", "approval")
        or r["lease"] > time.time()
    )


def detail_payload(r, s, events):
    with core.db() as c:
        charge = c.execute(
            "SELECT coalesce(sum(charge_nano),0) FROM usage_operations WHERE task=%s AND owner=%s",
            (r["id"], r["owner"]),
        ).fetchone()[0]
    pending = s.get("pending") or {}
    approval = profile.prefill(r["owner"], pending.get("approval"))
    if approval and pending.get("calls"):
        approval = {**approval, "id": pending["calls"][pending["index"]]["id"]}
    return {
        "id": r["id"],
        "title": r["title"],
        "mode": r.get("mode", "work"),
        "status": r["status"],
        "control": r["control"],
        "busy": ai_busy(r),
        "updated": r["updated"],
        "app_preview": s.get("app_preview"),
        "result": s.get("result"),
        "result_html": markdown(s.get("result"), r["id"], s.get("artifacts", [])),
        "error": public_error(s.get("error")),
        "steps": s.get("steps", 0),
        "cost": billing.usd(charge),
        "mode_label": "Work mode" if r.get("mode") == "work" else "Chat mode",
        "approval": approval,
        "messages": public_messages(s, r["id"]),
        "sources": s.get("sources", []),
        "browser_used": bool(s.get("browser_used")),
        "skills": s.get("skills", {"mode": "auto", "pins": []}),
        "model_choice": s.get("model_choice", "auto"),
        "model": s.get("model"),
        "temporary": bool(r.get("temporary")),
        "work_suggestion": s.get("work_suggestion"),
        "events": [public_event(e) for e in events],
    }


async def _rename_task(owner, task_id, prompt):
    try:
        title = await generate_title(owner, task_id, prompt)
        if not title:
            return
        with core.db() as c:
            c.execute(
                "UPDATE tasks SET title=%s,updated=%s WHERE id=%s AND owner=%s",
                (title, time.time(), task_id, owner),
            )
        core.event(task_id, "title_updated", {"title": title})
    except Exception:
        pass


@app.middleware("http")
async def headers(req, call_next):
    multimodal = (
        req.url.path == "/api/tasks"
        or req.url.path.endswith("/chat")
        or req.url.path.endswith("/command")
    )
    max_body = (
        26 * 1024 * 1024
        if multimodal
        else (
            12 * 1024 * 1024
            if req.url.path.startswith("/api/skills")
            else 2 * 1024 * 1024
        )
    )
    if req.url.path == "/api/support/uploads":
        max_body = 10 * 1024 * 1024
    try:
        body_length = int(req.headers.get("content-length", "0") or 0)
    except ValueError:
        return JSONResponse({"detail": "Invalid Content-Length"}, 400)
    if body_length < 0 or body_length > max_body:
        return JSONResponse({"detail": "Request too large"}, 413)
    if req.method not in ("GET", "HEAD") and req.headers.get("origin") != core.ORIGIN:
        return JSONResponse({"detail": "Origin rejected"}, 403)
    try:
        r = await call_next(req)
    except ProviderError as e:
        r = JSONResponse({"detail": str(e)}, e.status if 400 <= e.status < 600 else 502)
    except httpx.HTTPError:
        r = JSONResponse({"detail": "Provider unavailable. Please retry."}, 502)
    except billing.CreditError as e:
        r = JSONResponse({"detail": str(e)}, 402)
    except SandboxError as e:
        r = JSONResponse(
            {
                "detail": (
                    e.detail
                    if e.status < 500
                    else "Workspace is temporarily unavailable. Please retry."
                )
            },
            e.status,
        )
    except (ValueError, KeyError) as e:
        r = JSONResponse({"detail": str(e)}, 400)
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "no-referrer"
    r.headers["Cache-Control"] = "no-store"
    if req.url.path.startswith("/preview/"):
        r.headers["Content-Security-Policy"] = (
            "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https:; style-src 'unsafe-inline' https:; img-src data: https:; font-src https: data:; connect-src 'none'; form-action 'none'; base-uri 'none'"
        )
    else:
        r.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            + SCRIPT_POLICY
            + " style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; frame-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'"
        )
    return r


@app.get("/health")
def health():
    with core.db() as c:
        c.execute("SELECT 1")
    return {"ok": True}


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.post("/api/login")
async def login(req: Request):
    b = await req.json()
    email = str(b.get("email", "")).strip().lower()
    password = b.get("password", "")
    if not isinstance(password, str) or len(password) > 128:
        raise HTTPException(400, "Invalid credentials")
    if not core.rate("login-ip:" + req.client.host, 30, 900) or not core.rate(
        "login-user:" + core.digest(email), 10, 900
    ):
        raise HTTPException(429, "Too many attempts. Try later.")
    with core.db() as c:
        r = c.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
    try:
        if not r:
            core.PH.hash("dummy-password-for-equal-work")
            raise ValueError()
        core.PH.verify(r["password"], password)
    except Exception:
        raise HTTPException(401, "Invalid email or password")
    accounts.require(r["id"])
    token = secrets.token_urlsafe(40)
    csrf = secrets.token_urlsafe(24)
    with core.db() as c:
        c.begin_write()
        current = c.execute(
            "SELECT password FROM users WHERE id=%s", (r["id"],)
        ).fetchone()
        if not current or current["password"] != r["password"]:
            raise HTTPException(401, "Invalid email or password")
        c.execute(
            "INSERT INTO sessions VALUES(%s,%s,%s,%s)",
            (core.digest(token), r["id"], csrf, time.time() + 604800),
        )
        c.commit()
    response = JSONResponse({"ok": True, "csrf": csrf})
    response.set_cookie(
        "aster_session",
        token,
        httponly=True,
        secure=core.ORIGIN.startswith("https://"),
        samesite="strict",
        max_age=604800,
        path="/",
    )
    return response


@app.post("/api/logout")
def logout(req: Request):
    temporary.discard_owner(auth(req))
    with core.db() as c:
        c.execute(
            "DELETE FROM sessions WHERE token=%s",
            (core.digest(req.cookies.get("aster_session", "")),),
        )
    r = JSONResponse({"ok": True})
    r.delete_cookie("aster_session")
    return r


@app.get("/api/me")
def me(req: Request):
    owner = auth(req)
    with core.db() as c:
        u = c.execute("SELECT email FROM users WHERE id=%s", (owner,)).fetchone()
        s = c.execute(
            "SELECT csrf FROM sessions WHERE token=%s",
            (core.digest(req.cookies["aster_session"]),),
        ).fetchone()
        used = c.execute(
            "SELECT coalesce(sum(amount),0) FROM ledger WHERE owner=%s AND created>%s",
            (owner, time.time() - 86400),
        ).fetchone()[0]
    with core.db() as c:
        profile_row = c.execute(
            "SELECT name,country,first_name,last_name FROM user_profiles WHERE owner=%s",
            (owner,),
        ).fetchone()
    return {
        "email": u["email"],
        "first_name": profile_row["first_name"] if profile_row else "",
        "last_name": profile_row["last_name"] if profile_row else "",
        "name": profile_row["name"] if profile_row else "",
        "country": profile_row["country"] if profile_row else "",
        "csrf": s["csrf"],
        "usage": used,
        "daily_budget": None,
        "account": accounts.effective(owner),
    }


@app.get("/api/tasks")
def tasks(req: Request):
    owner = auth(req)
    with core.db() as c:
        rows = c.execute(
            "SELECT id,title,status,mode,control,created,updated FROM tasks WHERE owner=%s ORDER BY updated DESC LIMIT 100",
            (owner,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/tasks/{id}")
async def delete_task(id: str, req: Request):
    owner = auth(req)
    if temporary.is_temporary(id):
        try:
            temporary.discard(owner, id)
        except KeyError:
            raise HTTPException(404, "Conversation not found")
        return {"ok": True}
    with core.db() as c:
        r = c.execute(
            "SELECT * FROM tasks WHERE id=%s AND owner=%s", (id, owner)
        ).fetchone()
        if not r:
            raise HTTPException(404, "Conversation not found")
        if r["status"] in ("queued", "running") or r["busy"] > time.time():
            raise HTTPException(
                409, "Stop the active work before deleting this conversation"
            )
    try:
        await broker(id, "stop")
    except Exception:
        pass
    snapshot = (
        Path(os.getenv("ASTER_DATA", "/var/lib/aster")) / "snapshots" / (id + ".enc")
    )
    try:
        snapshot.unlink(missing_ok=True)
    except Exception:
        pass
    with core.db() as c:
        c.begin_write()
        c.execute("DELETE FROM previews WHERE task=%s", (id,))
        c.execute("DELETE FROM events WHERE task=%s", (id,))
        c.execute("DELETE FROM tasks WHERE id=%s AND owner=%s", (id, owner))
        c.commit()
    return {"ok": True}


def validate_browser_display(a):
    if (
        not isinstance(a, dict)
        or not {"width", "height"} <= set(a)
        or set(a) - {"width", "height", "mobile"}
        or any(type(a[k]) is not int for k in ("width", "height"))
        or not 320 <= a["width"] <= 1920
        or not 240 <= a["height"] <= 4096
        or ("mobile" in a and type(a["mobile"]) is not bool)
    ):
        raise HTTPException(400, "Invalid browser dimensions")
    return a


@app.post("/api/tasks")
async def create(req: Request):
    owner = auth(req)
    billing.require_credit(owner)
    if not core.rate(
        "tasks:" + owner, accounts.effective(owner)["limits"]["tasks_hour"], 3600
    ):
        raise HTTPException(429, "Hourly conversation limit reached")
    b = await req.json()
    mode = str(b.get("mode", "work")).lower()
    prompt = b.get("prompt")
    images = normalize_images(b.get("images"), owner)
    if not isinstance(b.get("temporary", False), bool):
        raise ValueError("Temporary must be true or false")
    tid = core.create_task(
        owner,
        prompt,
        b.get("id"),
        mode,
        images,
        temporary_chat=b.get("temporary", False),
        browser_display=(
            validate_browser_display(b["browser_display"])
            if "browser_display" in b
            else None
        ),
        skills_config=b.get("skills"),
        model_choice=b.get("model", "auto"),
        attachments=b.get("attachments"),
    )
    # Creation is atomic and fast. Chat execution starts only after the browser has opened the SSE stream.
    return {"id": tid, "mode": mode}


@app.post("/api/tasks/{id}/chat")
async def chat_message(id: str, req: Request, background_tasks: BackgroundTasks):
    r = task(req, id)
    if r.get("mode") != "chat":
        raise HTTPException(400, "This conversation is in Work mode")
    if r["busy"] > time.time():
        raise HTTPException(409, "OwnCMD is still answering the previous message")
    b = await req.json()
    initial = bool(b.get("initial", False))
    text = str(b.get("text", "")).strip()
    images = normalize_images(b.get("images"), r["owner"])
    if b.get("attachments"):
        from . import documents

        with core.db() as c:
            c.begin_write()
            documents.link(c, r["owner"], id, b["attachments"])
            c.commit()
    if images and initial:
        raise HTTPException(
            409, "Initial images are attached when the conversation is created"
        )
    content = ([{"type": "text", "text": text}] + images) if images else text
    if initial:
        state = core.state(r)
        if len(
            [m for m in state.get("messages", []) if m.get("role") == "user"]
        ) != 1 or any(m.get("role") == "assistant" for m in state.get("messages", [])):
            raise HTTPException(409, "Initial response already started")
    try:
        s = await chat_turn(
            r,
            text=None if initial else content,
            initial=initial,
            **({"model_choice": b["model"]} if "model" in b else {}),
        )
    except Exception as e:
        raise HTTPException(
            402 if isinstance(e, billing.CreditError) else 502, str(e)[:800]
        )
    if initial and not r.get("temporary"):
        background_tasks.add_task(
            _rename_task,
            r["owner"],
            id,
            content_text(state["messages"][0].get("content", "")),
        )
    return {"ok": True, "searched": bool(s.get("sources"))}


@app.get("/api/tasks/{id}")
def detail(id: str, req: Request):
    r = task(req, id)
    if r.get("temporary"):
        events = temporary.events(r["owner"], id)
    else:
        with core.db() as c:
            events = list(
                reversed(
                    c.execute(
                        "SELECT * FROM events WHERE task=%s ORDER BY id DESC LIMIT 250",
                        (id,),
                    ).fetchall()
                )
            )
    # Read state after the event snapshot: a completion can never outrun its saved reply.
    r = task(req, id)
    return detail_payload(r, core.state(r), events)


@app.get("/api/tasks/{id}/usage")
async def conversation_usage(id: str, req: Request):
    r = task(req, id)
    s = core.state(r)
    from .conversation_usage import summary

    result = summary(r["owner"], id)
    result.update(
        {
            "mode": r["mode"],
            "selected_model": s.get("model"),
            "model_choice": s.get("model_choice", "auto"),
            "status": r["status"],
            "busy": ai_busy(r),
            "runtimes": None,
            "runtime_available": r["mode"] != "work",
        }
    )
    if r["mode"] == "work":
        try:
            resources = await asyncio.wait_for(broker(id, "resources"), 8)
            result.update(
                {"runtimes": resources["runtimes"], "runtime_available": True}
            )
        except Exception:
            result["runtime_message"] = (
                "Live workspace status is unavailable. Usage totals are still shown."
            )
    return result


@app.post("/api/tasks/{id}/runtime-stop")
async def runtime_stop(id: str, req: Request):
    r = work_task(req, id)
    body = await req.json()
    kind = body.get("kind")
    if kind not in ("code", "browser"):
        raise HTTPException(400, "Choose a coding sandbox or browser")
    if (
        r["lease"] > time.time()
        or r["busy"] > time.time()
        or (r["control"] != "human" and r["status"] in ("queued", "running"))
    ):
        raise HTTPException(
            409,
            "Pause work and wait for its current action before stopping this resource.",
        )
    if r["status"] == "cancelled":
        return await broker(id, "stop-" + kind)
    core.begin_action(id, r["control"], browser_stop=True)
    try:
        result = await broker(id, "stop-" + kind)
        core.event(
            id,
            "runtime_stopped",
            {
                "text": ("Coding sandbox" if kind == "code" else "Browser")
                + " stopped; runtime stopped.",
                "kind": kind,
            },
        )
        return result
    finally:
        core.end_action(id)


@app.get("/api/tasks/{id}/stream")
async def stream(id: str, req: Request):
    owner = auth(req)
    try:
        core.owned(owner, id)
    except KeyError:
        raise HTTPException(404, "Conversation not found")
    try:
        last = int(
            req.headers.get("last-event-id") or req.query_params.get("after") or 0
        )
    except Exception:
        last = 0

    async def generate():
        nonlocal last
        last_state = ""
        started = time.monotonic()
        while time.monotonic() - started < 55:
            if await req.is_disconnected():
                break
            if temporary.is_temporary(id):
                try:
                    rows = temporary.events(owner, id, last)
                    r = temporary.owned(owner, id)
                except KeyError:
                    break
            else:
                with core.db() as c:
                    rows = c.execute(
                        "SELECT * FROM events WHERE task=%s AND id>%s ORDER BY id LIMIT 100",
                        (id, last),
                    ).fetchall()
                    r = c.execute(
                        "SELECT * FROM tasks WHERE id=%s AND owner=%s", (id, owner)
                    ).fetchone()
            if not r:
                break
            for e in rows:
                last = e["id"]
                payload = json.dumps(public_event(e), separators=(",", ":"))
                yield f"id: {last}\nevent: activity\ndata: {payload}\n\n"
            state = json.dumps(
                {
                    "status": r["status"],
                    "control": r["control"],
                    "busy": ai_busy(r),
                    "updated": r["updated"],
                },
                separators=(",", ":"),
            )
            if state != last_state:
                last_state = state
                yield "event: state\ndata: " + state + "\n\n"
            await asyncio.sleep(0.65)
        yield "event: reconnect\ndata: {}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/tasks/{id}/work-handoff")
async def confirm_work_handoff(id: str, req: Request):
    r = task(req, id)
    body = await req.json()
    if body.get("action") not in ("accept", "dismiss"):
        raise ValueError("Choose accept or dismiss")
    if body["action"] == "accept":
        billing.require_credit(r["owner"])
    return work_handoff(
        r["owner"], id, body.get("proposal_id"), body["action"] == "accept"
    )


@app.post("/api/tasks/{id}/control")
async def control(id: str, req: Request):
    r = work_task(req, id)
    owner = r["owner"]
    b = await req.json()
    control = core.takeover(owner, id, b["owner"])
    if control == "ai":
        with core.db() as c:
            c.begin_write()
            fresh = c.execute(
                "SELECT * FROM tasks WHERE id=%s AND owner=%s", (id, owner)
            ).fetchone()
            s = core.state(fresh)
            pending = s.get("pending") or {}
            approval = pending.get("approval") or {}
            if (
                fresh["status"] == "approval"
                and approval.get("name") == "ask_user"
                and (approval.get("arguments") or {}).get("browser_takeover")
            ):
                pending["answer"] = (
                    "The user completed the requested human-only browser step and returned control. Observe the current page before continuing."
                )
                c.execute(
                    "UPDATE tasks SET state=%s,status='queued',updated=%s WHERE id=%s",
                    (core.enc(json.dumps(s)), time.time(), id),
                )
            c.commit()
    return {"control": control}


@app.post("/api/tasks/{id}/command")
async def command(id: str, req: Request):
    r = task(req, id)
    b = await req.json()
    op = b.get("action")
    s = core.state(r)
    if r.get("mode") == "chat":
        if op != "followup":
            raise HTTPException(400, "Chat mode only accepts conversation messages")
        text = str(b.get("text", "")).strip()
        images = normalize_images(b.get("images"), r["owner"])
        content = ([{"type": "text", "text": text}] + images) if images else text
        try:
            await chat_turn(r, text=content, initial=False)
        except Exception as e:
            raise HTTPException(502, str(e)[:800])
        return {"ok": True}
    if op in ("pause", "cancel"):
        with core.db() as c:
            c.execute(
                "UPDATE tasks SET status=%s WHERE id=%s",
                ("paused" if op == "pause" else "cancelled", id),
            )
        core.event(
            id, op, {"text": "Paused by user" if op == "pause" else "Cancelled by user"}
        )
        if op == "cancel":
            await broker(id, "stop")
    elif op == "followup":
        if b.get("attachments"):
            from . import documents

            with core.db() as c:
                c.begin_write()
                documents.link(c, r["owner"], id, b["attachments"])
                c.commit()
        if r["lease"] > time.time():
            raise HTTPException(
                409,
                "OwnCMD is finishing the current action. Pause first if you need to interrupt it immediately.",
            )
        instruction = str(b.get("text", "")).strip()
        images = normalize_images(b.get("images"), r["owner"])
        if len(instruction) > 24000 or (not instruction and not images):
            raise HTTPException(
                400, "Message must be 1–24,000 characters or include an image"
            )
        content = (
            ([{"type": "text", "text": instruction}] + images)
            if images
            else instruction
        )
        if s.get("pending"):
            p = s["pending"]
            for call in p["calls"][p["index"] :]:
                s["messages"].append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": "Action interrupted or superseded. Inspect current state; do not assume it completed or repeat it blindly.",
                    }
                )
        from . import skills

        if "skills" in b:
            s["skills"] = skills.selection(r["owner"], b["skills"])
        else:
            skills.followup(s, instruction)
        if "model" in b:
            accounts.resolve_model(r["owner"], "work", b["model"])
            s["model_choice"] = b["model"]
        s["pending"] = None
        s.pop("inflight", None)
        s.pop("error", None)
        s["messages"].append({"role": "user", "content": content})
        s["result"] = ""
        s["steps"] = 0
        s["attempts"] = 0
        s["not_before"] = 0
        s["retry"] = 0
        s["searches"] = 0
        s["sources"] = []
        s["completion_guard"] = ""
        s["completion_retries"] = 0
        s.pop("notebook_recovery", None)
        s.pop("output_recovery", None)
        # Record the turn boundary before making it runnable so worker activity can never race ahead of the new-turn marker.
        core.event(id, "followup", {"text": instruction})
        with core.db() as c:
            c.execute(
                "UPDATE tasks SET state=%s,status='queued',control='ai',lease=0,updated=%s WHERE id=%s",
                (core.enc(json.dumps(s)), time.time(), id),
            )
    elif op == "resume":
        if r["lease"] > time.time():
            raise HTTPException(409, "Wait for the current action to finish")
        if s.get("inflight"):
            raise HTTPException(
                409,
                "An interrupted action needs inspection and a follow-up, not blind replay",
            )
        if (s.get("output_recovery") or {}).get("blocked"):
            raise HTTPException(
                409,
                "Automatic model recovery is exhausted. Send a follow-up to continue from saved progress; you can select another available Work model.",
            )
        with core.db() as c:
            c.execute(
                "UPDATE tasks SET status='queued',control='ai',updated=%s WHERE id=%s",
                (time.time(), id),
            )
        core.event(id, "resume", {"text": "Resumed"})
    elif op in ("approve", "deny", "answer"):
        with core.db() as c:
            c.begin_write()
            fresh = c.execute("SELECT * FROM tasks WHERE id=%s", (id,)).fetchone()
            s = core.state(fresh)
            if fresh["status"] != "approval" or not s.get("pending"):
                raise HTTPException(409, "No pending request")
            p = s["pending"]
            call = p["calls"][p["index"]]
            args = json.loads(call["function"].get("arguments") or "{}")
            if op == "approve":
                p["approved"] = call["id"]
                event = (
                    "approved",
                    {"text": args.get("confirmation_reason") or "Action approved"},
                )
            elif op == "deny":
                p["denied"] = True
                event = ("denied", {"text": "Action declined"})
            else:
                if call["function"]["name"] != "ask_user":
                    raise HTTPException(
                        400, "This action requires approval, not an answer"
                    )
                if b.get("approval_id") is not None and b["approval_id"] != call["id"]:
                    raise HTTPException(
                        409,
                        "This request changed. Review the current form before continuing.",
                    )
                try:
                    value = profile.answer_text(args, b)
                except ValueError as e:
                    raise HTTPException(400, str(e))
                if not value.strip():
                    raise HTTPException(400, "Enter an answer before continuing")
                p["answer"] = value
                event = (
                    "answer",
                    {
                        "text": (
                            "Sensitive information provided"
                            if profile.sensitive_answer(args)
                            else value[:500]
                        )
                    },
                )
            c.execute(
                "UPDATE tasks SET state=%s,status='queued',lease=0,updated=%s WHERE id=%s",
                (core.enc(json.dumps(s)), time.time(), id),
            )
            c.commit()
        core.event(id, event[0], event[1])
    else:
        raise HTTPException(400, "Unknown command")
    return {"ok": True}


@app.get("/api/tasks/{id}/frame")
async def frame(id: str, req: Request):
    work_task(req, id)
    try:
        return await broker(id, "frame")
    except Exception as e:
        raise HTTPException(503, str(e))


@app.get("/api/tasks/{id}/browser-frame")
async def browser_frame(id: str, req: Request):
    work_task(req, id)
    headers = {"Authorization": "Bearer " + os.environ["ASTER_BROKER_KEY"]}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "http://127.0.0.1:8091/task/" + id + "/frame.jpg", headers=headers
            )
    except httpx.HTTPError as e:
        raise HTTPException(503, "Live browser frame unavailable: " + str(e)[:240])
    if r.status_code != 200 or not r.content:
        try:
            detail = r.json().get("detail", "Live browser is starting")
        except Exception:
            detail = "Live browser is starting"
        raise HTTPException(
            r.status_code if r.status_code in (404, 410) else 503, str(detail)[:240]
        )
    return Response(
        r.content,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "X-Aster-Frame-Seq": r.headers.get("x-aster-frame-seq", "0"),
            "X-Aster-Frame-Age": r.headers.get("x-aster-frame-age", "0"),
            "X-Aster-Frame-URL": r.headers.get("x-aster-frame-url", ""),
        },
    )


@app.post("/api/tasks/{id}/browser")
async def browser(id: str, req: Request):
    r = work_task(req, id)
    b = await req.json()
    kind = b.get("kind")
    if kind == "start":
        core.begin_action(id, "human")
        try:
            return await broker(id, "action", {"kind": "observe", "args": {}})
        finally:
            core.end_action(id)
    if kind == "resize":
        # Display sizing is independent of who owns keyboard/pointer control. Only
        # validated dimensions/device mode are forwarded, serialized with page actions.
        a = b.get("args", {})
        validate_browser_display(a)
        if r["status"] == "cancelled":
            raise HTTPException(409, "Browser task stopped")
        return await broker(id, "action", {"kind": "resize", "args": a})
    if kind not in (
        "navigate",
        "pointer",
        "text",
        "key",
        "scroll",
        "back",
        "forward",
        "reload",
        "input",
        "selection",
    ):
        raise HTTPException(400, "Invalid browser action")
    core.begin_action(id, "human")
    try:
        return await broker(
            id,
            "action",
            {
                "kind": kind,
                "args": b.get("args", {}),
                "approval_token": b.get("approval_token"),
            },
        )
    finally:
        core.end_action(id)


@app.post("/api/tasks/{id}/browser-stop")
async def browser_stop(id: str, req: Request):
    r = work_task(req, id)
    if r["status"] == "cancelled":
        return await broker(id, "stop-browser")
    if r["lease"] > time.time() or (
        r["control"] != "human" and r["status"] in ("queued", "running")
    ):
        raise HTTPException(
            409,
            "Pause OwnCMD and wait for its current action before closing the browser",
        )
    core.begin_action(id, r["control"], browser_stop=True)
    try:
        result = await broker(id, "stop-browser")
        core.event(
            id,
            "browser_stopped",
            {"text": "Browser stopped; runtime stopped. Saved sign-ins retained."},
        )
        return result
    finally:
        core.end_action(id)


@app.get("/api/tasks/{id}/notebook")
def work_notebook(
    id: str, req: Request, key: str | None = None, query: str = "", offset: int = 0
):
    from . import notebook

    row = work_task(req, id)
    notebook.ensure(row, core.state(row))
    if key:
        return notebook.read(row["owner"], id, key, offset)
    if query:
        return notebook.search(row["owner"], id, query, offset)
    return notebook.listing(row["owner"], id, offset)


@app.get("/api/tasks/{id}/files")
async def files(id: str, req: Request):
    work_task(req, id)
    return await broker(id, "file", {"op": "list"})


@app.get("/api/tasks/{id}/file")
async def file_contents(id: str, req: Request, path: str):
    work_task(req, id)
    if not path or len(path) > 1000:
        raise HTTPException(400, "Invalid file path")
    result = await broker(id, "file", {"op": "read", "path": path})
    html, language = code_preview(result.get("content", ""), path)
    return {**result, "html": html, "language": language, "read_only": True}


@app.get("/api/tasks/{id}/download")
async def download(id: str, req: Request, path: str):
    work_task(req, id)
    r = await broker(id, "file", {"op": "download", "path": path})
    name = re.sub("[^a-zA-Z0-9._-]", "_", r["name"])
    return Response(
        base64.b64decode(r["data"]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.post("/api/tasks/{id}/upload")
async def upload(id: str, req: Request):
    r = work_task(req, id)
    if r["control"] != "human" or r["busy"] > time.time():
        raise HTTPException(409, "Take control before editing files")
    b = await req.json()
    core.begin_action(id, "human")
    try:
        result = await broker(
            id, "file", {"op": "write", "path": b["path"], "content": b["content"]}
        )
        await checkpoint(id)
        return result
    finally:
        core.end_action(id)


@app.get("/api/settings")
def get_settings(req: Request):
    return core.preferences(auth(req))


@app.put("/api/settings")
async def update_settings(req: Request):
    owner = auth(req)
    b = await req.json()
    current = core.preferences(owner)
    allowed = {
        "theme": ("system", "light", "dark"),
        "font": ("inter", "system", "serif", "mono"),
        "font_size": ("small", "medium", "large"),
        "density": ("comfortable", "compact"),
    }
    for key, values in allowed.items():
        if key in b:
            if b[key] not in values:
                raise HTTPException(400, "Invalid " + key.replace("_", " "))
            current[key] = b[key]
    for key in ("send_enter", "reduce_motion", "sources_expanded", "activity_expanded"):
        if key in b:
            if not isinstance(b[key], bool):
                raise HTTPException(400, "Invalid " + key.replace("_", " "))
            current[key] = b[key]
    return core.save_preferences(owner, current)


@app.post("/api/change-password")
async def change_password(req: Request):
    owner = auth(req)
    b = await req.json()
    current = b.get("current", "")
    new = b.get("new", "")
    confirm = b.get("confirm", "")
    if (
        not isinstance(current, str)
        or not isinstance(new, str)
        or not isinstance(confirm, str)
        or not 12 <= len(new) <= 128
    ):
        raise HTTPException(400, "New password must be 12–128 characters")
    if new != confirm:
        raise HTTPException(400, "New passwords do not match")
    with core.db() as c:
        u = c.execute("SELECT password FROM users WHERE id=%s", (owner,)).fetchone()
    try:
        core.PH.verify(u["password"], current)
    except Exception:
        raise HTTPException(401, "Current password is incorrect")
    if current == new:
        raise HTTPException(400, "Choose a different password")
    hashed = core.PH.hash(new)
    token = core.digest(req.cookies.get("aster_session", ""))
    with core.db() as c:
        c.begin_write()
        latest = c.execute(
            "SELECT password FROM users WHERE id=%s", (owner,)
        ).fetchone()
        session = c.execute(
            "SELECT 1 FROM sessions WHERE token=%s AND owner=%s AND expires>%s",
            (token, owner, time.time()),
        ).fetchone()
        if not latest or latest["password"] != u["password"] or not session:
            raise HTTPException(
                401, "Please sign in again before changing your password"
            )
        c.execute("UPDATE users SET password=%s WHERE id=%s", (hashed, owner))
        c.execute("DELETE FROM sessions WHERE owner=%s AND token<>%s", (owner, token))
        c.commit()
    return {"ok": True}


@app.get("/api/memory")
def memory(req: Request):
    return core.memories(auth(req), limit=500)


@app.post("/api/memory")
async def add_memory(req: Request):
    owner = auth(req)
    b = await req.json()
    text = str(b.get("text", "")).strip()
    if not 1 <= len(text) <= 2000:
        raise HTTPException(400, "Memory must be 1–2,000 characters")
    with core.db() as c:
        if (
            c.execute(
                "SELECT count(*) FROM memory WHERE owner=%s", (owner,)
            ).fetchone()[0]
            >= 500
        ):
            raise HTTPException(400, "Memory limit reached; delete outdated entries")
        id = core.ident()
        c.execute(
            "INSERT INTO memory VALUES(%s,%s,%s,%s)",
            (id, owner, core.enc(text), time.time()),
        )
    return {"id": id}


@app.delete("/api/memory/{id}")
def delete_memory(id: str, req: Request):
    with core.db() as c:
        c.execute("DELETE FROM memory WHERE id=%s AND owner=%s", (id, auth(req)))
    return {"ok": True}


@app.get("/api/schedules")
def schedules(req: Request):
    return scheduling.list_schedules(auth(req))


@app.post("/api/schedules/readiness")
async def schedule_readiness(req: Request):
    owner = auth(req)
    b = await req.json()
    return scheduling.readiness(owner, b.get("prompt", ""), b.get("id"))


@app.post("/api/schedules/preview")
async def schedule_preview(req: Request):
    cfg, when, enabled = scheduling.validate(auth(req), await req.json())
    times = [when]
    for _ in range(min(5, cfg.get("max_runs") or 5) - 1):
        n = scheduling.next_time(cfg, times[-1])
        if n is None:
            break
        times.append(n)
    return {"times": times, "timezone": cfg["timezone"]}


@app.post("/api/schedules")
async def create_schedule(req: Request):
    return scheduling.save(auth(req), await req.json())


@app.put("/api/schedules/{id}")
async def update_schedule(id: str, req: Request):
    b = await req.json()
    b["id"] = id
    try:
        return scheduling.save(auth(req), b, id)
    except KeyError:
        raise HTTPException(404, "Schedule not found")


@app.post("/api/schedules/{id}/action")
async def schedule_action(id: str, req: Request):
    owner = auth(req)
    b = await req.json()
    action = b.get("action")
    if action == "run":
        token = str(b.get("token", ""))
        if not re.fullmatch(r"[a-zA-Z0-9-]{16,80}", token):
            raise ValueError("A run request needs a unique request ID")
        try:
            return scheduling.dispatch_due(only=id, owner=owner, manual_token=token)
        except KeyError:
            raise HTTPException(404, "Schedule not found")
    if action not in ("pause", "resume"):
        raise ValueError("Invalid schedule action")
    try:
        return scheduling.set_enabled(owner, id, action == "resume", b.get("version"))
    except KeyError:
        raise HTTPException(404, "Schedule not found")


@app.delete("/api/schedules/{id}")
def delete_schedule(id: str, req: Request):
    with core.db() as c:
        c.execute("DELETE FROM schedules WHERE id=%s AND owner=%s", (id, auth(req)))
    return {"ok": True}


@app.get("/preview/{token}/{path:path}")
async def preview(token: str, path: str, req: Request):
    owner = auth(req)
    if (
        path.startswith("/")
        or any(p == ".." for p in path.split("/"))
        or any(v in path for v in ("\\", "?", "#", "%"))
    ):
        raise HTTPException(400, "Invalid preview path")
    with core.db() as c:
        r = c.execute(
            "SELECT * FROM previews WHERE token=%s AND owner=%s AND expires>%s",
            (core.digest(token), owner, time.time()),
        ).fetchone()
    if not r:
        raise HTTPException(410, "Preview expired or unavailable")
    async with httpx.AsyncClient(timeout=15) as c:
        up = await c.get(
            "http://127.0.0.1:8091/task/" + r["task"] + "/preview/" + path,
            headers={"Authorization": "Bearer " + os.environ["ASTER_BROKER_KEY"]},
        )
    return Response(
        up.content,
        status_code=up.status_code,
        media_type=up.headers.get("content-type", "text/plain"),
    )


@app.post("/api/browser-session/clear")
async def clear_browser_session(req: Request):
    owner = auth(req)
    async with httpx.AsyncClient(timeout=30) as c:
        response = await c.post(
            "http://127.0.0.1:8091/owner/" + owner + "/forget-browser",
            headers={"Authorization": "Bearer " + os.environ["ASTER_BROKER_KEY"]},
        )
    if not response.is_success:
        raise HTTPException(
            response.status_code,
            "Wait for current browser actions to finish, then retry",
        )
    return {"ok": True}


async def begin_workspace_action(id, owner):
    # Wait only before acquiring the mutex, never replay an action. This also
    # covers a preview reopened while its previous request is still finishing.
    deadline = time.monotonic() + 5
    while True:
        fresh = core.owned(owner, id)
        if fresh["lease"] > time.time() or fresh["status"] in (
            "queued",
            "running",
            "approval",
        ):
            raise HTTPException(
                409,
                "Pause OwnCMD and wait for its current action before changing the workspace",
            )
        if fresh["busy"] <= time.time():
            try:
                core.begin_action(id, fresh["control"], workspace=True)
                return
            except ValueError:
                if core.owned(owner, id)["busy"] <= time.time():
                    raise
        if time.monotonic() >= deadline:
            raise HTTPException(
                409, "A workspace action is still finishing. Please try again shortly."
            )
        await asyncio.sleep(0.05)


@app.post("/api/tasks/{id}/workspace")
async def workspace(id: str, req: Request):
    r = work_task(req, id)
    b = await req.json()
    op = b.get("op")
    if op == "services":
        return await broker(id, "services", {"op": "list"})
    if op == "terminal" and b.get("action") == "read":
        return await broker(
            id, "terminal", {"op": "read", "cursor": b.get("cursor", 0)}
        )
    if op == "preview" and b.get("kind") == "resize":
        a = validate_browser_display(b.get("args", {}))
        if r["status"] == "cancelled":
            raise HTTPException(409, "Workspace task stopped")
        return await broker(id, "dev-action", {"kind": "resize", "args": a})
    if op not in ("run", "save", "service", "preview", "terminal"):
        raise HTTPException(400, "Unknown workspace operation")
    if r["lease"] > time.time() or r["status"] in ("queued", "running", "approval"):
        raise HTTPException(
            409,
            "Pause OwnCMD and wait for its current action before changing the workspace",
        )
    await begin_workspace_action(id, r["owner"])
    try:
        # Opening the preview records coding context once. Pointer/typing batches must
        # not decrypt and rewrite an entire long Work conversation on every input.
        if op != "preview" or b.get("kind") == "open":
            with core.db() as c:
                current = c.execute(
                    "SELECT state FROM tasks WHERE id=%s", (id,)
                ).fetchone()
                state = core.state(current)
                state["coding_used"] = True
                state["input_context"] = "code"
                c.execute(
                    "UPDATE tasks SET state=%s WHERE id=%s",
                    (core.enc(json.dumps(state)), id),
                )
        if op == "terminal":
            return await broker(
                id,
                "terminal",
                {k: b[k] for k in ("data", "cols", "rows", "cursor") if k in b}
                | {"op": b.get("action", "open")},
            )
        elif op == "run":
            result = await broker(
                id, "run", {"command": b.get("command", ""), "timeout": 100}
            )
        elif op == "save":
            result = await broker(
                id,
                "file",
                {
                    "op": "write",
                    "path": b.get("path", ""),
                    "content": b.get("content", ""),
                },
            )
        elif op == "service":
            result = await broker(
                id,
                "services",
                {k: b[k] for k in ("name", "command", "port") if k in b}
                | {"op": b.get("action", "list")},
            )
        else:
            return await broker(
                id, "dev-action", {"kind": b.get("kind"), "args": b.get("args", {})}
            )
        await checkpoint(id)
        core.event(
            id, "workspace_saved", {"text": "Workspace changes saved", "name": op}
        )
        return result
    finally:
        core.end_action(id)


@app.get("/api/tasks/{id}/workspace-frame")
async def workspace_frame(id: str, req: Request):
    work_task(req, id)
    async with httpx.AsyncClient(timeout=12) as c:
        r = await c.get(
            "http://127.0.0.1:8091/task/" + id + "/dev-frame",
            headers={"Authorization": "Bearer " + os.environ["ASTER_BROKER_KEY"]},
        )
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


@app.get("/api/tasks/{id}/browser-stream")
async def browser_stream(id: str, req: Request):
    from .preview_stream import relay

    work_task(req, id)
    return await relay(
        "http://127.0.0.1:8091/task/" + id + "/frame-stream",
        {"Authorization": "Bearer " + os.environ["ASTER_BROKER_KEY"]},
        lambda: work_task(req, id),
    )


@app.get("/api/tasks/{id}/workspace-stream")
async def workspace_stream(id: str, req: Request):
    from .preview_stream import relay

    work_task(req, id)
    return await relay(
        "http://127.0.0.1:8091/task/" + id + "/dev-stream",
        {"Authorization": "Bearer " + os.environ["ASTER_BROKER_KEY"]},
        lambda: work_task(req, id),
    )


@app.get("/api/tasks/{id}/project.zip")
async def export_project(id: str, req: Request):
    work_task(req, id)
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.get(
            "http://127.0.0.1:8091/task/" + id + "/archive",
            headers={"Authorization": "Bearer " + os.environ["ASTER_BROKER_KEY"]},
        )
    return Response(
        r.content,
        status_code=r.status_code,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="aster-project.zip"'},
    )


def usage_filters(req):
    return {
        key: req.query_params.get(key, default)
        for key, default in [
            ("status", "all"),
            ("mode", "all"),
            ("query", ""),
            ("start_date", ""),
            ("end_date", ""),
            ("sort", "newest"),
            ("min_charge", ""),
            ("max_charge", ""),
            ("model", "all"),
            ("provider", "all"),
            ("task", ""),
            ("min_tokens", ""),
            ("max_tokens", ""),
        ]
    }


@app.get("/api/usage")
def usage(
    req: Request, days: int = 30, offset: int = 0, service: str = "all", limit: int = 25
):
    try:
        return billing.activity(
            auth(req),
            days,
            offset,
            service,
            max(10, min(100, limit)),
            **usage_filters(req),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/usage/export.csv")
def usage_export(req: Request, days: int = 30, service: str = "all"):
    try:
        content = billing.export_csv(auth(req), days, service, **usage_filters(req))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="aster-usage.csv"'},
    )


@app.get("/api/pricing")
async def pricing(req: Request):
    owner = auth(req)
    policy = accounts.effective(owner)
    from .providers import catalog

    models = []
    rates_updated = None
    cache = core.DATA / ("public-rate-card-" + core.digest(owner) + ".json")
    signature = hashlib.sha256(
        json.dumps(policy["models"], sort_keys=True).encode()
    ).hexdigest()
    try:
        catalog_rows = await catalog()
        for mode in ("chat", "work"):
            for id in policy["models"][mode]["allowed"]:
                data = catalog_rows.get(id, {})
                models.append(
                    {
                        "mode": mode,
                        "model": id,
                        "name": data.get("name", id),
                        "auto": id == policy["models"][mode]["auto"],
                        "pricing": {
                            k: float(v) * billing.MARKUP
                            for k, v in data.get("pricing", {}).items()
                            if k
                            in (
                                "prompt",
                                "completion",
                                "input_cache_read",
                                "input_cache_write",
                                "image",
                                "request",
                            )
                            and v is not None
                            and __import__("math").isfinite(float(v))
                            and float(v) >= 0
                        },
                        "available": bool(data),
                    }
                )
        if all(
            m["available"] and "prompt" in m["pricing"] and "completion" in m["pricing"]
            for m in models
        ):
            rates_updated = time.time()
            try:
                tmp = cache.with_suffix("." + core.ident() + ".tmp")
                tmp.write_text(
                    json.dumps(
                        {
                            "signature": signature,
                            "models": models,
                            "updated": rates_updated,
                        }
                    )
                )
                tmp.replace(cache)
            except OSError:
                pass
    except Exception:
        pass
    if not models or not all(m["available"] for m in models):
        try:
            saved = json.loads(cache.read_text())
            if saved.get("signature") == signature:
                models = saved["models"]
                rates_updated = saved["updated"]
        except (OSError, ValueError, KeyError):
            pass
    return {
        "currency": "USD",
        "models": models,
        "rates_updated": rates_updated,
        "checked_at": time.time(),
        "search": {
            "price": None,
            "basis": "Search cost is reported by the provider per request and shown in Usage. No fixed search rate or markup is imposed by OwnCMD.",
        },
        "browser_per_hour": float(billing.runtime_rate("browser")),
        "code_per_hour": float(billing.runtime_rate("code")),
        "runtime_basis": "Use Stop browser to release resources; hiding the preview keeps the session running. Idle browsers stop after 15 minutes, including while waiting for requested input. Preview polling does not extend these limits. OwnCMD releases its browser when its work finishes. Coding workspaces, including running apps, are metered until stopped or idle for 15 minutes.",
        "policy": "OwnCMD Community adds no fees or markup. Provider usage is recorded at cost. Pending estimates can change after settlement. Infrastructure estimates default to zero.",
    }


@app.post("/api/tasks/{id}/workspace-stop")
async def workspace_stop(id: str, req: Request):
    r = work_task(req, id)
    if r["lease"] > time.time() or r["status"] in ("queued", "running", "approval"):
        raise HTTPException(409, "Pause OwnCMD and wait for the current action first")
    await begin_workspace_action(id, r["owner"])
    try:
        await broker(id, "stop")
        with core.db() as c:
            fresh = c.execute("SELECT state FROM tasks WHERE id=%s", (id,)).fetchone()
            state = json.loads(core.dec(fresh["state"]))
            state.pop("app_preview", None)
            c.execute(
                "UPDATE tasks SET state=%s,updated=%s WHERE id=%s",
                (core.enc(json.dumps(state)), time.time(), id),
            )
        core.event(
            id,
            "workspace_stopped",
            {"text": "Workspace stopped; saved files preserved"},
        )
        return {"ok": True, "status": "stopped"}
    finally:
        core.end_action(id)


@app.get("/api/tasks/{id}/workspace-status")
async def workspace_status(id: str, req: Request):
    work_task(req, id)
    return await broker(id, "status", {})


@app.get("/api/personal-details")
def personal_details(req: Request):
    return profile.get(auth(req))


@app.put("/api/personal-details")
async def save_personal_details(req: Request):
    return profile.save(auth(req), await req.json())


@app.delete("/api/personal-details")
def clear_personal_details(req: Request):
    with core.db() as c:
        c.execute("DELETE FROM personal_details WHERE owner=%s", (auth(req),))
    return {"ok": True}


from .skill_routes import register as register_skills

register_skills(app, auth, work_task)

from .community import register as register_community

register_community(app, auth)

from .document_routes import register as register_documents

register_documents(app, auth, task)
