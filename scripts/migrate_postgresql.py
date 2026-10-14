"""Offline, atomic one-time import. SQLite is used ONLY to read/back up legacy data.
Run with app services stopped and the original encryption key; never on a live writer.
"""

import argparse
import base64
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["ASTER_SKIP_DB_INIT"] = "1"
from app import core
from app.database import db
from psycopg import sql
from psycopg.types.json import Jsonb

TABLES = (
    "users",
    "sessions",
    "limits",
    "memory",
    "tasks",
    "events",
    "schedules",
    "previews",
    "ledger",
    "connector",
    "preferences",
    "credit_transactions",
    "usage_operations",
    "usage_adjustments",
    "runtime_meters",
    "personal_details",
    "schedule_settings",
    "scheduled_runs",
    "browser_profiles",
)
ENCRYPTED = {
    "memory": ["body"],
    "tasks": ["state"],
    "events": ["body"],
    "schedules": ["prompt"],
    "connector": ["secret"],
    "preferences": ["body"],
    "personal_details": ["body"],
    "schedule_settings": ["body"],
    "browser_profiles": ["body"],
}


def sqlite_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def tagged_value(value):
    """Lossless representation for SQLite columns with mixed storage classes."""
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(
            "Non-finite legacy database value; repair source before migrating"
        )
    if isinstance(value, bytes):
        kind, encoded = "blob", base64.b64encode(value).decode("ascii")
    elif isinstance(value, str):
        kind, encoded = "text", base64.b64encode(value.encode("utf-8")).decode("ascii")
    elif isinstance(value, int):
        kind, encoded = "integer", str(value)
    else:
        kind, encoded = "real", value.hex()
    return {"sqlite_type": kind, "value": encoded}


def extra_column_type(legacy, table, column):
    # Inspect actual storage classes: SQLite declarations do not enforce types.
    table, column = sqlite_identifier(table), sqlite_identifier(column)
    kinds = {
        r[0] for r in legacy.execute(f"SELECT DISTINCT typeof({column}) FROM {table}")
    } - {"null"}
    if kinds == {"integer"}:
        return "bigint"
    if kinds == {"real"}:
        return "double precision"
    if kinds == {"blob"}:
        return "bytea"
    if kinds == {"text"}:
        if not legacy.execute(
            f"SELECT 1 FROM {table} WHERE instr({column},char(0))>0 LIMIT 1"
        ).fetchone():
            return "text"
    # Mixed types, NUL text and all-NULL columns have no safe native scalar type.
    return "jsonb"


def normalized_row(row, cols, target_columns):
    values = list(row)
    for i, col in enumerate(cols):
        if target_columns[col] == "double precision" and values[i] is not None:
            values[i] = float(values[i])
        elif target_columns[col] == "jsonb":
            values[i] = tagged_value(values[i])
    return values


class Fingerprint:
    """Order-independent multiset checksum with bounded memory; counts also checked."""

    def __init__(self):
        self.count = self.total = self.xor = 0

    def add(self, row):
        for value in row:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(
                    "Non-finite legacy database value; repair source before migrating"
                )
        encoded = json.dumps(
            list(row),
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
            sort_keys=True,
            default=tagged_value,
        ).encode()
        number = int.from_bytes(hashlib.sha256(encoded).digest(), "big")
        self.total = (self.total + number) % (1 << 256)
        self.xor ^= number
        self.count += 1

    def result(self):
        return {
            "rows": self.count,
            "sum": f"{self.total:064x}",
            "xor": f"{self.xor:064x}",
        }


def migrate(source, backup_dir):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError("Legacy database does not exist")
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    backup = backup_dir / (
        "pre-postgresql-"
        + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        + "-"
        + os.urandom(4).hex()
        + ".db"
    )
    # SQLite backup includes committed WAL pages. Source is never opened for writes.
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    with closing(
        sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=30)
    ) as legacy:
        with closing(sqlite3.connect(backup)) as target:
            legacy.backup(target)
    os.chmod(backup, 0o600)
    # Inspect before schema initialization, which includes historical credit grants.
    # A populated unrelated target must remain completely untouched.
    with db() as c:
        c.begin_write()
        existing = {
            r[0]
            for r in c.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )
        }
        modern = {
            "skills",
            "skill_versions",
            "skill_resources",
            "skill_search",
            "work_notes",
            "work_note_chunks",
            "admin_settings",
            "account_settings",
            "admin_audit",
            "credit_notes",
            "documents",
            "document_parts",
            "document_chunks",
            "task_documents",
            "account_policy_provenance",
            "support_tickets",
            "support_messages",
            "support_files",
            "knowledge_articles",
            "knowledge_versions",
            "knowledge_chunks",
            "knowledge_queries",
            "knowledge_feedback",
        }
        modern.update(
            {
                "integration_settings",
                "email_outbox",
                "registration_challenges",
                "password_resets",
                "user_profiles",
                "credit_topups",
                "stripe_events",
            }
        )
        if existing - set(TABLES) - {"aster_database_migrations"} - modern:
            raise ValueError(
                "PostgreSQL destination has unrecognized tables; refusing to modify it"
            )
        migrated = False
        if "aster_database_migrations" in existing:
            migrated = bool(
                c.execute(
                    "SELECT 1 FROM aster_database_migrations WHERE name='sqlite-to-postgresql-v1'"
                ).fetchone()
            )
        if not migrated:
            for table in existing.intersection(set(TABLES) | modern):
                if c.execute(
                    sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(table))
                ).fetchone():
                    raise ValueError(
                        "PostgreSQL destination is not empty; refusing to merge or overwrite "
                        + table
                    )
        c.rollback()
    core.init()
    with closing(
        sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True)
    ) as legacy, db() as c:
        if legacy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Legacy integrity check failed")
        if legacy.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Legacy foreign-key check failed; no data imported")
        tables = {
            r[0]
            for r in legacy.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if tables - set(TABLES):
            raise ValueError(
                "Unrecognized legacy tables; refusing to omit data: "
                + ", ".join(sorted(tables - set(TABLES)))
            )
        if not {"users", "tasks"}.issubset(tables):
            raise ValueError("Not an OwnCMD database")
        c.begin_write()
        c.execute("SET LOCAL idle_in_transaction_session_timeout=0")
        c.execute("SET LOCAL statement_timeout=0")
        c.execute(
            "CREATE TABLE IF NOT EXISTS aster_database_migrations(name TEXT PRIMARY KEY,source_digest TEXT NOT NULL,report TEXT NOT NULL,created DOUBLE PRECISION NOT NULL)"
        )
        prior = c.execute(
            "SELECT source_digest,report FROM aster_database_migrations WHERE name='sqlite-to-postgresql-v1'"
        ).fetchone()
        prior_report = json.loads(prior["report"]) if prior else {}
        columns = {}
        column_types = {}
        report = {}
        for table in TABLES:
            if table not in tables:
                continue
            info = list(legacy.execute('PRAGMA table_xinfo("' + table + '")'))
            cols = [r[1] for r in info if r[6] != 1]
            target_columns = {
                r[0]: r[1]
                for r in c.execute(
                    "SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='public' AND table_name=%s",
                    (table,),
                )
            }
            extras = set(cols) - set(target_columns)
            for col in sorted(extras):
                if len(col.encode("utf-8")) > 63:
                    raise ValueError(
                        "Legacy column name exceeds PostgreSQL identifier limit: "
                        + table
                        + "."
                        + col
                    )
                kind = extra_column_type(legacy, table, col)
                # Optional extension columns retain old data without making new
                # application inserts depend on an obsolete schema's constraints.
                c.execute(
                    sql.SQL("ALTER TABLE {} ADD COLUMN {} {}").format(
                        sql.Identifier(table), sql.Identifier(col), sql.SQL(kind)
                    )
                )
                target_columns[col] = kind
            extras.update(prior_report.get(table, {}).get("legacy_columns", {}))
            columns[table] = cols
            column_types[table] = target_columns
            fp = Fingerprint()
            for row in legacy.execute(
                "SELECT "
                + ",".join(map(sqlite_identifier, cols))
                + ' FROM "'
                + table
                + '"'
            ):
                values = normalized_row(row, cols, target_columns)
                for i, col in enumerate(cols):
                    if col in ENCRYPTED.get(table, []) and values[i]:
                        core.dec(values[i])
                fp.add(values)
            report[table] = fp.result()
            if extras:
                report[table]["legacy_columns"] = {
                    r[1]: {
                        "declaration": list(r[2:]),
                        "postgresql_type": target_columns[r[1]],
                    }
                    for r in info
                    if r[1] in extras
                }
                report[table]["legacy_schema"] = legacy.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()[0]
        digest = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
        if prior:
            if prior["source_digest"] != digest:
                raise ValueError(
                    "This PostgreSQL database was migrated from different data; refusing a second import"
                )
            c.rollback()
            return {
                "status": "already_migrated",
                "tables": json.loads(prior["report"]),
                "backup": str(backup),
            }
        for table in TABLES:
            if c.execute(
                sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(table))
            ).fetchone():
                raise ValueError(
                    "PostgreSQL destination is not empty; refusing to merge or overwrite "
                    + table
                )
        # Import existing welcome/usage entries exactly, without signup side effects.
        c.execute("ALTER TABLE users DISABLE TRIGGER welcome_credit")
        for table, cols in columns.items():
            prefix = sql.SQL("INSERT INTO {} ({}) VALUES ").format(
                sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, cols))
            )
            row_sql = (
                sql.SQL("(")
                + sql.SQL(",").join([sql.Placeholder()] * len(cols))
                + sql.SQL(")")
            )
            batch = []
            batch_bytes = 0

            def flush():
                if batch:
                    c.raw.execute(
                        prefix + sql.SQL(",").join([row_sql] * len(batch)),
                        [value for row in batch for value in row],
                    )

            for row in legacy.execute(
                "SELECT "
                + ",".join(map(sqlite_identifier, cols))
                + ' FROM "'
                + table
                + '"'
            ):
                values = normalized_row(row, cols, column_types[table])
                batch.append(
                    [
                        (
                            Jsonb(v)
                            if column_types[table][col] == "jsonb" and v is not None
                            else v
                        )
                        for col, v in zip(cols, values)
                    ]
                )
                batch_bytes += sum(
                    len(v) if isinstance(v, (str, bytes)) else 16 for v in row
                )
                if len(batch) >= 100 or batch_bytes >= 4 * 1024 * 1024:
                    flush()
                    batch = []
                    batch_bytes = 0
            flush()
            fp = Fingerprint()
            # Named server cursor streams verification without loading full histories.
            with c.raw.cursor(
                name="verify_" + table, row_factory=__import__("psycopg").rows.tuple_row
            ) as cursor:
                cursor.execute(
                    sql.SQL("SELECT {} FROM {}").format(
                        sql.SQL(",").join(map(sql.Identifier, cols)),
                        sql.Identifier(table),
                    )
                )
                for row in cursor:
                    fp.add(row)
            if any(report[table][key] != value for key, value in fp.result().items()):
                raise ValueError("Post-copy verification failed: " + table)
        c.execute("ALTER TABLE users ENABLE TRIGGER welcome_credit")
        # Reset the identity after explicit legacy IDs; never reuse deleted event IDs.
        seq = (
            legacy.execute(
                "SELECT seq FROM sqlite_sequence WHERE name='events'"
            ).fetchone()
            if "sqlite_sequence"
            in {r[0] for r in legacy.execute("SELECT name FROM sqlite_master")}
            else None
        )
        high = max(
            int(seq[0]) if seq else 0,
            c.execute("SELECT coalesce(max(id),0) FROM events").fetchone()[0],
        )
        c.execute(
            "SELECT setval(pg_get_serial_sequence('events','id'),%s,%s)",
            (max(1, high), high > 0),
        )
        c.execute(
            "INSERT INTO aster_database_migrations VALUES(%s,%s,%s,%s)",
            (
                "sqlite-to-postgresql-v1",
                digest,
                json.dumps(report, sort_keys=True),
                time.time(),
            ),
        )
        c.commit()
    return {"status": "migrated", "tables": report, "backup": str(backup)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--services-stopped", action="store_true", required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.source, args.backup_dir), indent=2))
