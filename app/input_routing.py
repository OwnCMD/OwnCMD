"""Input presentation follows the real work environment, independently of model."""

import json, time

CODE_TOOLS = {
    "run_code",
    "write_file",
    "read_file",
    "list_files",
    "start_service",
    "test_app",
    "preview",
    "stage_attachment",
    "publish_file",
}


def coding_context(state):
    return bool(
        state.get("coding_used")
        or state.get("app_preview")
        or state.get("input_context") == "code"
        or any(
            (c.get("function") or {}).get("name") in CODE_TOOLS
            for m in state.get("messages", [])
            for c in m.get("tool_calls") or []
        )
    )


def browser_input_context(state):
    if coding_context(state):
        return False
    if state.get("input_context"):
        return state["input_context"] == "browser"
    return bool(state.get("browser_used"))


def finish_question(state, args):
    text = (
        str(args.get("question") or "").strip()[:24000]
        or "Please send the missing task details in chat."
    )
    pending = state["pending"]
    for call in pending["calls"][pending["index"] :]:
        state["messages"].append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": "Clarification moved to ordinary chat. Remaining actions were not executed.",
            }
        )
    state["messages"].append({"role": "assistant", "content": text})
    state["pending"] = None
    state["result"] = text
    return text


def repair_existing(c):
    """One-time idempotent upgrade recovery for old coding forms; no action replay."""
    from . import core

    now = time.time()
    for row in c.execute(
        "SELECT id,state FROM tasks WHERE mode='work' AND status='approval' AND lease<=%s AND busy<=%s",
        (now, now),
    ).fetchall():
        state = core.state(row)
        pending = state.get("pending") or {}
        if not coding_context(state) or pending.get("answer"):
            continue
        try:
            call = pending["calls"][pending["index"]]
            if call["function"]["name"] != "ask_user":
                continue
            args = call["function"].get("arguments") or "{}"
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict):
                args = {}
            text = finish_question(state, args)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        c.execute(
            "UPDATE tasks SET state=%s,status='completed',updated=%s,version=version+1 WHERE id=%s",
            (core.enc(json.dumps(state)), now, row["id"]),
        )
        c.execute(
            "INSERT INTO events(task,kind,body,created) VALUES(%s,%s,%s,%s)",
            (
                row["id"],
                "turn_completed",
                core.enc(
                    json.dumps(
                        {"text": "Coding clarification is now available in chat."}
                    )
                ),
                now,
            ),
        )
