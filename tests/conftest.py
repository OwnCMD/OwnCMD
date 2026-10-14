import os, tempfile
from cryptography.fernet import Fernet

os.environ["ASTER_DATA"] = tempfile.mkdtemp(prefix="aster-test-")
os.environ["ASTER_MASTER_KEY"] = Fernet.generate_key().decode()
os.environ["ASTER_ORIGIN"] = "https://testserver"
os.environ["ASTER_BROKER_KEY"] = "test-broker"
os.environ["OWNCMD_SETUP_TOKEN"] = "test-setup-token"
os.environ["ASTER_TASK_BUDGET"] = "1"
os.environ["ASTER_DAILY_BUDGET"] = "5"
os.environ["OPENROUTER_API_KEY"] = "test-key"
os.environ["EXA_API_KEY"] = "test-key"
import pytest
from urllib.parse import urlsplit

url = os.environ.get("ASTER_TEST_DATABASE_URL", "")
if not url or not urlsplit(url).path.rsplit("/", 1)[-1].startswith("aster_test"):
    raise RuntimeError(
        "Run scripts/test_postgresql.sh or set ASTER_TEST_DATABASE_URL to a dedicated aster_test* PostgreSQL database; tests never use the application URL"
    )
os.environ["ASTER_DATABASE_URL"] = url
os.environ.pop("ASTER_SKIP_DB_INIT", None)
from fastapi.testclient import TestClient
from app.main import app
from app import core


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    import asyncio
    from app import documents

    async def quiet_queue():
        await asyncio.Event().wait()

    monkeypatch.setattr(documents, "queue_loop", quiet_queue)
    from app import temporary

    with temporary.LOCK:
        temporary.ROWS.clear()
    with core.db() as c:
        tables = [
            r[0]
            for r in c.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )
        ]
        from psycopg import sql

        if tables:
            c.execute(
                sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(",").join(map(sql.Identifier, tables))
                )
            )
    yield


@pytest.fixture
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def login(c, email="a@example.com"):
    h = {"Origin": "https://testserver"}
    # Authentication fixture represents an existing verified account. Public
    # registration and email challenges have their own end-to-end tests.
    import time

    with core.db() as db:
        db.execute(
            "INSERT INTO users VALUES(%s,%s,%s,%s)",
            (core.ident(), email, core.PH.hash("test-password-123"), time.time()),
        )
    r = c.post(
        "/api/login", headers=h, json={"email": email, "password": "test-password-123"}
    )
    assert r.status_code == 200
    return {**h, "X-CSRF": r.json()["csrf"]}
