"""Called only by the installer after every application writer has stopped."""

import json
import os
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from migrate_postgresql import migrate
from app import core

source = core.DATA / "aster.db"
if source.exists():
    result = migrate(source, core.DATA / "backups")
    report = core.DATA / "backups" / "postgresql-migration-report.json"
    report.write_text(json.dumps(result, indent=2) + "\n")
    report.chmod(0o600)
    for path in (core.DATA / "backups", Path(result["backup"]), report):
        shutil.chown(path, user="aster", group="aster")
    print(
        "PostgreSQL migration verified:",
        sum(t["rows"] for t in result["tables"].values()),
        "rows across",
        len(result["tables"]),
        "tables.",
    )
    extra_count = sum(
        len(t.get("legacy_columns", {})) for t in result["tables"].values()
    )
    if extra_count:
        print("Additional legacy columns preserved and verified:", extra_count)
else:
    core.init()
    print("PostgreSQL schema ready.")
# Written before returning to shell so a restart cannot re-enable stale data.
Path("/etc/aster/postgresql-cutover").touch(mode=0o600)
