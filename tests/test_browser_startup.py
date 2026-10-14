import asyncio, os, shutil
import pytest
from test_sandbox import sandbox


@pytest.mark.parametrize("fails", [False, True])
def test_supported_headless_launch_uses_private_writable_paths(monkeypatch, fails):
    monkeypatch.setattr(sandbox, "browser_runtime_directory", None)

    class Driver:
        stopped = False
        options = None

        @property
        def chromium(self):
            return self

        async def launch(self, **options):
            self.options = options
            if fails:
                raise RuntimeError("launch failure")
            return self

        async def stop(self):
            self.stopped = True

        async def start(self):
            return self

    driver = Driver()
    monkeypatch.setattr(sandbox, "async_playwright", lambda: driver)
    try:
        if fails:
            with pytest.raises(RuntimeError):
                asyncio.run(sandbox.launch_browser())
            assert driver.stopped and sandbox.playwright is None
            assert sandbox.browser_runtime_directory is None
        else:
            assert asyncio.run(sandbox.launch_browser()) is driver
            assert "channel" not in driver.options and driver.options["headless"]
            for key in (
                "XDG_CONFIG_HOME",
                "CHROME_CONFIG_HOME",
                "XDG_CACHE_HOME",
                "XDG_DATA_HOME",
                "XDG_RUNTIME_DIR",
            ):
                path = driver.options["env"][key]
                assert path.startswith("/tmp/aster-browser-") and os.access(
                    path, os.W_OK
                )
                assert os.stat(path).st_mode & 0o777 == 0o700
    finally:
        if sandbox.browser_runtime_directory:
            shutil.rmtree(sandbox.browser_runtime_directory)
