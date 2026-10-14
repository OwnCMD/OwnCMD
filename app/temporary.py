"""Process-local conversations. Never written to the task/event database or disk.

The managed API runs one worker. Temporary sessions expire after 30 minutes idle
(or 8 hours absolute), and are discarded on navigation, logout or process restart.
Only content-free billing records remain in PostgreSQL.
"""

import copy, threading, time
from contextlib import contextmanager

LOCK = threading.RLock()
ROWS = {}
IDLE_SECONDS = 1800
MAX_AGE = 28800
MAX_BYTES = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024


def is_temporary(task):
    return str(task).startswith("tmp-")


def sweep():
    now = time.time()
    with LOCK:
        for tid, item in list(ROWS.items()):
            if (
                now - item["touched"] > IDLE_SECONDS
                or now - item["row"]["created"] > MAX_AGE
            ):
                ROWS.pop(tid, None)


def _item(tid, owner=None):
    sweep()
    item = ROWS.get(tid)
    if not item or (owner is not None and item["row"]["owner"] != owner):
        raise KeyError("Temporary chat has ended")
    return item


@contextmanager
def locked(tid, owner):
    with LOCK:
        item = _item(tid, owner)
        yield item["row"]


def create(owner, tid, state):
    now = time.time()
    with LOCK:
        sweep()
        if tid in ROWS:
            _item(tid, owner)
            return tid
        if sum(x["row"]["owner"] == owner for x in ROWS.values()) >= 5:
            raise ValueError("Close an existing temporary chat before starting another")
        if (
            len(state) > MAX_BYTES
            or sum(x["bytes"] for x in ROWS.values()) + len(state) > MAX_TOTAL
        ):
            raise ValueError("Temporary chat capacity reached. Please try again later.")
        row = dict(
            id=tid,
            owner=owner,
            title="Temporary chat",
            state=state,
            status="ready",
            mode="chat",
            control="ai",
            lease=0,
            busy=0,
            version=0,
            control_epoch=0,
            created=now,
            updated=now,
            temporary=True,
        )
        ROWS[tid] = {
            "row": row,
            "events": [],
            "sequence": 0,
            "touched": now,
            "bytes": len(state),
        }
    return tid


def owned(owner, tid):
    with LOCK:
        return copy.deepcopy(_item(tid, owner)["row"])


def claim(owner, tid):
    with LOCK:
        item = _item(tid, owner)
        row = item["row"]
        now = time.time()
        if row["status"] == "running":
            raise ValueError("OwnCMD is still answering the previous message")
        previous = copy.deepcopy(row)
        row.update(busy=now + 300, status="running", updated=now)
        item["touched"] = now
        return previous


def save(owner, tid, state, status):
    with LOCK:
        item = _item(tid, owner)
        projected = item["bytes"] - len(item["row"]["state"]) + len(state)
        if (
            projected > MAX_BYTES
            or sum(x["bytes"] for x in ROWS.values()) - item["bytes"] + projected
            > MAX_TOTAL
        ):
            raise ValueError("Temporary chat is too large. Start a new chat.")
        item["bytes"] = projected
        item["touched"] = time.time()
        item["row"].update(
            state=state,
            status=status,
            busy=time.time() + 300 if status == "running" else 0,
            lease=0,
            updated=time.time(),
        )


def event(tid, kind, body):
    with LOCK:
        # An in-flight response may finish after the tab was closed. Never recreate it.
        if tid not in ROWS:
            return
        item = _item(tid)
        item["sequence"] += 1
        item["events"].append(
            dict(id=item["sequence"], kind=kind, body=body, created=time.time())
        )
        item["bytes"] += len(body)
        # Bound streaming replay memory, including large rendered Markdown snapshots.
        while (
            len(item["events"]) > 250
            or sum(len(e["body"]) for e in item["events"]) > 2 * 1024 * 1024
        ):
            item["bytes"] -= len(item["events"].pop(0)["body"])


def events(owner, tid, after=0):
    with LOCK:
        return copy.deepcopy(
            [e for e in _item(tid, owner)["events"] if e["id"] > after]
        )


def discard(owner, tid):
    with LOCK:
        if tid in ROWS:
            _item(tid, owner)
            ROWS.pop(tid, None)


def discard_owner(owner):
    with LOCK:
        for tid, item in list(ROWS.items()):
            if item["row"]["owner"] == owner:
                ROWS.pop(tid, None)


# A daemon ensures expired content disappears even with no subsequent requests.
def _reap():
    while True:
        time.sleep(60)
        sweep()


threading.Thread(target=_reap, name="temporary-chat-expiry", daemon=True).start()
