"""Disposable test database only. Synthetic vectors measure SQL/policy, not semantics.
Run with ASTER_TEST_DATABASE_URL; no external API calls or real user data.
"""

import os, sys, time, json, random, statistics, resource, tempfile
from pathlib import Path
from cryptography.fernet import Fernet
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if (
    not urlsplit(os.getenv("ASTER_TEST_DATABASE_URL", ""))
    .path.rsplit("/", 1)[-1]
    .startswith("aster_test")
):
    raise SystemExit("Use a disposable aster_test* ASTER_TEST_DATABASE_URL")
os.environ.update(
    ASTER_DATABASE_URL=os.environ["ASTER_TEST_DATABASE_URL"],
    ASTER_DATA=tempfile.mkdtemp(),
    ASTER_MASTER_KEY=Fernet.generate_key().decode(),
    EXA_API_KEY="fixture",
)
from app import core, skills, skill_providers as provider

core.init()
rng = random.Random(71)
owners = [core.ident() for _ in range(3)]
dim = 1536
with core.db() as c:
    c.begin_write()
    for owner in owners:
        c.execute(
            "INSERT INTO users VALUES(%s,%s,%s,%s)",
            (owner, owner + "@benchmark.test", "unused", time.time()),
        )
        for i in range(1000):
            id = core.ident()
            vid = core.ident()
            v = [rng.uniform(-1, 1) for _ in range(dim)]
            meta = {
                "name": f"Research workflow {i}",
                "description": "Compare current public sources and report evidence",
                "tags": ["research"],
                "when_to_use": ["Research public information"],
                "when_not_to_use": ["private accounts"],
                "capabilities": [],
                "version": 1,
            }
            c.execute(
                "INSERT INTO skills(id,owner,active_version,created,updated) VALUES(%s,%s,%s,%s,%s)",
                (id, owner, vid, 0, 0),
            )
            c.execute(
                "INSERT INTO skill_versions VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    vid,
                    id,
                    1,
                    json.dumps(meta),
                    core.enc("Verify sources and compare evidence."),
                    0,
                ),
            )
            c.execute(
                "INSERT INTO skill_search VALUES(%s,%s,%s,%s,%s,%s::vector,to_tsvector('english',%s))",
                (
                    vid,
                    owner,
                    provider.model(),
                    dim,
                    skills.SCHEMA,
                    provider.vector(v),
                    "Research public information current sources",
                ),
            )
    c.commit()
q = provider.vector([rng.uniform(-1, 1) for _ in range(dim)])
timings = {k: [] for k in ("lexical", "vector", "hybrid")}
max_candidates = 0
for iteration in range(35):
    owner = owners[iteration % 3]
    for kind in timings:
        start = time.perf_counter()
        with core.db() as c:
            if kind == "lexical":
                rows = c.execute(
                    "SELECT version FROM skill_search WHERE owner=%s AND document@@websearch_to_tsquery('english','research OR sources') ORDER BY ts_rank_cd(document,websearch_to_tsquery('english','research OR sources')) DESC LIMIT 8",
                    (owner,),
                ).fetchall()
            elif kind == "vector":
                rows = c.execute(
                    "SELECT version FROM skill_search WHERE owner=%s ORDER BY embedding <=> %s::vector LIMIT 8",
                    (owner, q),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT s.id,s.owner,v.id AS version_id,v.metadata,ts_rank_cd(i.document,websearch_to_tsquery('english','research OR sources')) AS lexical,CASE WHEN i.model=%s AND i.dimensions=%s AND i.schema_version=%s THEN 1-(i.embedding <=> %s::vector) ELSE -1 END AS similarity FROM skills s JOIN skill_versions v ON v.id=s.active_version JOIN skill_search i ON i.version=v.id WHERE s.owner=%s AND i.owner=%s AND s.enabled AND NOT s.archived AND NOT s.deleted",
                    (provider.model(), dim, skills.SCHEMA, q, owner, owner),
                ).fetchall()
                assert len(rows) == 1000 and all(r["owner"] == owner for r in rows)
                candidates, reasons = skills.hybrid(
                    rows, "Research current public sources"
                )
                max_candidates = max(max_candidates, len(candidates))
        if iteration >= 5:
            timings[kind].append((time.perf_counter() - start) * 1000)
report = {
    "users": 3,
    "skills_per_user": 1000,
    "dimensions": dim,
    "vectors": "seeded synthetic; no semantic quality claim",
    "timings_ms": {
        k: {
            "p50": round(statistics.median(v), 2),
            "p95": round(sorted(v)[int(0.95 * (len(v) - 1))], 2),
        }
        for k, v in timings.items()
    },
    "max_candidates": max_candidates,
    "owner_isolation": "all 35 full retrievals contained only 1000 owner rows",
    "python_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    "network_ms": "not measured; providers disabled",
    "catalog_in_model_context": False,
    "reranker_candidate_limit": 8,
    "selected_skill_limit": 3,
    "instruction_char_limit_per_skill": 12000,
}
print(json.dumps(report, indent=2))
