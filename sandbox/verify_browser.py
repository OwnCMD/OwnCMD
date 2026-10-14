"""Installer gate: real browser startup under production read-only mounts."""

import asyncio
import server


async def verify():
    try:
        server.display_profile = {"width": 390, "height": 600, "mobile": True}
        page = await server.getpage()
        await page.set_content(
            '<meta name="viewport" content="width=device-width,initial-scale=1"><button onclick="this.textContent=\'Tapped\'">Tap</button>'
        )
        assert await page.evaluate("innerWidth") == 390
        assert await page.evaluate("navigator.maxTouchPoints") == 1
        assert "Mobile" in await page.evaluate("navigator.userAgent")
        await page.locator("button").tap()
        assert await page.locator("button").inner_text() == "Tapped"
        assert (await page.screenshot(type="jpeg"))[:2] == b"\xff\xd8"
        await server.apply_display(
            page, {"width": 1152, "height": 720, "mobile": False}
        )
        assert await page.evaluate("innerWidth") == 1152
        assert "Mobile" not in await page.evaluate("navigator.userAgent")
        print("READ_ONLY_BROWSER_MOBILE_DESKTOP_OK", flush=True)
    finally:
        if server.browser:
            await server.browser.close()
        if server.playwright:
            await server.playwright.stop()


asyncio.run(verify())
