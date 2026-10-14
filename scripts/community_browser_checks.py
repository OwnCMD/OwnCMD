"""Run against the isolated community_browser_server fixture, never production.

Set OWNCMD_BROWSER_BINARY to use an existing Chromium binary, or install
Playwright Chromium. Starts no external provider requests.
"""

import os
from playwright.sync_api import sync_playwright, expect

BASE = "http://127.0.0.1:8765"


def run():
    errors = []
    with sync_playwright() as p:
        options = {
            "headless": True,
            "args": ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        }
        if os.getenv("OWNCMD_BROWSER_BINARY"):
            options["executable_path"] = os.environ["OWNCMD_BROWSER_BINARY"]
        browser = p.chromium.launch(**options)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE)
        expect(page.get_by_role("heading", name="Set up your instance")).to_be_visible()
        page.get_by_label("Setup token").fill("browser-test-token")
        page.get_by_label("Display name").fill("Example Owner")
        page.get_by_label("Email (login identifier)").fill("owner@example.com")
        page.get_by_label("Password", exact=True).fill("browser-test-password")
        page.get_by_label("Confirm password").fill("browser-test-password")
        page.get_by_role("button", name="Create account", exact=True).click()
        expect(page.get_by_role("link", name="Instance settings")).to_be_visible()
        page.get_by_role("link", name="Instance settings").click()
        expect(page.get_by_role("heading", name="Provider keys")).to_be_visible()
        page.locator("input[name=openrouter_key]").fill("test-provider-key")
        page.get_by_role("button", name="Save provider keys").click()
        expect(page.get_by_role("status")).to_contain_text("Saved successfully")
        page.reload()
        expect(page.get_by_text("OpenRouter · Configured", exact=True)).to_be_visible()
        page.get_by_role("button", name="Members", exact=True).click()
        page.get_by_label("Invite a member").fill("member@example.com")
        page.get_by_role("button", name="Create invitation link").click()
        expect(page.get_by_label("Invitation link")).to_be_visible()
        link = page.get_by_label("Invitation link").input_value()
        mobile = browser.new_page(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        mobile.on("pageerror", lambda e: errors.append(str(e)))
        mobile.goto(link)
        expect(
            mobile.get_by_role("heading", name="Join your workspace")
        ).to_be_visible()
        mobile.get_by_label("Display name").fill("Example Member")
        mobile.get_by_label("Email (login identifier)").fill("member@example.com")
        mobile.get_by_label("Password", exact=True).fill("browser-member-password")
        mobile.get_by_label("Confirm password").fill("browser-member-password")
        mobile.get_by_role("button", name="Create account", exact=True).click()
        expect(mobile.locator("#prompt")).to_be_visible()
        assert not mobile.get_by_role("link", name="Instance settings").count()
        mobile.goto(BASE + "/#usage")
        expect(mobile.get_by_role("heading", name="Usage", exact=True)).to_be_visible()
        expect(mobile.get_by_text("Provider cost", exact=True)).to_be_visible()
        assert mobile.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        page.goto(BASE + "/#usage")
        expect(page.get_by_role("heading", name="Usage", exact=True)).to_be_visible()
        page.get_by_label("Date range").select_option("7")
        expect(page.get_by_text("0 operations", exact=True)).to_be_visible()
        # CSP hydration and client behavior must be clean on both viewport sizes.
        assert not errors, errors
        if os.getenv("OWNCMD_BROWSER_SCREENSHOT"):
            page.screenshot(
                path=os.environ["OWNCMD_BROWSER_SCREENSHOT"], full_page=True
            )
        browser.close()
    print(
        "PASS: owner setup, HTTP login, provider persistence, invitation signup, member restrictions, mobile layout, usage filters; no page errors"
    )


if __name__ == "__main__":
    run()
