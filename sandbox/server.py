import asyncio, os, json, base64, pathlib, zipfile, io, signal, time, hashlib, secrets, re, stat, sqlite3, tempfile, hmac, anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from playwright.async_api import async_playwright

app = FastAPI()
root = pathlib.Path(os.getenv("ASTER_SANDBOX_ROOT", "/work"))
root.mkdir(exist_ok=True)


@app.middleware("http")
async def isolation(req, call_next):
    key = os.getenv("ASTER_SANDBOX_KEY")
    if key and not hmac.compare_digest(req.headers.get("X-Aster-Sandbox", ""), key):
        return __import__("fastapi").responses.JSONResponse(
            {"detail": "Unauthorized sandbox request"}, 401
        )
    kind = os.getenv("ASTER_SANDBOX_KIND", "code")
    if (
        kind == "code"
        and req.url.path
        in ("/action", "/frame", "/frame.jpg", "/frame-stream", "/session")
        or kind == "browser"
        and req.url.path
        not in (
            "/health",
            "/action",
            "/frame",
            "/frame.jpg",
            "/frame-stream",
            "/session",
        )
    ):
        return __import__("fastapi").responses.JSONResponse(
            {"detail": "Operation unavailable in this sandbox"}, 403
        )
    return await call_next(req)


lock = asyncio.Lock()
frame_lock = asyncio.Lock()
browser = None
context = None
page = None
playwright = None
frame_cache = b""
frame_seq = 0
frame_ts = 0.0
frame_page = None
frame_cdp = None
frame_url = ""
initial_storage = None
payment_challenges = {}
init_lock = asyncio.Lock()
cast_lock = asyncio.Lock()
cast_session = None
cast_page = None
cast_users = 0
frame_cdp_page = None


async def stop_cast():
    global cast_session, cast_page
    session = cast_session
    cast_session = None
    cast_page = None
    if session:
        with anyio.move_on_after(3, shield=True):
            try:
                await session.send("Page.stopScreencast")
            except Exception:
                pass
            try:
                await session.detach()
            except Exception:
                pass


async def ensure_cast(p):
    global cast_session, cast_page
    async with cast_lock:
        if cast_session and cast_page is p:
            return
        await stop_cast()
        session = await p.context.new_cdp_session(p)
        cast_session = session
        cast_page = p

        async def received(event):
            global frame_cache, frame_seq, frame_ts, frame_url, frame_page
            try:
                if cast_session is session:
                    raw = base64.b64decode(event["data"], validate=True)
                    if raw and len(raw) <= 4 * 1024 * 1024:
                        frame_cache = raw
                        frame_seq += 1
                        frame_ts = time.monotonic()
                        frame_url = p.url
                        frame_page = p
            finally:
                try:
                    await session.send(
                        "Page.screencastFrameAck", {"sessionId": event["sessionId"]}
                    )
                except Exception:
                    pass

        session.on("Page.screencastFrame", received)
        try:
            await session.send(
                "Page.startScreencast",
                {
                    "format": "jpeg",
                    "quality": 65,
                    "maxWidth": 1920,
                    "maxHeight": 1200,
                    "everyNthFrame": 1,
                },
            )
        except BaseException:
            await stop_cast()
            raise


def frame_packet(raw=b""):
    # Length-prefixed metadata and binary JPEG, no base64 on the network.
    metadata = json.dumps(
        {
            "length": len(raw),
            "seq": frame_seq,
            "url": frame_url,
            "width": display_profile["width"],
            "height": display_profile["height"],
        },
        separators=(",", ":"),
    ).encode()
    return len(metadata).to_bytes(4, "big") + metadata + raw


async def live_frames(req, development=False):
    global cast_users
    if development and preview_port is None:
        raise HTTPException(409, "Open a running service first")
    if cast_users >= 4:
        raise HTTPException(429, "Too many preview viewers")
    # Allocation is performed by explicit start/open operations, never by viewing.
    if not browser or not context:
        raise HTTPException(410, "Browser has not started")

    async def chunks():
        global cast_users
        # Acquire inside the iterator so disconnecting before response headers cannot
        # leak a viewer or leave Chromium capturing with nobody watching.
        if cast_users >= 4:
            return
        cast_users += 1
        last = -1
        sent = 0
        try:
            while not await req.is_disconnected():
                p = await getpage()
                await ensure_cast(p)
                if frame_cache and frame_page is p and frame_seq != last:
                    last = frame_seq
                    sent = time.monotonic()
                    yield frame_packet(frame_cache)
                elif time.monotonic() - sent > 2:
                    sent = time.monotonic()
                    yield frame_packet()  # idle heartbeat, no repeated JPEG
                await asyncio.sleep(
                    1 / 30
                )  # latest frame only; no historical frame queue
        finally:
            cast_users -= 1
            if cast_users == 0:
                async with cast_lock:
                    if cast_users == 0:
                        await stop_cast()

    return StreamingResponse(
        chunks(),
        media_type="application/x-owncmd-frames",
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )


@app.get("/frame-stream")
async def browser_stream(req: Request):
    return await live_frames(req)


@app.get("/dev-stream")
async def development_stream(req: Request):
    return await live_frames(req, True)


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


try:
    display_profile = validate_browser_display(
        json.loads(
            os.getenv(
                "ASTER_BROWSER_DISPLAY", '{"width":1152,"height":720,"mobile":false}'
            )
        )
    )
except (ValueError, HTTPException):
    display_profile = {"width": 1152, "height": 720, "mobile": False}
device_sessions = {}
device_applied = {}
desktop_user_agent = ""
browser_version = ""


def device_identity(mobile):
    major = browser_version.split(".")[0]
    ua = (
        f"Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Mobile Safari/537.36"
        if mobile
        else desktop_user_agent
    )
    metadata = {
        "brands": [
            {"brand": "Chromium", "version": major},
            {"brand": "Not_A Brand", "version": "99"},
        ],
        "fullVersionList": [
            {"brand": "Chromium", "version": browser_version},
            {"brand": "Not_A Brand", "version": "99.0.0.0"},
        ],
        "fullVersion": browser_version,
        "platform": "Android" if mobile else "Linux",
        "platformVersion": "10.0.0" if mobile else "",
        "architecture": (
            ""
            if mobile
            else ("arm" if os.uname().machine in ("aarch64", "arm64") else "x86")
        ),
        "model": "K" if mobile else "",
        "mobile": mobile,
        "bitness": "" if mobile else "64",
        "wow64": False,
    }
    return {
        "userAgent": ua,
        "platform": "Linux armv8l" if mobile else "Linux " + os.uname().machine,
        "userAgentMetadata": metadata,
    }


def coding_proxy():
    from urllib.parse import urlsplit, unquote

    value = os.getenv("ASTER_CODE_PROXY", "")
    if os.getenv("ASTER_SANDBOX_KIND", "code") != "code" or not value:
        return {}
    proxy = urlsplit(value)
    if (
        proxy.scheme != "http"
        or not proxy.hostname
        or not proxy.port
        or not proxy.username
        or not proxy.password
    ):
        raise ValueError("Invalid coding proxy configuration")
    host = ("[" + proxy.hostname + "]") if ":" in proxy.hostname else proxy.hostname
    return {
        "proxy": {
            "server": f"http://{host}:{proxy.port}",
            "username": unquote(proxy.username),
            "password": unquote(proxy.password),
            "bypass": "localhost,127.0.0.1,[::1]",
        }
    }


async def new_browser_context():
    mobile = display_profile.get("mobile", False)
    ctx = await browser.new_context(
        viewport={k: display_profile[k] for k in ("width", "height")},
        screen={k: display_profile[k] for k in ("width", "height")},
        device_scale_factor=1,
        is_mobile=mobile,
        has_touch=mobile,
        user_agent=device_identity(mobile)["userAgent"],
        accept_downloads=True,
        storage_state=initial_storage,
        **coding_proxy(),
    )
    ctx.set_default_timeout(8000)
    return ctx


async def apply_display(p, profile):
    # This also runs on each newly discovered popup before further agent actions.
    if device_applied.get(p) == profile:
        return
    session = device_sessions.get(p)
    if session is None:
        session = await p.context.new_cdp_session(p)
        device_sessions[p] = session
    mobile = profile.get("mobile", False)
    await p.set_viewport_size({k: profile[k] for k in ("width", "height")})
    await session.send(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": profile["width"],
            "height": profile["height"],
            "deviceScaleFactor": 1,
            "mobile": mobile,
            "screenWidth": profile["width"],
            "screenHeight": profile["height"],
        },
    )
    await session.send(
        "Emulation.setTouchEmulationEnabled", {"enabled": mobile, "maxTouchPoints": 1}
    )
    await session.send("Emulation.setUserAgentOverride", device_identity(mobile))
    device_applied[p] = dict(profile)


browser_runtime_directory = None


def browser_environment():
    global browser_runtime_directory
    if browser_runtime_directory is None:
        browser_runtime_directory = pathlib.Path(
            tempfile.mkdtemp(prefix="aster-browser-", dir="/tmp")
        )
    paths = {
        key: browser_runtime_directory / child
        for key, child in (
            ("XDG_CONFIG_HOME", "config"),
            ("CHROME_CONFIG_HOME", "config"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_RUNTIME_DIR", "runtime"),
        )
    }
    for path in paths.values():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return {**os.environ, **{key: str(path) for key, path in paths.items()}}


async def launch_browser():
    global playwright, browser_runtime_directory
    playwright = await async_playwright().start()
    try:
        return await playwright.chromium.launch(
            headless=True,
            env=browser_environment(),
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-default-apps",
                "--no-first-run",
                "--disable-features=WebRtcHideLocalIpsWithMdns,Translate",
            ],
        )
    except BaseException:
        await playwright.stop()
        playwright = None
        if browser_runtime_directory:
            __import__("shutil").rmtree(browser_runtime_directory, ignore_errors=True)
            browser_runtime_directory = None
        raise


async def _getpage():
    global browser, context, page, playwright, desktop_user_agent, browser_version
    if not browser:
        browser = await launch_browser()
    if not browser_version:
        version_session = await browser.new_browser_cdp_session()
        version = await version_session.send("Browser.getVersion")
        await version_session.detach()
        browser_version = browser.version
        desktop_user_agent = version["userAgent"].replace("HeadlessChrome/", "Chrome/")
    if context is None:
        context = await new_browser_context()
    if not page or page.is_closed():
        page = await context.new_page()
    pages = [p for p in context.pages if not p.is_closed()]
    if pages:
        page = pages[-1]
    for closed in list(device_sessions):
        if closed.is_closed():
            device_sessions.pop(closed, None)
            device_applied.pop(closed, None)
    await apply_display(page, display_profile)
    return page


async def getpage():
    async with init_lock:
        return await _getpage()


async def fresh_navigation_page(previous):
    """Replace a probe tab, cancelling pending/error navigation in the old tab.
    Keep the browser context (cookies/storage/device identity), not a new browser.
    Ordinary browser navigation never calls this unless explicitly requested.
    """
    global page
    async with init_lock:
        candidate = await previous.context.new_page()
        try:
            await apply_display(candidate, display_profile)
            await previous.close(run_before_unload=False)
        except BaseException:
            await candidate.close(run_before_unload=False)
            raise
        page = candidate
        device_sessions.pop(previous, None)
        device_applied.pop(previous, None)
        return candidate


def safe(name):
    p = (root / name).resolve()
    if not p.is_relative_to(root) or p == root:
        raise ValueError("Path must be a file inside the task workspace")
    return p


async def refresh_frame(p, force=False):
    global frame_cache, frame_seq, frame_ts, frame_page, frame_cdp, frame_url, frame_cdp_page
    now = time.monotonic()
    if (
        not force
        and cast_session
        and cast_page is p
        and frame_cache
        and frame_page is p
    ):
        return
    # Browser actions must never starve the live view. Capture uses Chromium's
    # compositor directly and does not wait for web fonts or the action lock.
    if not force and frame_cache and frame_page is p and now - frame_ts < 0.10:
        return
    async with frame_lock:
        if (
            not force
            and frame_cache
            and frame_page is p
            and time.monotonic() - frame_ts < 0.10
        ):
            return
        try:
            if frame_page is not p or frame_cdp is None or frame_cdp_page is not p:
                if frame_cdp:
                    try:
                        await frame_cdp.detach()
                    except Exception:
                        pass
                frame_cdp = await p.context.new_cdp_session(p)
                frame_page = p
                frame_cdp_page = p
            data = await asyncio.wait_for(
                frame_cdp.send(
                    "Page.captureScreenshot",
                    {
                        "format": "jpeg",
                        "quality": 60,
                        "fromSurface": True,
                        "captureBeyondViewport": False,
                    },
                ),
                1.5,
            )
            raw = base64.b64decode(data["data"], validate=True)
            if not raw:
                raise ValueError("Empty browser frame")
            frame_cache = raw
            frame_seq += 1
            frame_ts = time.monotonic()
            frame_url = p.url
        except Exception:
            frame_page = None
            # Retain the last visible image on transient navigation/capture errors, but
            # expose its age. Never describe a stale cached frame as a fresh update.
            pass


def frame_headers():
    from urllib.parse import quote

    age = int(max(0, time.monotonic() - frame_ts) * 1000) if frame_ts else 999999
    return {
        "Cache-Control": "no-store",
        "X-Aster-Frame-Seq": str(frame_seq),
        "X-Aster-Frame-Age": str(age),
        "X-Aster-Frame-URL": quote(frame_url, safe=""),
    }


async def capture(p):
    await refresh_frame(p)
    if not frame_cache:
        await refresh_frame(p, True)
    return base64.b64encode(frame_cache).decode()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/frame")
async def frame():
    p = await getpage()
    return {"image": await capture(p), "url": p.url, "seq": frame_seq}


@app.get("/frame.jpg")
async def frame_jpg():
    p = await getpage()
    await refresh_frame(p)
    if not frame_cache:
        await refresh_frame(p, True)
    if not frame_cache:
        raise HTTPException(503, "The browser has not produced a frame yet")
    return Response(frame_cache, media_type="image/jpeg", headers=frame_headers())


DOM_OBSERVATION = r"""() => {
 const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};
 let focus=document.activeElement;
 while(focus?.shadowRoot?.activeElement)focus=focus.shadowRoot.activeElement;
 const search=!!focus?.matches('input[type=search],[role=combobox],input[aria-autocomplete],input[aria-controls],input[list]')||!!(focus?.matches('input')&&/search|find|ticker|company|location|destination/i.test([focus.name,focus.id,focus.placeholder].join(' ')));
 const ids=(focus?.getAttribute('aria-controls')||focus?.getAttribute('aria-owns')||'').split(/\s+/).filter(Boolean);
 const containers=ids.map(id=>document.getElementById(id)).filter(Boolean);
 if(search)containers.push(...document.querySelectorAll('[role=listbox],[role=menu],[class*=suggest],[class*=autocomplete],[class*=typeahead]'));
 const candidates=new Set([...containers].filter(visible).flatMap(c=>[...c.querySelectorAll('[role=option],[role=menuitem],li,a,button,[data-symbol]')]).filter(visible));
 const options=[...new Set([...document.querySelectorAll('[role=option]')].filter(visible).concat([...candidates]))].filter(e=>e.textContent?.trim()).slice(0,25);
 const normal=[...document.querySelectorAll('a,button,input,textarea,select,[role=button],[role=combobox],[role=option],[role=menuitem],[contenteditable=true]')].filter(visible);
 const nodes=[...new Set([...options,...normal])].slice(0,200);
 const state=window.__asterRefState||(window.__asterRefState={next:0,refs:new WeakMap()});
 const rows=nodes.map(e=>{if(!state.refs.has(e))state.refs.set(e,state.next++);const ref=state.refs.get(e);e.setAttribute('data-aster-ref',ref);
 const id=e.getAttribute('id'),label=(id&&document.querySelector('label[for="'+CSS.escape(id)+'"]')?.innerText)||e.closest('label')?.innerText||'';
 return {ref,tag:e.tagName,role:e.getAttribute('role')||'',text:(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder')||label||'').trim().slice(0,180),type:e.type||'',name:e.getAttribute('name')||'',autocomplete:e.getAttribute('aria-autocomplete')||e.getAttribute('autocomplete')||'',expanded:e.getAttribute('aria-expanded'),selected:e.getAttribute('aria-selected'),focused:e===focus,suggestion:options.includes(e),href:e.getAttribute('href')||'',options:e.tagName==='SELECT'?Array.from(e.options).slice(0,30).map(o=>(o.label||o.text||o.value).slice(0,120)):[]};});
 const suggestions=rows.filter(e=>e.suggestion).map(({ref,text,role})=>({ref,text,role}));
 return {elements:rows,search:{focused:search,suggestions,hint:search?(suggestions.length?'Choose the matching suggestion by ref after checking its full label. Prefer it to Enter; never choose an unrelated result.':'If this field offers autocomplete, observe again after a brief wait before submitting with Enter.') : ''}};
}"""


async def observe_page(p, wait_suggestions=False):
    snapshot = await p.evaluate(DOM_OBSERVATION)
    if (
        wait_suggestions
        and snapshot["search"]["focused"]
        and not snapshot["search"]["suggestions"]
    ):
        # Allow asynchronous autocomplete to render without a fixed delay on all
        # browser operations. The next observe remains available for slower sites.
        deadline = time.monotonic() + 0.9
        while time.monotonic() < deadline:
            await asyncio.sleep(0.15)
            snapshot = await p.evaluate(DOM_OBSERVATION)
            if snapshot["search"]["suggestions"]:
                break
    return snapshot


@app.post("/action")
async def action(req: Request):
    global page
    b = await req.json()
    kind = b.get("kind")
    a = b.get("args", {})
    async with lock:
        try:
            p = await getpage()
            if b.get("check_only"):
                # Observe the final-action gate before presenting the UI approval. This gives
                # the worker the SAME one-use token it later executes, avoiding double prompts.
                guard = (
                    await payment_guard(p, kind, a)
                    if kind in ("click", "key", "pointer", "text")
                    else None
                )
                if guard:
                    return guard
                routine = kind in (
                    "navigate",
                    "observe",
                    "type",
                    "text",
                    "select",
                    "scroll",
                    "wait",
                    "back",
                    "forward",
                    "reload",
                    "resize",
                ) or (
                    kind == "key"
                    and str(a.get("key", "")).lower()
                    not in ("enter", "return", "space")
                )
                if kind == "click":
                    label = await p.locator(
                        '[data-aster-ref="' + str(int(a["ref"])) + '"]'
                    ).inner_text(timeout=2000)
                    routine = bool(
                        re.fullmatch(
                            r"\s*(?:add to (?:cart|bag|basket)|view (?:cart|bag|basket)|(?:proceed|go) to checkout|checkout|continue shopping|select (?:size|colour|color)|apply (?:coupon|code))\s*",
                            label,
                            re.I,
                        )
                    )
                return {"approval_required": False, "routine": routine}
            if kind == "resize":
                validate_browser_display(a)
                await dev_input(p, "resize", a)
                return {"ok": True, "url": p.url, "frame_seq": frame_seq}
            if kind == "input":
                events = a.get("events")
                if not isinstance(events, list) or not 1 <= len(events) <= 80:
                    raise HTTPException(400, "Invalid browser input batch")
                allowed = {"pointer", "move", "text", "key", "scroll", "resize"}
                if any(
                    not isinstance(e, dict)
                    or e.get("kind") not in allowed
                    or not isinstance(e.get("args", {}), dict)
                    for e in events
                ):
                    raise HTTPException(400, "Unsupported browser input")
                for index, event in enumerate(events):
                    ek = event["kind"]
                    ea = event.get("args", {})
                    if ek in ("pointer", "key", "text"):
                        guard = await payment_guard(
                            p, ek, ea, b.get("approval_token") if index == 0 else None
                        )
                        if guard:
                            return {
                                **guard,
                                "pending_events": events[index:],
                                "processed": index,
                            }
                    await dev_input(p, ek, ea)
                return {
                    "ok": True,
                    "url": p.url,
                    "processed": len(events),
                    "frame_seq": frame_seq,
                }
            if kind == "selection":
                return {
                    "text": await p.evaluate(
                        "() => {const e=document.activeElement;if(e?.type==='password')return '';return typeof e?.selectionStart==='number'?e.value.slice(e.selectionStart,e.selectionEnd):window.getSelection()?.toString()||''}"
                    )
                }
            if kind in ("click", "key", "pointer", "text"):
                guard = await payment_guard(p, kind, a, b.get("approval_token"))
                if guard:
                    return guard
            navigation_response = None
            if kind == "navigate":
                from urllib.parse import urlsplit

                u = urlsplit(a["url"])
                if u.scheme not in ("http", "https") or u.username or u.password:
                    raise ValueError("Use a public HTTP or HTTPS URL")
                if type(a.get("fresh_page", False)) is not bool:
                    raise ValueError("fresh_page must be a boolean")
                if a.get("fresh_page"):
                    p = await fresh_navigation_page(p)
                navigation_response = await p.goto(
                    a["url"], wait_until="domcontentloaded", timeout=35000
                )
            elif kind == "observe":
                pass
            elif kind == "click":
                await p.locator('[data-aster-ref="' + str(int(a["ref"])) + '"]').click(
                    timeout=8000
                )
            elif kind == "type":
                await p.locator('[data-aster-ref="' + str(int(a["ref"])) + '"]').fill(
                    str(a.get("text", ""))[:12000], timeout=8000
                )
            elif kind == "select":
                loc = p.locator('[data-aster-ref="' + str(int(a["ref"])) + '"]')
                value = str(a.get("value", ""))[:1000]
                try:
                    await loc.select_option(label=value, timeout=8000)
                except Exception:
                    await loc.select_option(value=value, timeout=8000)
            elif kind == "key":
                await p.keyboard.press(str(a["key"])[:40])
            elif kind == "wait":
                await asyncio.sleep(max(0, min(5, float(a.get("seconds", 1)))))
            elif kind == "pointer":
                await dev_input(p, "pointer", a)
            elif kind == "text":
                await p.keyboard.insert_text(str(a["text"])[:12000])
            elif kind == "scroll":
                await p.mouse.wheel(0, max(-2000, min(2000, int(a.get("delta", 650)))))
            elif kind == "back":
                await p.go_back(wait_until="domcontentloaded", timeout=15000)
            elif kind == "forward":
                await p.go_forward(wait_until="domcontentloaded", timeout=15000)
            elif kind == "reload":
                await p.reload(wait_until="domcontentloaded", timeout=20000)
            else:
                raise ValueError("Unknown browser action")
            p = await getpage()
            snapshot = await observe_page(p, wait_suggestions=kind == "type")
            # Publish an action frame before reporting completion. No fixed sleep and no
            # network-idle wait; progressive page rendering remains visible during loading.
            await refresh_frame(p, True)
            return {
                **(
                    {"http_status": navigation_response.status}
                    if navigation_response is not None
                    else {}
                ),
                "url": p.url,
                "title": await p.title(),
                "text": (await p.locator("body").inner_text(timeout=7000))[:12000],
                **snapshot,
                "frame_seq": frame_seq,
                "frame_pending": time.monotonic() - frame_ts > 2,
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, str(e)[:500])


@app.post("/run")
async def run(req: Request):
    b = await req.json()
    command = b["command"]
    timeout = min(100, max(1, int(b.get("timeout", 60))))
    if not isinstance(command, str) or len(command) > 12000:
        raise HTTPException(400, "Invalid command")
    proc = await asyncio.create_subprocess_exec(
        "/bin/bash",
        "-c",
        command,
        cwd=root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
        env=process_env(),
    )
    output = bytearray()

    async def consume():
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            if len(output) < 48000:
                output.extend(chunk[: 48000 - len(output)])

    try:
        await asyncio.wait_for(asyncio.gather(consume(), proc.wait()), timeout)
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        return {
            "exit_code": 124,
            "output": output.decode(errors="replace"),
            "timed_out": True,
        }
    return {"exit_code": proc.returncode, "output": output.decode(errors="replace")}


@app.post("/file")
async def file(req: Request):
    b = await req.json()
    try:
        if b["op"] == "list":
            return {
                "files": [str(p.relative_to(root)) for p in workspace_files()][:5000]
            }
        p = safe(b["path"])
        if b["op"] == "info":
            if not p.is_file():
                raise ValueError("Download file not found")
            size = p.stat().st_size
            if size > 20 * 1024 * 1024:
                raise ValueError("Download exceeds 20 MB")
            return {"name": p.name, "size": size}
        if b["op"] in ("attachment_status", "attachment_part"):
            # Original uploads are recoverable from encrypted host storage and excluded
            # from project checkpoints. No caller-selected path outside this namespace.
            if not re.fullmatch(
                r"\.aster/attachments/[0-9a-f-]{36}/source\.[a-z0-9]+",
                str(p.relative_to(root)),
            ):
                raise ValueError("Invalid attachment path")
            total = b.get("total")
            offset = b.get("offset", 0)
            if type(total) != int or not 0 < total <= 512 * 1024 * 1024:
                raise ValueError("Invalid attachment size")
            temp = p.with_name(p.name + ".upload")
            if p.exists() and p.stat().st_size == total:
                return {"received": total, "complete": True}
            if b["op"] == "attachment_status":
                return {
                    "received": temp.stat().st_size if temp.exists() else 0,
                    "complete": False,
                }
            raw = base64.b64decode(b.get("data", ""), validate=True)
            if (
                type(offset) != int
                or offset < 0
                or not 0 < len(raw) <= 1024 * 1024
                or offset + len(raw) > total
            ):
                raise ValueError("Invalid attachment part")
            p.parent.mkdir(parents=True, exist_ok=True)
            size = temp.stat().st_size if temp.exists() else 0
            if offset < size:
                with temp.open("rb") as f:
                    f.seek(offset)
                    existing = f.read(len(raw))
                if existing != raw:
                    raise ValueError("Conflicting attachment part")
            elif offset == size:
                with temp.open("ab") as f:
                    f.write(raw)
            else:
                raise ValueError("Attachment part is out of order")
            received = temp.stat().st_size
            if received == total:
                temp.replace(p)
                p.chmod(0o400)
            return {"received": received, "complete": received == total}
        if b["op"] == "write":
            content = (
                base64.b64decode(b["data"], validate=True)
                if "data" in b
                else b["content"].encode("utf-8")
            )
            if len(content) > 1000000:
                raise ValueError("File exceeds 1 MB")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
            return {"written": b["path"]}
        if b["op"] == "read":
            size = p.stat().st_size
            with p.open("rb") as f:
                raw = f.read(50001)
            if b"\x00" in raw[:4096]:
                raise ValueError("Binary files can be downloaded but not previewed")
            shown = raw[:50000].decode("utf-8", errors="replace")
            return {
                "content": shown,
                "size": size,
                "truncated": size > 50000,
                "lines": shown.count("\n") + (1 if shown else 0),
            }
        if b["op"] == "download":
            if p.stat().st_size > 20 * 1024 * 1024:
                raise ValueError("Download exceeds 20 MB")
            return {"data": base64.b64encode(p.read_bytes()).decode(), "name": p.name}
    except Exception as e:
        raise HTTPException(400, str(e)[:200])
    raise HTTPException(400, "Invalid file operation")


def restore_capacity(items):
    # Validate the entire archive before writing anything. Count implicit parent
    # directories as well as files, matching the filesystem inode budget.
    entries = set()
    total = 0
    for item in items:
        path = pathlib.PurePosixPath(item.filename)
        entries.add(str(path))
        entries.update(str(parent) for parent in path.parents if str(parent) != ".")
        if not item.is_dir():
            total += ((item.file_size + 4095) // 4096) * 4096
    if total > int(os.getenv("ASTER_WORKSPACE_MB", "1536")) * 1024 * 1024 or len(
        entries
    ) > int(os.getenv("ASTER_WORKSPACE_FILES", "100000")):
        raise HTTPException(
            409,
            "Saved workspace exceeds the configured workspace limits. Raise the account limits before reopening; the saved checkpoint is preserved.",
        )


@app.post("/snapshot")
async def snapshot(req: Request):
    b = await req.json()
    if b.get("restore"):
        raw = base64.b64decode(b["restore"])
        z = zipfile.ZipFile(io.BytesIO(raw))
        total = 0
        for item in z.infolist():
            if stat.S_ISLNK(item.external_attr >> 16):
                raise HTTPException(400, "Snapshot symlinks are not allowed")
            safe(item.filename)
            total += item.file_size
            if total > 128 * 1024 * 1024 or len(z.infolist()) > 10000:
                raise HTTPException(400, "Snapshot exceeds limits")
        restore_capacity(z.infolist())
        for item in z.infolist():
            p = safe(item.filename)
            if item.is_dir():
                p.mkdir(parents=True, exist_ok=True)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(z.read(item))
                p.chmod(0o700 if (item.external_attr >> 16) & 0o111 else 0o600)
        return {"restored": True}
    await checkpoint_databases()
    return {"data": base64.b64encode(project_zip()).decode()}


@app.get("/preview/{name:path}")
async def preview(name: str):
    try:
        p = safe(name or "index.html")
        if p.is_dir():
            p = safe(str(p.relative_to(root)) + "/index.html")
        import mimetypes

        if p.stat().st_size > 5 * 1024 * 1024:
            raise ValueError("File too large")
        return Response(
            p.read_bytes(),
            media_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream",
        )
    except Exception:
        raise HTTPException(404, "Preview file not found")


SKIP_DIRS = {
    "node_modules",
    ".git",
    ".venv",
    "__pycache__",
    ".npm",
    ".cache",
    ".next",
    "target",
    ".data",
}


def workspace_files():
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in SKIP_DIRS
            and not pathlib.Path(directory, d).is_symlink()
            and str(pathlib.Path(directory, d).relative_to(root))
            != ".config/go/telemetry"
        )
        for name in sorted(files):
            p = pathlib.Path(directory, name)
            if p.is_file() and not p.is_symlink():
                yield p


@app.post("/session")
async def session_state(req: Request):
    global context, page, initial_storage, frame_cache, frame_page, frame_cdp, frame_ts, frame_url
    b = await req.json()
    async with lock:
        if "restore" in b:
            initial_storage = b["restore"]
            if context:
                await context.close()
            device_sessions.clear()
            device_applied.clear()
            context = None
            page = None
            frame_cache = b""
            frame_page = None
            frame_cdp = None
            frame_ts = 0
            frame_url = ""
            # Recreate a context even if the browser process is already warm.
            if browser:
                context = await new_browser_context()
            return {"ok": True}
        if not context:
            return initial_storage or {"cookies": [], "origins": []}
        return await context.storage_state(indexed_db=True)


async def payment_guard(p, kind, args, token=None):
    """One-use approval bound to live URL, target and visible checkout evidence."""
    if kind == "text" or (
        kind == "key"
        and str(args.get("key", "")).lower() not in ("enter", "return", "space")
    ):
        return None
    # Read the target and its form atomically. A :focus Locator can wait for an
    # input that a reactive website replaces between count() and evaluate().
    try:
        if hasattr(p, "evaluate"):
            evidence = await asyncio.wait_for(
                p.evaluate(
                    """a => {
    let e;
    if(a.kind==='click')e=document.querySelector('[data-aster-ref="'+Number(a.args.ref)+'"]');
    else if(a.kind==='pointer')e=document.elementFromPoint(a.args.x,a.args.y)?.closest('button,a,input,[role=button]');
    else {e=document.activeElement;while(e?.shadowRoot?.activeElement)e=e.shadowRoot.activeElement;}
    return {label:e?.innerText||e?.getAttribute('aria-label')||e?.value||'',form:e?.closest('form')?.innerText||''};
   }""",
                    {"kind": kind, "args": args},
                ),
                2,
            )
        else:
            evidence = {
                "label": getattr(p, "label", ""),
                "form": getattr(p, "form", ""),
            }
    except Exception:
        raise HTTPException(
            409,
            "The page changed before the action. Observe the current page and retry only if the action is still needed.",
        )
    label = evidence.get("label", "")[:500]
    form = evidence.get("form", "")[:4000]
    commit = bool(
        re.search(
            r"\b(pay( now| securely)?|place (my |your )?order|buy now|confirm (purchase|payment|order|booking)|complete (purchase|payment|order|booking)|submit (payment|order)|purchase|subscribe|donate|book now)\b",
            label,
            re.I,
        )
    )
    keyboard = kind == "key" and str(args.get("key", "")).lower() in (
        "enter",
        "return",
        "space",
    )
    if keyboard and re.search(
        r"payment|card number|order total|checkout", form + " " + p.url, re.I
    ):
        commit = True
    if not commit:
        return None
    evidence_key = hashlib.sha256(
        json.dumps([p.url, kind, args, label, form], sort_keys=True).encode()
    ).hexdigest()
    saved = payment_challenges.pop(token, None) if token else None
    if saved and saved[0] == evidence_key and saved[1] > time.time():
        return None
    challenge = secrets.token_urlsafe(32)
    payment_challenges.clear()
    payment_challenges[challenge] = (evidence_key, time.time() + 300)
    return {
        "approval_required": True,
        "approval_token": challenge,
        "confirmation_reason": f'Confirm the final action on {p.url}: {label or "submit checkout"}. Review the displayed merchant, amount and currency before approving.',
        "url": p.url,
    }


services = {}
service_gate = asyncio.Lock()
preview_port = None


def process_env():
    return {
        **os.environ,
        "HOME": str(root),
        "TMPDIR": "/tmp",
        "npm_config_cache": str(root / ".npm"),
        "PIP_CACHE_DIR": str(root / ".cache/pip"),
        "GOPATH": str(root / ".cache/go"),
        "CARGO_HOME": str(root / ".cache/cargo"),
    }


async def stop_service(item):
    proc = item["process"]
    if proc.returncode is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), 12)
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()


async def drain_service(proc, item):
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        item["log"] = (item["log"] + chunk.decode(errors="replace"))[-48000:]


def service_rows():
    return [
        {
            "name": n,
            "command": v["command"],
            "port": v["port"],
            "status": "running" if v["process"].returncode is None else "stopped",
            "exit_code": v["process"].returncode,
            "output": v["log"],
        }
        for n, v in services.items()
    ]


@app.post("/services")
async def manage_services(req: Request):
    b = await req.json()
    op = b.get("op", "list")
    name = str(b.get("name", "app"))
    async with service_gate:
        if op in ("stop", "stop_all"):
            await checkpoint_databases()
            for n, v in list(services.items()):
                if op == "stop_all" or n == name:
                    await stop_service(v)
        elif op == "start":
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", name):
                raise HTTPException(400, "Invalid service name")
            command = b.get("command", "")
            port = int(b.get("port", 3000))
            if (
                not isinstance(command, str)
                or not command.strip()
                or len(command) > 12000
            ):
                raise HTTPException(400, "Invalid command")
            if not 1024 <= port <= 65535 or port == 8001:
                raise HTTPException(400, "Use a port from 1024–65535, excluding 8001")
            if name in services and services[name]["process"].returncode is None:
                raise HTTPException(409, "Stop this service before restarting it")
            if sum(v["process"].returncode is None for v in services.values()) >= 5:
                raise HTTPException(409, "Up to five services may run at once")
            proc = await asyncio.create_subprocess_exec(
                "/bin/bash",
                "-c",
                command,
                cwd=root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                env=process_env(),
            )
            item = {"process": proc, "command": command, "port": port, "log": ""}
            services[name] = item
            item["reader"] = asyncio.create_task(drain_service(proc, item))
            await asyncio.sleep(0.1)
        elif op != "list":
            raise HTTPException(400, "Unknown service operation")
        return {"services": service_rows()}


def app_path(value="/"):
    from urllib.parse import urlsplit

    value = str(value or "/")
    parts = urlsplit(value)
    if (
        len(value) > 4096
        or not value.startswith("/")
        or value.startswith("//")
        or parts.scheme
        or parts.netloc
        or "\\" in value
        or any(ord(c) < 32 for c in value)
    ):
        raise HTTPException(400, "Use a path inside the app, such as / or /index.php")
    return value


async def dev_input(p, kind, a):
    global display_profile
    if kind == "pointer":
        if a.get("touch") and display_profile.get("mobile"):
            session = device_sessions[p]
            point = {"x": float(a["x"]), "y": float(a["y"])}
            await session.send(
                "Input.dispatchTouchEvent",
                {"type": "touchStart", "touchPoints": [point]},
            )
            await session.send(
                "Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}
            )
        else:
            await p.mouse.click(
                float(a["x"]),
                float(a["y"]),
                click_count=min(2, max(1, int(a.get("count", 1)))),
            )
    elif kind == "move":
        await p.mouse.move(float(a["x"]), float(a["y"]))
    elif kind == "down":
        await p.mouse.move(float(a["x"]), float(a["y"]))
        await p.mouse.down(
            button="left", click_count=min(2, max(1, int(a.get("count", 1))))
        )
    elif kind == "up":
        await p.mouse.move(float(a["x"]), float(a["y"]))
        await p.mouse.up(
            button="left", click_count=min(2, max(1, int(a.get("count", 1))))
        )
    elif kind == "text":
        await p.keyboard.insert_text(str(a.get("text", ""))[:12000])
    elif kind == "key":
        await p.keyboard.press(str(a["key"])[:80])
    elif kind == "scroll":
        if "atX" in a and "atY" in a:
            await p.mouse.move(float(a["atX"]), float(a["atY"]))
        await p.mouse.wheel(
            max(-2400, min(2400, float(a.get("x", 0)))),
            max(-2400, min(2400, float(a.get("delta", 650)))),
        )
    elif kind == "resize":
        validate_browser_display(a)
        target = {**display_profile, **a}
        await apply_display(p, target)
        display_profile = target
        if target.get("mobile"):
            # The client keyboard reduces the remote viewport. Keep the actual focused
            # field visible without reading or transmitting its value.
            await p.evaluate(
                """() => {const e=document.activeElement;if(e && e!==document.body && (e.matches('input,textarea,[contenteditable=true]'))) e.scrollIntoView({block:'nearest',inline:'nearest'});} """
            )
    else:
        raise HTTPException(400, "Unsupported preview input")


@app.post("/dev-action")
async def dev_action(req: Request):
    global preview_port
    b = await req.json()
    kind = b.get("kind")
    a = b.get("args", {})
    async with lock:
        if kind == "open":
            port = int(a.get("port", 3000))
            path = app_path(a.get("path", "/"))
            if port == 8001 or not 1024 <= port <= 65535:
                raise HTTPException(400, "Invalid app port")
            p = await getpage()
            if "display" in a:
                await dev_input(p, "resize", a["display"])
            deadline = time.monotonic() + 20
            while True:
                try:
                    response = await p.goto(
                        f"http://127.0.0.1:{port}" + path,
                        wait_until="domcontentloaded",
                        timeout=12000,
                    )
                    if response and response.status >= 400:
                        raise HTTPException(
                            422,
                            f"App returned HTTP {response.status} at {path}. Check the service working directory/document root and actual entry path, fix it, then test_app again. The preview is not verified.",
                        )
                    preview_port = port
                    await refresh_frame(p, True)
                    return {
                        "ok": True,
                        "url": p.url,
                        "path": path,
                        "http_status": response.status if response else None,
                        "title": await p.title(),
                        "text": (await p.locator("body").inner_text(timeout=3000))[
                            :6000
                        ],
                    }
                except HTTPException:
                    raise
                except Exception:
                    if time.monotonic() >= deadline:
                        raise HTTPException(
                            503,
                            "App did not load on this port. Inspect service logs and confirm its start command and entry path.",
                        )
                    await asyncio.sleep(0.3)
        if kind == "resize":
            p = await getpage()
            await dev_input(p, kind, a)
            return {"ok": True, "url": p.url}
        if preview_port is None:
            raise HTTPException(409, "Open a running app first")
        p = await getpage()
        if kind == "input":
            events = a.get("events", [])
            if not isinstance(events, list) or len(events) > 80:
                raise HTTPException(400, "Invalid preview input batch")
            for event in events:
                await dev_input(p, event.get("kind"), event.get("args", {}))
        elif kind == "reload":
            await p.reload(wait_until="domcontentloaded", timeout=20000)
        elif kind == "back":
            await p.go_back(wait_until="domcontentloaded", timeout=15000)
        elif kind == "forward":
            await p.go_forward(wait_until="domcontentloaded", timeout=15000)
        elif kind == "selection":
            return {
                "text": await p.evaluate(
                    "() => {const e=document.activeElement;if(e?.type==='password')return '';return typeof e?.selectionStart==='number'?e.value.slice(e.selectionStart,e.selectionEnd):window.getSelection()?.toString()||''}"
                )
            }
        else:
            await dev_input(p, kind, a)
        return {"ok": True, "url": p.url}


@app.get("/dev-frame")
async def dev_frame():
    if preview_port is None:
        raise HTTPException(409, "Open a running service first")
    return await frame_jpg()


@app.get("/archive")
async def archive():
    await checkpoint_databases()
    return Response(project_zip(), media_type="application/zip")


def is_sqlite(path):
    try:
        with path.open("rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def project_zip():
    # SQLite's backup API produces one consistent database, including committed WAL data.
    buf = io.BytesIO()
    total = 0
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in workspace_files():
            if p.is_relative_to(root / ".aster/attachments"):
                continue
            if p.name.endswith(("-wal", "-shm", "-journal")) and is_sqlite(
                p.with_name(p.name.rsplit("-", 1)[0])
            ):
                continue
            count += 1
            total += p.stat().st_size
            if count > 10000 or total > 128 * 1024 * 1024:
                raise HTTPException(
                    413, "Project checkpoint exceeds 128 MB / 10,000 files"
                )
            if is_sqlite(p):
                started = time.monotonic()

                def progress(*args):
                    if time.monotonic() - started > 8:
                        raise ValueError(
                            "SQLite checkpoint busy; retry after current database writes finish"
                        )

                with tempfile.TemporaryDirectory(prefix="aster-sqlite-") as folder:
                    temp = pathlib.Path(folder) / "db"
                    with sqlite3.connect(
                        p.as_uri() + "?mode=ro", uri=True, timeout=2
                    ) as source, sqlite3.connect(temp) as target:
                        source.backup(target, pages=128, progress=progress, sleep=0.05)
                    total += max(0, temp.stat().st_size - p.stat().st_size)
                    if total > 128 * 1024 * 1024:
                        raise HTTPException(413, "Project checkpoint exceeds 128 MB")
                    z.write(temp, str(p.relative_to(root)))
            else:
                z.write(p, str(p.relative_to(root)))
    return buf.getvalue()


db_dump_lock = asyncio.Lock()


async def checkpoint_databases():
    async with db_dump_lock:
        await _checkpoint_databases()


async def database_available(port):
    """Probe only databases in this sandbox's own network namespace."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), 0.2
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


async def _checkpoint_databases():
    """Logical dumps of standard local development DBs; refuse to silently lose data."""
    folder = root / ".aster"
    folder.mkdir(exist_ok=True)
    for port, command, file in [
        (
            27017,
            [
                "mongodump",
                "--host",
                "127.0.0.1",
                "--port",
                "27017",
                "--archive",
                "--gzip",
            ],
            "mongodb.archive.gz",
        ),
        (
            5432,
            ["pg_dumpall", "--no-password", "-h", "127.0.0.1", "-U", "agent"],
            "postgres.sql",
        ),
        (
            6379,
            ["redis-cli", "-h", "127.0.0.1", "--rdb", str(folder / "redis.rdb.tmp")],
            "redis.rdb",
        ),
    ]:
        if not await database_available(port):
            continue
        tmp = folder / (file + ".tmp")
        try:
            with tmp.open("wb") as output:
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=output if port != 6379 else asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                    env=process_env(),
                )
                try:
                    _, err = await asyncio.wait_for(proc.communicate(), 40)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    raise ValueError(
                        "Database export timed out; workspace was not discarded"
                    )
            if proc.returncode:
                raise ValueError(
                    "Database export failed; stop or configure the local database before checkpointing: "
                    + err.decode(errors="replace")[:200]
                )
            if tmp.stat().st_size > 100 * 1024 * 1024:
                raise ValueError(
                    "Database export exceeds 100 MB; export it manually before releasing the workspace"
                )
            tmp.replace(folder / file)
        except OSError as e:
            raise ValueError("Database checkpoint unavailable: " + str(e))


# One persistent PTY per isolated code workspace. HTTP transport retains ordered,
# cursor-based output across reconnects without granting any host shell access.
import pty, fcntl, termios, struct, subprocess, codecs

terminal_session = None
terminal_gate = asyncio.Lock()
TERMINAL_BUFFER = 256 * 1024


def terminal_size(fd, cols, rows):
    fcntl.ioctl(
        fd,
        termios.TIOCSWINSZ,
        struct.pack(
            "HHHH", max(5, min(120, int(rows))), max(20, min(300, int(cols))), 0, 0
        ),
    )


def terminal_drain(item):
    for _ in range(16):
        try:
            data = os.read(item["fd"], 16384)
        except BlockingIOError:
            break
        except OSError:
            asyncio.get_running_loop().remove_reader(item["fd"])
            break
        if not data:
            asyncio.get_running_loop().remove_reader(item["fd"])
            break
        text = item["decoder"].decode(data)
        item["buffer"] += text
        item["end"] += len(text)
        if len(item["buffer"]) > TERMINAL_BUFFER:
            item["buffer"] = item["buffer"][-TERMINAL_BUFFER:]


def terminal_close(item):
    if not item:
        return
    asyncio.get_running_loop().remove_reader(item["fd"])
    try:
        os.killpg(item["process"].pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    item["process"].wait(timeout=5)
    os.close(item["fd"])


@app.post("/terminal")
async def terminal(req: Request):
    global terminal_session
    b = await req.json()
    op = b.get("op", "read")
    if op not in ("open", "read", "input", "resize", "close"):
        raise HTTPException(400, "Unknown terminal operation")
    async with terminal_gate:
        item = terminal_session
        if op == "open" and (not item or item["process"].poll() is not None):
            terminal_close(item)
            master, slave = pty.openpty()
            terminal_size(slave, b.get("cols", 100), b.get("rows", 28))
            env = process_env()
            env.update(
                TERM="xterm-256color",
                COLORTERM="truecolor",
                PS1="\\[\\e[36m\\]aster\\[\\e[0m\\]:\\w\\$ ",
            )
            # setsid acquires the PTY as controlling terminal for job control and Ctrl+C.
            try:
                proc = subprocess.Popen(
                    [
                        "/usr/bin/setsid",
                        "--ctty",
                        "/bin/bash",
                        "--noprofile",
                        "--norc",
                        "-i",
                    ],
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                    cwd=root,
                    env=env,
                    close_fds=True,
                )
            except Exception:
                os.close(master)
                raise
            finally:
                os.close(slave)
            os.set_blocking(master, False)
            item = {
                "fd": master,
                "process": proc,
                "buffer": "",
                "end": 0,
                "decoder": codecs.getincrementaldecoder("utf-8")("replace"),
            }
            terminal_session = item
            asyncio.get_running_loop().add_reader(master, terminal_drain, item)
        if not item:
            raise HTTPException(410, "Terminal is closed. Open a new session.")
        if op == "close":
            terminal_close(item)
            terminal_session = None
            return {"closed": True}
        if op == "resize":
            terminal_size(item["fd"], b.get("cols", 100), b.get("rows", 28))
        if op == "input":
            data = b.get("data", "")
            if not isinstance(data, str) or len(data) > 16000:
                raise HTTPException(400, "Terminal input is too large")
            if item["process"].poll() is not None:
                raise HTTPException(410, "Shell exited. Open a new session.")
            raw = data.encode()
            offset = 0
            deadline = time.monotonic() + 3
            while offset < len(raw):
                try:
                    offset += os.write(item["fd"], raw[offset:])
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise HTTPException(429, "Terminal input buffer is full")
                    await asyncio.sleep(0.01)
        terminal_drain(item)
        start = item["end"] - len(item["buffer"])
        cursor = max(0, int(b.get("cursor", 0)))
        return {
            "output": item["buffer"][max(0, cursor - start) :],
            "cursor": item["end"],
            "truncated": cursor < start,
            "running": item["process"].poll() is None,
            "exit_code": item["process"].returncode,
        }
