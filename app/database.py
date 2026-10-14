"""PostgreSQL-only storage. All SQL is native PostgreSQL, parameterized by psycopg.

Short mutation transactions share one advisory lock to preserve the application's
existing cross-table billing/task invariants. Readers remain concurrent through
MVCC. Do not hold a write transaction during network calls or acquire another
write connection inside one. Read reports use a repeatable snapshot.
"""

import contextlib
import os
import subprocess
import psycopg
from psycopg.pq import TransactionStatus

WRITE_LOCK = 0x4153544552


class Record(dict):
    """Named fields and positional access used by the existing application."""

    def __init__(self, names, values):
        self._values = tuple(values)
        super().__init__(zip(names, self._values))

    def __getitem__(self, key):
        return (
            self._values[key]
            if isinstance(key, (int, slice))
            else super().__getitem__(key)
        )


def row_factory(cursor):
    names = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: Record(names, values)


def database_url():
    value = os.environ.get("ASTER_DATABASE_URL", "")
    if not value.startswith(("postgresql://", "postgres://")):
        raise RuntimeError(
            "ASTER_DATABASE_URL must be a PostgreSQL URL; no file database fallback is supported"
        )
    return value


class Connection:
    def __init__(self, raw):
        self.raw = raw

    def begin_write(self):
        if self.raw.info.transaction_status != TransactionStatus.IDLE:
            raise RuntimeError("Nested write transaction is not supported")
        self.raw.execute("BEGIN")
        self.raw.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK,))

    def begin_read(self):
        self.raw.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")

    def execute(self, query, params=None):
        # Autocommit mutations participate in the same lock as multi-statement
        # transactions. SELECT is intentionally never locked.
        mutation = str(query).lstrip().split(None, 1)[0].upper() in {
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "ALTER",
            "DROP",
            "TRUNCATE",
        }
        if mutation and self.raw.info.transaction_status == TransactionStatus.IDLE:
            self.begin_write()
            try:
                result = self.raw.execute(query, params)
                self.raw.commit()
                return result
            except BaseException:
                with contextlib.suppress(Exception):
                    self.raw.rollback()
                raise
        return self.raw.execute(query, params)

    def execute_schema(self, query):
        return self.execute(query)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()


@contextlib.contextmanager
def db():
    # No inherited/fork-unsafe connection or unbounded per-process pool.
    raw = psycopg.connect(
        database_url(),
        autocommit=True,
        row_factory=row_factory,
        connect_timeout=10,
        prepare_threshold=None,
        application_name="aster",
        options="-c search_path=public -c lock_timeout=30000 -c statement_timeout=120000 -c idle_in_transaction_session_timeout=120000",
    )
    try:
        yield Connection(raw)
    except BaseException:
        # Preserve the original database error even if the connection was lost.
        with contextlib.suppress(Exception):
            raw.rollback()
        raise
    else:
        if raw.info.transaction_status != TransactionStatus.IDLE:
            raw.rollback()
    finally:
        raw.close()


def client_environment(url=None):
    """Translate all libpq URL options to environment variables without argv secrets."""
    values = psycopg.conninfo.conninfo_to_dict(url or database_url())
    env = os.environ.copy()
    for option in psycopg.pq.Conninfo.get_defaults():
        key = option.keyword.decode()
        if option.envvar and key in values:
            env[option.envvar.decode()] = values[key]
    return env


def dump_database(destination):
    # Keep the URL (which can contain a password) out of process arguments.
    env = client_environment()
    subprocess.run(
        [
            "pg_dump",
            "--no-password",
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--file",
            str(destination),
        ],
        env=env,
        stdin=subprocess.DEVNULL,
        check=True,
    )
    os.chmod(destination, 0o600)
