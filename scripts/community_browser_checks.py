"""Run Community browser checks against a disposable PostgreSQL database.

Requires ASTER_DATABASE_URL ending in an aster_test* database name, ASTER_DATA,
ASTER_MASTER_KEY, ASTER_BROKER_KEY, ASTER_ORIGIN=http://127.0.0.1:8765 and
OWNCMD_SETUP_TOKEN=browser-test-token. Install requirements.lock and Playwright,
then install Chromium or set OWNCMD_BROWSER_BINARY. Rebuild the frontend first.
The companion server enforces the test-database boundary and fakes only the
model catalog. Provider requests are never submitted. Test users and costs are
created; never point this at a real instance. Output defaults to test-results/.
"""

import os
import sys
import subprocess
import time
import socket
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(
    os.environ.get("OWNCMD_BROWSER_OUTPUT", ROOT / "test-results" / "community")
)
# Refuse real databases and occupied ports before creating any accounts.
if (
    not urlsplit(os.environ.get("ASTER_DATABASE_URL", ""))
    .path.rsplit("/", 1)[-1]
    .startswith("aster_test")
):
    raise RuntimeError("Use a disposable aster_test* database")
with socket.socket() as probe:
    if probe.connect_ex(("127.0.0.1", 8765)) == 0:
        raise RuntimeError(
            "Port 8765 is occupied; stop the existing local fixture first"
        )
OUTPUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
server = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "uvicorn",
        "scripts.community_browser_server:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
    ],
    cwd=ROOT,
    stdout=open(OUTPUT / "server.log", "w"),
    stderr=subprocess.STDOUT,
)
try:
    for i in range(100):
        if server.poll() is not None:
            raise RuntimeError("Fixture server exited; inspect server.log")
        try:
            urlopen("http://127.0.0.1:8765/api/setup", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError("Server failed to start")
    from app import core, billing

    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(
            executable_path=os.environ.get("OWNCMD_BROWSER_BINARY"),
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-zygote",
                "--use-gl=angle",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
            ],
        )
        page = b.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:8765")
        page.get_by_label("Setup token").fill("browser-test-token")
        page.get_by_label("Display name").fill("Example Owner")
        page.get_by_label("Email (login identifier)").fill("owner@example.com")
        page.get_by_label("Password", exact=True).fill("browser-test-password")
        page.get_by_label("Confirm password").fill("browser-test-password")
        page.get_by_role("button", name="Create account", exact=True).click()
        page.get_by_role("link", name="Instance settings").click()
        expect(page.get_by_role("heading", name="Provider connections")).to_be_visible()
        page.get_by_label("OpenRouter API key").fill("test-openrouter-key")
        page.get_by_role("button", name="Save provider keys").click()
        expect(page.get_by_role("status")).to_contain_text("Provider keys saved")
        page.reload()
        expect(page.get_by_text("Configured", exact=True).first).to_be_visible()
        assert page.get_by_label("OpenRouter API key").input_value() == ""
        page.screenshot(path=OUTPUT / "providers-desktop.png", full_page=True)
        page.get_by_role("button", name="Members", exact=True).click()
        page.get_by_role("button", name="Invite member", exact=True).click()
        dlg = page.get_by_role("dialog", name="Invite a member")
        dlg.get_by_label("Email address").fill("member@example.com")
        dlg.get_by_role("button", name="Create invitation link").click()
        expect(dlg.get_by_label("Invitation link")).to_be_visible()
        link = dlg.get_by_label("Invitation link").input_value()
        dlg.get_by_role("button", name="Close dialog").click()
        mobile = b.new_page(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        mobile.on("pageerror", lambda e: errors.append(str(e)))
        mobile.goto(link)
        mobile.get_by_label("Display name").fill("Example Member")
        mobile.get_by_label("Email (login identifier)").fill("member@example.com")
        mobile.get_by_label("Password", exact=True).fill("browser-member-password")
        mobile.get_by_label("Confirm password").fill("browser-member-password")
        mobile.get_by_role("button", name="Create account", exact=True).click()
        expect(mobile.locator("#prompt")).to_be_visible()
        page.reload()
        page.get_by_role("button", name="Members", exact=True).click()
        page.get_by_role("button", name="Manage member@example.com", exact=True).click()
        manage = page.get_by_role("dialog", name="Manage member")
        expect(manage.get_by_text("Example Member", exact=True)).to_be_visible()
        manage.get_by_role("button", name="Models", exact=True).click()
        expect(manage.get_by_label("chat Auto default")).to_be_visible()
        assert manage.locator("textarea").count() == 0
        manage.get_by_label("Vision test model", exact=False).first.check()
        manage.get_by_label("chat Auto default").select_option("test/vision-model")
        manage.get_by_role("button", name="Save member policy", exact=True).click()
        expect(manage.get_by_role("status")).to_contain_text("Member policy saved")
        manage.get_by_label("Vision test model", exact=False).first.uncheck()
        manage.get_by_role("button", name="Account", exact=True).click()
        manage.get_by_role("button", name="Make Owner", exact=True).click()
        page.get_by_role("dialog", name="Change account role?").get_by_role(
            "button", name="Change role", exact=True
        ).click()
        expect(
            manage.get_by_role("button", name="Make Member", exact=True)
        ).to_be_visible()
        manage.get_by_role("button", name="Models", exact=True).click()
        expect(manage.get_by_label("chat Auto default")).to_have_value(
            "test/vision-model"
        )
        manage.get_by_role("button", name="Account", exact=True).click()
        manage.get_by_role("button", name="Make Member", exact=True).click()
        page.get_by_role("dialog", name="Change account role?").get_by_role(
            "button", name="Change role", exact=True
        ).click()
        expect(
            manage.get_by_role("button", name="Make Owner", exact=True)
        ).to_be_visible()
        page.screenshot(path=OUTPUT / "member-detail-desktop.png", full_page=True)
        manage.get_by_role("button", name="Account", exact=True).click()
        manage.get_by_role("button", name="Suspend account", exact=True).click()
        confirm = page.get_by_role("dialog", name="Suspend this account?")
        confirm.get_by_role("button", name="Cancel", exact=True).click()
        expect(manage.get_by_text("Active", exact=True)).to_be_visible()
        manage.get_by_role("button", name="Suspend account", exact=True).click()
        page.get_by_role("dialog", name="Suspend this account?").get_by_role(
            "button", name="Suspend account", exact=True
        ).click()
        expect(manage.get_by_text("Suspended", exact=True)).to_be_visible()
        manage.get_by_role("button", name="Restore access", exact=True).click()
        page.get_by_role("dialog", name="Restore this account?").get_by_role(
            "button", name="Restore access", exact=True
        ).click()
        expect(manage.get_by_text("Active", exact=True)).to_be_visible()
        manage.get_by_role("button", name="Close dialog").click()
        page.screenshot(path=OUTPUT / "members-desktop.png", full_page=True)
        page.get_by_role("button", name="Models", exact=True).click()
        expect(page.get_by_label("chat Auto default")).to_be_visible()
        page.get_by_label("Find chat models").fill("vision")
        page.get_by_label("Vision test model", exact=False).first.check()
        page.get_by_label("chat Auto default").select_option("test/vision-model")
        page.get_by_role("button", name="Save changes", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("Instance policy saved")
        page.reload()
        page.get_by_role("button", name="Models", exact=True).click()
        expect(page.get_by_label("chat Auto default")).to_have_value(
            "test/vision-model"
        )
        expect(
            page.get_by_text(
                "$1.00 / $2.00 per 1M input/output tokens", exact=False
            ).first
        ).to_be_visible()
        page.screenshot(path=OUTPUT / "models-desktop.png", full_page=True)
        with core.db() as c:
            owner = c.execute(
                "SELECT id FROM users WHERE email=%s", ("owner@example.com",)
            ).fetchone()[0]
        task = core.create_task(owner, "Provider cost acceptance", mode="chat")
        rid = billing.reserve(owner, task, 0.01, model="test/vision-model")
        billing.settle(rid, 0.125, {"prompt_tokens": 500, "completion_tokens": 125})
        rid2 = billing.reserve(owner, task, 0.01, service="title")
        billing.settle(rid2, 0.025)
        page.goto("http://127.0.0.1:8765/#usage")
        expect(page.get_by_role("heading", name="Usage", exact=True)).to_be_visible()
        expect(page.get_by_text("$0.15", exact=True).first).to_be_visible()
        assert page.get_by_text("Add credit", exact=False).count() == 0
        page.get_by_label("Usage period").select_option("custom")
        expect(page.get_by_text("Choose both dates", exact=False)).to_be_visible()
        today = time.strftime("%Y-%m-%d", time.gmtime())
        page.get_by_label("Usage start date").fill(today)
        page.get_by_label("Usage end date").fill(today)
        expect(page.get_by_text("$0.15", exact=True).first).to_be_visible()
        page.get_by_role("button", name="More filters").click()
        page.get_by_label("Usage model").select_option("test/vision-model")
        expect(page.get_by_text("$0.125", exact=True).first).to_be_visible()
        with page.expect_download() as download:
            page.get_by_role("link", name="Export filtered CSV").click()
        csv = Path(download.value.path()).read_text()
        assert "0.125" in csv and "Provider cost USD" in csv and ("0.025" not in csv)
        page.get_by_role("button", name="Activity", exact=True).click()
        expect(page.get_by_text("Provider cost acceptance", exact=True)).to_be_visible()
        page.get_by_label("Sort usage").select_option("highest")
        page.get_by_role("button", name="Provider rates", exact=True).click()
        expect(page.get_by_text("Provider-reported", exact=False)).to_be_visible()
        page.get_by_role("button", name="Overview", exact=True).click()
        page.get_by_role("button", name="Reset filters", exact=True).click()
        expect(page.get_by_text("$0.15", exact=True).first).to_be_visible()
        page.get_by_role("button", name="More filters", exact=True).click()
        page.screenshot(path=OUTPUT / "usage-desktop.png", full_page=True)
        for width in [390, 320, 768]:
            page.set_viewport_size({"width": width, "height": 900})
            page.goto("http://127.0.0.1:8765/#admin")
            expect(
                page.get_by_role("heading", name="Provider connections")
            ).to_be_visible()
            for tab in ["Providers", "Members", "Models", "Access & limits", "Network"]:
                page.get_by_role(
                    "navigation", name="Instance settings sections"
                ).get_by_role("button", name=tab, exact=True).click()
                page.wait_for_timeout(350)
                assert page.evaluate(
                    "document.documentElement.scrollWidth<=innerWidth"
                ), (width, tab, "page overflow")
                assert page.locator(".instance-page").evaluate(
                    "(e)=>e.scrollWidth<=e.clientWidth"
                ), (width, tab, "settings overflow")
            page.get_by_role("button", name="Members", exact=True).click()
            page.screenshot(path=OUTPUT / f"members-{width}.png", full_page=True)
            page.get_by_role(
                "button", name="Manage member@example.com", exact=True
            ).click()
            member_dialog = page.get_by_role("dialog", name="Manage member")
            expect(
                member_dialog.get_by_text("Example Member", exact=True)
            ).to_be_visible()
            assert member_dialog.evaluate("e=>e.scrollWidth<=e.clientWidth"), (
                width,
                "member dialog overflow",
            )
            assert member_dialog.locator(".member-detail-heading > div").evaluate(
                "e=>e.clientWidth>=120"
            ), (width, "member identity too narrow")
            page.screenshot(path=OUTPUT / f"member-dialog-{width}.png", full_page=True)
            member_dialog.get_by_role("button", name="Models", exact=True).click()
            expect(member_dialog.get_by_label("chat Auto default")).to_be_visible()
            assert member_dialog.locator(".member-detail").evaluate(
                "e=>e.scrollWidth<=e.clientWidth"
            ), (width, "member models overflow")
            member_dialog.get_by_role("button", name="Close dialog").click()
            page.goto("http://127.0.0.1:8765/#usage")
            expect(
                page.get_by_role("heading", name="Usage", exact=True)
            ).to_be_visible()
            page.get_by_role("button", name="More filters").click()
            page.get_by_label("Usage period").select_option("custom")
            page.get_by_label("Usage start date").fill(today)
            page.get_by_label("Usage end date").fill(today)
            page.wait_for_timeout(400)
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), (
                width,
                "usage overflow",
            )
            boxes = page.locator(".usage-advanced label").evaluate_all(
                "(els)=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})"
            )
            assert all(
                (
                    a["x"] + a["w"] <= b["x"] + 1
                    or b["x"] + b["w"] <= a["x"] + 1
                    or a["y"] + a["h"] <= b["y"] + 1
                    or (b["y"] + b["h"] <= a["y"] + 1)
                    for i, a in enumerate(boxes)
                    for b in boxes[i + 1 :]
                )
            ), (width, "overlapping filters")
            page.screenshot(path=OUTPUT / f"usage-{width}.png", full_page=True)
            page.get_by_role("button", name="More filters", exact=True).click()
            page.locator(".usage-page").screenshot(
                path=OUTPUT / f"usage-overview-{width}.png"
            )
            page.locator(".model-insights").scroll_into_view_if_needed()
            page.screenshot(path=OUTPUT / f"usage-charts-{width}.png", full_page=True)
        page.evaluate("document.documentElement.dataset.theme='dark'")
        page.screenshot(path=OUTPUT / "usage-dark.png", full_page=True)
        assert not errors, errors
        b.close()
        print(
            "PASS: real API browser flows, raw costs, custom dates, filters, CSV, member controls, model selection; widths 320/390/768/1440; no browser errors"
        )
finally:
    server.terminate()
    server.wait(timeout=10)
