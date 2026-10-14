"""Durable, bounded recovery of incomplete Work model responses.

Only complete responses enter task history. A failed generation is still billed,
but none of its proposed actions has run and none is replayed during recovery.
"""

import json

MAX_OUTPUT = 48000
MAX_CONSECUTIVE = 3
MAX_RECOVERIES = 8
PAUSED = (
    "The model repeatedly returned an incomplete response. Work is paused to prevent repeated charges. "
    "Completed actions, files and notes are preserved. Send a follow-up to continue; "
    "you can select another available Work model."
)


class IncompleteOutput(Exception):
    def __init__(self, model, limit, kind="length"):
        super().__init__(
            "Model response exceeded its output limit"
            if kind == "length"
            else "Model returned incomplete tool arguments"
        )
        self.model = model
        self.limit = limit
        self.kind = kind


def positive_int(value, default):
    try:
        value = int(value)
        return value if value > 0 else default
    except (TypeError, ValueError, OverflowError):
        return default


def output_limit(state, model, metadata, requested):
    recovery = state.get("output_recovery") or {}
    cap = requested
    if recovery.get("model") == model:
        cap = max(cap, positive_int(recovery.get("limit"), requested))
    top = metadata.get("top_provider") or {}
    cap = min(
        cap, MAX_OUTPUT, positive_int(top.get("max_completion_tokens"), MAX_OUTPUT)
    )
    # Leave input headroom even when a small-context model advertises a large
    # output ceiling. Context trimming separately reserves the requested output.
    context = positive_int(
        top.get("context_length"), positive_int(metadata.get("context_length"), 32000)
    )
    return max(1, min(cap, context // 2))


def validate_message(message, model, limit):
    """Validate the WHOLE batch before any side effect can enter the queue."""

    def invalid():
        raise IncompleteOutput(model, limit, "tool_arguments")

    if not isinstance(message, dict):
        invalid()
    calls = message.get("tool_calls") or []
    if not isinstance(calls, list) or len(calls) > 8:
        invalid()
    ids = set()
    for call in calls:
        if not isinstance(call, dict):
            invalid()
        key = call.get("id")
        fn = call.get("function")
        if not isinstance(key, str) or not key or key in ids:
            invalid()
        ids.add(key)
        if (
            not isinstance(fn, dict)
            or not isinstance(fn.get("name"), str)
            or not fn["name"]
        ):
            invalid()
        raw = fn.get("arguments", "{}")
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            invalid()
        if not isinstance(args, dict) and not (
            fn["name"] in ("work_notebook", "ask_user") and isinstance(args, list)
        ):
            invalid()
        if not isinstance(raw, str):
            fn["arguments"] = json.dumps(args, ensure_ascii=False)
    if message.get("content") is not None and not isinstance(message["content"], str):
        invalid()


def recover(state, error):
    recovery = state.setdefault("output_recovery", {})
    consecutive = int(recovery.get("consecutive", 0)) + 1
    total = int(recovery.get("total", 0)) + 1
    recovery.update(
        model=error.model,
        consecutive=consecutive,
        total=total,
        limit=(
            min(MAX_OUTPUT, max(6000, error.limit * 2))
            if error.kind == "length"
            else error.limit
        ),
        kind=error.kind,
        blocked=consecutive > MAX_CONSECUTIVE or total > MAX_RECOVERIES,
    )
    state["not_before"] = 0
    if recovery["blocked"]:
        state["error"] = PAUSED
        return False
    state.pop("error", None)
    return True


def accepted(state):
    recovery = state.get("output_recovery")
    if recovery:
        recovery["consecutive"] = 0
    state.pop("error", None)


def prompt(state):
    recovery = state.get("output_recovery") or {}
    if not recovery.get("consecutive"):
        return ""
    return (
        "\nOUTPUT RECOVERY: The previous model response was incomplete and was discarded in full. "
        "NONE of that response's proposed tool calls executed. Previously recorded tool results remain valid. "
        "Continue from the last confirmed result; consult the notebook or recall_work if needed. "
        "Return one small, complete tool call with valid JSON arguments, or a concise complete final answer. "
        "For large files, use short run_code commands to apply targeted edits or write staged chunks; "
        "inspect existing files before appending and verify the final file. Do not repeat completed actions, "
        "regenerate whole large files in one call, or ask the user to narrow the overall task. "
        "Keep internal deliberation focused on the next step. Never fabricate missing tool results.\n"
    )
