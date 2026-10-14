"""Local-only browser fixture. Requires a disposable aster_test database.

Never loaded by production. Providers are not called; the normal app, session
cookies, CSRF, ownership, setup and instance-settings APIs are used unchanged.
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if (
    not urlsplit(os.environ.get("ASTER_DATABASE_URL", ""))
    .path.rsplit("/", 1)[-1]
    .startswith("aster_test")
):
    raise RuntimeError("Browser fixture requires an aster_test database")
from app import main, providers


async def catalog():
    return {
        providers.configured_model(mode): {
            "name": mode.title() + " model",
            "supported_parameters": ["tools"],
            "pricing": {"prompt": "0", "completion": "0"},
        }
        for mode in ("chat", "work")
    }


providers.catalog = catalog
app = main.app
