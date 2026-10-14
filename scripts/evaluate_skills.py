"""Labeled retrieval evaluation. --live uses credits in a disposable test DB.
Without --live, validates the fixture only; never claims semantic accuracy.
"""

import argparse, asyncio, json, os, sys, tempfile, time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
CASES = [
    (
        "Research brief",
        "Research current battery recycling developments and cite primary sources",
    ),
    ("Research brief", "Use Research brief to compare renewable energy technologies"),
    ("Research brief", "Find recent public evidence about sodium ion batteries"),
    (
        "Financial analysis",
        "Analyze operating margin debt and cash flows in these financial statements",
    ),
    ("Financial analysis", "Use Financial analysis to calculate liquidity ratios"),
    (
        "Financial analysis",
        "Compare the balance sheets and earnings quality of two companies",
    ),
    (
        "Spreadsheet cleanup",
        "Normalize column names and remove duplicate spreadsheet rows",
    ),
    ("Spreadsheet cleanup", "Use Spreadsheet cleanup on this table"),
    ("Spreadsheet cleanup", "Clean missing cells in a CSV and verify row counts"),
    ("Travel comparison", "Compare flight itineraries and baggage fees"),
    ("Travel comparison", "Use Travel comparison to compare rail and flight options"),
    ("Travel comparison", "Find a travel itinerary with few connections"),
    ("Code review", "Review this Python patch for correctness and missing tests"),
    ("Code review", "Use Code review for this pull request"),
    (
        "Code review",
        "Check an application change for regressions and unsafe error handling",
    ),
    (None, "Hello"),
    (None, "Tell me a joke"),
    (None, "Help me"),
    (None, "Research brief for private account changes"),
    (None, "Travel comparison for purchasing tickets"),
    (None, "Financial analysis for guaranteed investment returns"),
    (
        "Spreadsheet cleanup",
        "Clean financial table columns without interpreting investment outlook",
    ),
    (
        "Financial analysis",
        "Research profitability and leverage from these company statements",
    ),
    (None, "Use Disabled example"),
]
DEFINITIONS = [
    (
        "Research brief",
        "Find current public information and cite evidence",
        ["public evidence research", "technology comparisons"],
        ["private account changes"],
    ),
    (
        "Financial analysis",
        "Analyze supplied company statements, cash flow, leverage and margins",
        ["company financial ratios", "earnings quality"],
        ["guaranteed investment returns"],
    ),
    (
        "Spreadsheet cleanup",
        "Normalize spreadsheet columns, missing cells, duplicate rows and CSV types",
        ["clean tables before analysis"],
        ["interpreting investment outlook"],
    ),
    (
        "Travel comparison",
        "Compare travel itineraries, connections and baggage costs",
        ["flight and rail planning"],
        ["purchasing tickets"],
    ),
    (
        "Code review",
        "Review application patches for correctness, regressions and tests",
        ["pull request code review"],
        ["writing marketing copy"],
    ),
    ("Disabled example", "Disabled catalog fixture", ["Disabled example"], []),
]


async def live():
    from cryptography.fernet import Fernet

    url = os.getenv("ASTER_TEST_DATABASE_URL", "")
    if not urlsplit(url).path.rsplit("/", 1)[-1].startswith("aster_test"):
        raise SystemExit("Requires disposable aster_test* database")
    if not os.getenv("OPENROUTER_API_KEY"):
        raise SystemExit(
            "Requires an authorized provider key; no live evaluation performed"
        )
    os.environ.update(
        ASTER_DATABASE_URL=url,
        ASTER_DATA=tempfile.mkdtemp(),
        ASTER_MASTER_KEY=Fernet.generate_key().decode(),
    )
    from app import core, skills, skill_providers as provider, skill_packages

    core.init()
    owner = core.ident()
    with core.db() as c:
        c.execute(
            "INSERT INTO users VALUES(%s,%s,%s,%s)",
            (owner, owner + "@evaluation.test", "unused", time.time()),
        )
    packages = [
        {
            "name": name,
            "description": desc,
            "tags": [],
            "when_to_use": yes,
            "when_not_to_use": no,
            "capabilities": [],
            "version": 1,
            "instructions": "Follow the process and verify results.",
            "resources": [],
        }
        for name, desc, yes, no in DEFINITIONS
    ]
    vectors = await provider.embed(
        owner, [skill_packages.matching_text(p) for p in packages]
    )
    for p, v in zip(packages, vectors):
        item = skills.activate(owner, p, v, provider.model())
        if p["name"] == "Disabled example":
            skills.status(owner, item["id"], item["revision"], enabled=False)
    report = []
    for expected, query in CASES:
        r = await skills.match(owner, query)
        names = [p["name"] for p in r["pins"]]
        report.append(
            {
                "query": query,
                "expected": expected,
                "selected": names,
                "pass": names == [] if expected is None else expected in names,
                "reranked": r["reranked"],
                "fallback": r.get("fallback", False),
                "reasons": r["reasons"],
                "timing": r["timing"],
            }
        )
    print(
        json.dumps(
            {
                "embedding_model": provider.model(),
                "reranking_model": provider.providers.configured_model("chat"),
                "passed": sum(r["pass"] for r in report),
                "total": len(report),
                "cases": report,
            },
            indent=2,
        )
    )
    if not all(r["pass"] for r in report):
        raise SystemExit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--live",
        action="store_true",
        help="Make billable model calls against disposable test data",
    )
    a = p.parse_args()
    assert len(CASES) == 24 and all(
        expected is None or expected in {d[0] for d in DEFINITIONS}
        for expected, q in CASES
    )
    if a.live:
        asyncio.run(live())
    else:
        print(
            "24 labeled cases validated. Live semantic evaluation NOT RUN; pass --live with a test database and authorized provider key."
        )
