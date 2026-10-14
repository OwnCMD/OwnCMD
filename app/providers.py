import os, time, json, asyncio, re
import httpx
from .core import reserve, settle
from . import billing, core, work_output
from decimal import Decimal


class ProviderError(Exception):
    def __init__(self, text, status=0, diagnostic=""):
        super().__init__(text)
        self.status = status
        self.diagnostic = diagnostic


def provider_diagnostic(response, key):
    """Bounded operator-only error fields, never headers or entire request bodies."""
    try:
        data = response.json()
    except (ValueError, TypeError):
        return "Provider returned a non-JSON error response"
    if not isinstance(data, dict):
        return "Provider returned an unrecognized error response"
    error = data.get("error", data)
    if not isinstance(error, dict):
        error = {"message": error}
    fields = []

    def collect(value):
        if not isinstance(value, dict):
            return
        for name in ("message", "code", "type", "param"):
            text = value.get(name)
            if isinstance(text, (str, int)):
                fields.append(name + "=" + str(text))

    collect(error)
    metadata = error.get("metadata") or {}
    if isinstance(metadata, dict):
        if isinstance(metadata.get("provider_name"), str):
            fields.append("provider=" + metadata["provider_name"])
        raw = metadata.get("raw")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = {"message": raw}
        if isinstance(raw, dict):
            collect(raw.get("error", raw))
    text = "; ".join(fields) or "No provider error detail was supplied"
    if key:
        text = text.replace(key, "[redacted]")
    text = re.sub(r'(?i)(bearer\s+)[^\s,;"\']+', r"\1[redacted]", text)
    text = re.sub(r"\b(?:sk-|sk_|whsec_)[A-Za-z0-9_-]+", "[redacted]", text)
    return " ".join(text.split())[:1200]


CHAT_MODEL_DEFAULT = "google/gemini-3.5-flash-lite"
WORK_MODEL_DEFAULT = "openai/gpt-5.6-luna"


def configured_model(mode):
    return (
        os.getenv("ASTER_WORK_MODEL", WORK_MODEL_DEFAULT)
        if mode == "work"
        else os.getenv("ASTER_CHAT_MODEL", CHAT_MODEL_DEFAULT)
    )


async def request(url, body, key, exa=False, *, diagnostics=False):
    async with httpx.AsyncClient(timeout=65, trust_env=True) as c:
        try:
            r = await c.post(
                url,
                json=body,
                headers=(
                    {"x-api-key": key} if exa else {"Authorization": "Bearer " + key}
                ),
            )
        except httpx.HTTPError:
            raise ProviderError("Provider connection failed", 503)
        if r.status_code != 200:
            detail = provider_diagnostic(r, key) if diagnostics else ""
            raise ProviderError(
                f"{'Search' if exa else 'AI'} service request failed ({r.status_code}). Please retry shortly.",
                r.status_code,
                detail,
            )
        return r.json()


_catalog = (0, {})


async def catalog():
    global _catalog
    if time.time() - _catalog[0] < 3600:
        return _catalog[1]
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://openrouter.ai/api/v1/models")
        r.raise_for_status()
        models = {m["id"]: m for m in r.json()["data"]}
    _catalog = (time.time(), models)
    return models


async def _prepare_model(row, s, tools, system, max_tokens=6000):
    if not credential("OPENROUTER_API_KEY"):
        raise ProviderError(
            "Model API key is not configured. Ask an instance owner to add it in Instance settings > Providers.",
            503,
        )
    mode = s.get("mode") or row.get("mode") or "chat"
    from . import accounts

    selected = accounts.resolve_model(row["owner"], mode, s.get("model_choice", "auto"))
    tools = accounts.filter_tools(row["owner"], tools)
    models = await catalog()
    if selected not in models:
        raise ProviderError(
            f"{mode.title()} mode is temporarily unavailable. Please contact support.",
            404,
        )
    if tools and "tools" not in models[selected].get("supported_parameters", []):
        raise ProviderError(
            "Work mode is temporarily unavailable. Please contact support.", 400
        )
    m = models[selected]
    price = m.get("pricing", {})
    p = float(price.get("prompt", "0"))
    o = float(price.get("completion", "0"))
    if p < 0 or o < 0:
        raise ValueError("Unknown model pricing; refusing unbounded spend")
    from . import documents

    attachment_prompt, attachment_images = await asyncio.to_thread(
        documents.model_context, row, s
    )
    system += attachment_prompt
    is_work = mode == "work" and s.get("_billing_service", "model") == "model"
    cap = (
        work_output.output_limit(s, selected, m, max_tokens) if is_work else max_tokens
    )
    messages = [
        {
            "role": "system",
            "content": system
            + "\nYou are OwnCMD. The selected model is "
            + selected
            + ". Do not expose credentials or internal infrastructure.",
        }
    ] + context_messages(s, m, tools, output_reserve=cap)
    if attachment_images:
        messages.append({"role": "user", "content": attachment_images})
    size = text_bytes(messages) + len(json.dumps(tools).encode())
    image_count = sum(
        1
        for msg in messages
        if isinstance(msg.get("content"), list)
        for block in msg["content"]
        if isinstance(block, dict) and block.get("type") == "image_url"
    )
    modalities = m.get("architecture", {}).get("input_modalities", [])
    if image_count and "image" not in modalities:
        raise ProviderError("Image input is currently unavailable in this mode.", 400)
    image_price = float(price.get("image", "0") or 0)
    fixed = (
        (size + image_count * 8192) * p
        + float(price.get("request", 0) or 0)
        + image_count * image_price
    )
    estimate = fixed + cap * o
    rid = reserve(
        row["owner"],
        row["id"],
        estimate,
        service=s.get("_billing_service", "model"),
        model=selected,
        metadata={"mode": mode, "pricing": price},
    )
    s["cost"] += estimate
    # The effective account policy selects one model. OpenRouter can fail over between providers
    # serving the SAME model, but OwnCMD never supplies a cross-model fallback list.
    body = {
        "model": selected,
        "messages": messages,
        "max_completion_tokens": cap,
        "provider": {
            "allow_fallbacks": True,
            "require_parameters": bool(tools),
            "max_price": {
                "prompt": p * 1e6,
                "completion": o * 1e6,
                "request": float(price.get("request", 0) or 0),
                "image": image_price,
            },
        },
    }
    body["user"] = row["owner"]
    if tools:
        body["tools"] = tools
    return selected, body, rid, estimate


async def model_call(row, s, tools, system, max_tokens=6000):
    selected, body, rid, estimate = await _prepare_model(
        row, s, tools, system, max_tokens
    )
    try:
        data = await request(
            "https://openrouter.ai/api/v1/chat/completions",
            body,
            credential("OPENROUTER_API_KEY"),
        )
    except ProviderError as e:
        if e.status in (400, 401, 402, 403, 404, 422, 429):
            settle(rid, 0)
            s["cost"] -= estimate
        else:
            billing.record(rid, pending=True)
        raise
    actual = (data.get("usage") or {}).get("cost")
    settle_response(rid, data)
    if actual is not None:
        s["cost"] += float(actual) - estimate
    s["model"] = selected
    choice = (data.get("choices") or [{}])[0]
    is_work = (s.get("mode") or row.get("mode")) == "work" and s.get(
        "_billing_service", "model"
    ) == "model"
    reason = str(
        choice.get("finish_reason") or choice.get("native_finish_reason") or ""
    ).lower()
    if reason in ("length", "max_tokens", "max_output_tokens", "max_completion_tokens"):
        if is_work:
            raise work_output.IncompleteOutput(selected, body["max_completion_tokens"])
        raise ProviderError(
            "Model output was truncated. Narrow the task or request smaller files.", 422
        )
    if reason == "content_filter":
        raise ProviderError(
            "The provider could not complete this response because of its content policy.",
            422,
        )
    if reason == "error":
        raise ProviderError("Provider interrupted this response", 502)
    msg = choice.get("message")
    if not msg:
        raise ProviderError("Provider returned no message", 502)
    if is_work:
        work_output.validate_message(msg, selected, body["max_completion_tokens"])
    return msg


async def model_call_stream(row, s, tools, system, on_delta=None):
    """OpenRouter streaming completion with tool-call reconstruction.

    This is used by Chat so text reaches the UI as the model generates it. Tool calls are
    accumulated exactly like a normal OpenAI-compatible completion and are not exposed as text.
    """
    selected, body, rid, estimate = await _prepare_model(row, s, tools, system)
    body["stream"] = True
    headers = {"Authorization": "Bearer " + credential("OPENROUTER_API_KEY")}
    content = []
    tool_map = {}
    finish_reason = None
    actual = None
    got = False
    usage = {}
    generation = None
    try:
        async with httpx.AsyncClient(timeout=70, trust_env=True) as c:
            async with c.stream(
                "POST",
                "https://openrouter.ai/api/v1/chat/completions",
                json=body,
                headers=headers,
            ) as r:
                if r.status_code != 200:
                    raw = (await r.aread()).decode(errors="replace")[:350]
                    try:
                        data = json.loads(raw)
                        err = data.get("error", {})
                        raw = str(
                            err.get("message")
                            if isinstance(err, dict)
                            else err or data.get("detail", "")
                        )[:350]
                    except Exception:
                        pass
                    raise ProviderError(
                        f"AI service request failed ({r.status_code}). Please retry shortly.",
                        r.status_code,
                    )
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        data = json.loads(payload)
                    except Exception:
                        continue
                    got = True
                    if data.get("id") and not generation:
                        generation = data["id"]
                        billing.record(rid, provider_id=generation)
                    if data.get("usage"):
                        usage = data["usage"]
                        actual = usage.get("cost")
                        settle_response(rid, {"id": generation, "usage": usage})
                    if data.get("error"):
                        raise ProviderError("Provider interrupted this response", 502)
                    choice = (data.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    if choice.get("finish_reason"):
                        finish_reason = choice.get("finish_reason")
                    piece = delta.get("content")
                    if isinstance(piece, str) and piece:
                        content.append(piece)
                        if on_delta:
                            value = on_delta(piece)
                            if asyncio.iscoroutine(value):
                                await value
                    for tc in delta.get("tool_calls") or []:
                        idx = int(tc.get("index", 0))
                        item = tool_map.setdefault(
                            idx,
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        if tc.get("id"):
                            item["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            item["function"]["name"] += fn["name"]
                        if fn.get("arguments"):
                            item["function"]["arguments"] += fn["arguments"]
    except ProviderError as e:
        if e.status in (400, 401, 402, 403, 404, 422, 429):
            settle(rid, 0)
            s["cost"] -= estimate
        else:
            billing.record(rid, pending=True)
        raise
    except httpx.HTTPError:
        billing.record(rid, pending=True)
        # Unknown provider-side outcome keeps the reservation, matching non-streaming semantics.
        raise ProviderError("Provider connection failed", 503)
    if not got:
        billing.record(rid, pending=True)
        raise ProviderError("Provider returned no message", 502)
    settle_response(rid, {"id": generation, "usage": usage})
    if actual is not None:
        s["cost"] += float(actual) - estimate
    s["model"] = selected
    if finish_reason == "length":
        raise ProviderError(
            "Model output was truncated. Narrow the task or request smaller files.", 422
        )
    msg = {"role": "assistant", "content": "".join(content)}
    calls = [tool_map[k] for k in sorted(tool_map)]
    if calls:
        msg["tool_calls"] = calls
    return msg


async def generate_title(owner, task_id, prompt):
    """Generate a short conversation title without mutating task state or blocking the main turn."""
    prompt = str(prompt or "").strip()
    if not prompt:
        return ""
    model = configured_model("chat")
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Create a concise conversation title from the user message. Return only the title, 3 to 7 words, no quotes, no punctuation at the end.",
            },
            {"role": "user", "content": prompt[:4000]},
        ],
        "max_tokens": 28,
        "temperature": 0.2,
    }
    state = {
        "mode": "chat",
        "messages": [body["messages"][1]],
        "cost": 0,
        "_billing_service": "title",
    }
    try:
        _, prepared, rid, amount = await _prepare_model(
            {"owner": owner, "id": task_id},
            state,
            [],
            body["messages"][0]["content"],
            28,
        )
        prepared["temperature"] = 0.2
    except Exception:
        return ""
    try:
        data = await request(
            "https://openrouter.ai/api/v1/chat/completions",
            prepared,
            credential("OPENROUTER_API_KEY"),
        )
    except ProviderError as e:
        if e.status in (400, 401, 402, 403, 404, 422, 429):
            settle(rid, 0)
        else:
            billing.record(rid, pending=True)
        return ""
    except Exception:
        billing.record(rid, pending=True)
        return ""
    settle_response(rid, data)
    try:
        title = (
            str(data["choices"][0]["message"]["content"])
            .strip()
            .strip("\"'`# ")
            .replace("\n", " ")
        )
    except Exception:
        return ""
    title = " ".join(title.split())[:80].strip(" .,:;-")
    return title if 2 <= len(title) <= 80 else ""


async def search(row, s, query):
    if not credential("EXA_API_KEY"):
        raise ProviderError(
            "Search API key is not configured. Ask an instance owner to add it in Instance settings > Providers.",
            503,
        )
    from . import accounts

    accounts.require(row["owner"], "search")
    if not isinstance(query, str) or not 2 <= len(query) <= 500:
        raise ValueError("Invalid search query")
    amount = float(os.getenv("ASTER_EXA_RESERVE", "0.03"))
    rid = reserve(
        row["owner"],
        row["id"],
        amount,
        service="search",
        metadata={"provider": "exa", "type": "auto"},
    )
    s["cost"] += amount
    s["searches"] += 1
    n = max(3, min(10, int(os.getenv("ASTER_EXA_RESULTS", "8"))))
    try:
        data = await request(
            "https://api.exa.ai/search",
            {
                "query": query,
                "numResults": n,
                "type": "auto",
                "contents": {"text": {"maxCharacters": 4500}},
            },
            credential("EXA_API_KEY"),
            True,
        )
    except ProviderError as e:
        if e.status in (400, 401, 402, 403, 404, 422, 429):
            settle(rid, 0)
            s["cost"] -= amount
        else:
            billing.record(rid, pending=True)
        raise
    cost = data.get("costDollars", {}).get("total")
    settle(
        rid,
        cost,
        provider_id=data.get("requestId"),
        metadata={
            "result_count": len(data.get("results", [])),
            "reported_cost": data.get("costDollars", {}),
            "cost_basis": "Exa costDollars.total (provider estimate)",
            "provisional": True,
        },
    )
    if cost is not None:
        s["cost"] += float(cost) - amount
    return [
        {
            "title": str(r.get("title") or r.get("url"))[:240],
            "url": str(r.get("url"))[:2000],
            "favicon": r.get("favicon"),
            "text": r.get("text", "")[:4500],
        }
        for r in data.get("results", [])
        if r.get("url")
    ]


async def contents(row, s, url, refresh=False):
    if not credential("EXA_API_KEY"):
        raise ProviderError(
            "Search API key is not configured. Ask an instance owner to add it in Instance settings > Providers.",
            503,
        )
    from . import accounts

    accounts.require(row["owner"], "search")
    amount = float(os.getenv("ASTER_EXA_RESERVE", "0.03"))
    rid = reserve(
        row["owner"],
        row["id"],
        amount,
        service="search",
        metadata={"provider": "exa", "type": "contents"},
    )
    s["cost"] += amount
    body = {"urls": [url], "text": {"maxCharacters": 200000}}
    if refresh:
        body["maxAgeHours"] = 0
    try:
        data = await request(
            "https://api.exa.ai/contents", body, credential("EXA_API_KEY"), True
        )
    except ProviderError as e:
        if e.status in (400, 401, 402, 403, 404, 422, 429):
            settle(rid, 0)
            s["cost"] -= amount
        else:
            billing.record(rid, pending=True)
        raise
    cost = data.get("costDollars", {}).get("total")
    settle(
        rid,
        cost,
        provider_id=data.get("requestId"),
        metadata={
            "result_count": len(data.get("results", [])),
            "reported_cost": data.get("costDollars", {}),
            "provider": "exa",
            "type": "contents",
            "cost_basis": "Exa contents costDollars.total",
            "provisional": True,
        },
    )
    if cost is not None:
        s["cost"] += float(cost) - amount
    return next((r for r in data.get("results", []) if r.get("text")), {})


def text_bytes(messages):
    # Base64 image bytes are not text tokens. Image input is reserved separately.
    def trim(value):
        if isinstance(value, dict):
            return {
                k: ("[image]" if k == "image_url" else trim(v))
                for k, v in value.items()
                if k != "sources"
            }
        if isinstance(value, list):
            return [trim(v) for v in value]
        return value

    return len(json.dumps(trim(messages), ensure_ascii=False).encode())


def context_messages(s, model, tools, output_reserve=8000):
    messages = [
        {
            k: v
            for k, v in m.items()
            if k in ("role", "content", "tool_calls", "tool_call_id", "name")
        }
        for m in s["messages"]
    ]
    # Keep tool-call groups intact. Full history stays in encrypted task state and
    # Work can retrieve older records with recall_work; this avoids a total-step cap.
    budget = max(
        8000,
        min(
            120000,
            int(model.get("context_length") or 32000) - max(8000, output_reserve),
        ),
    )
    if text_bytes(messages) <= budget:
        return messages
    groups = []
    for m in messages:
        if m.get("role") == "tool" and groups:
            groups[-1].append(m)
        else:
            groups.append([m])
    kept = []
    size = 0
    for group in reversed(groups):
        length = text_bytes(group)
        if kept and size + length > budget:
            break
        kept = group + kept
        size += length
    latest_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    if latest_user and latest_user not in kept:
        kept = [latest_user] + kept
    first = messages[0]
    if first not in kept:
        kept = [
            first,
            {
                "role": "system",
                "content": "Earlier conversation records have been omitted from this model context to make room for continued work. They remain saved. Use recall_work to retrieve prior actions/results by offset or query when needed.",
            },
        ] + kept
    return kept


def settle_response(rid, data):
    u = data.get("usage") or {}
    prompt = u.get("prompt_tokens_details") or {}
    completion = u.get("completion_tokens_details") or {}
    metadata = {
        "prompt_tokens": u.get("prompt_tokens", 0),
        "completion_tokens": u.get("completion_tokens", 0),
        "cached_tokens": prompt.get("cached_tokens", 0),
        "cache_write_tokens": prompt.get("cache_write_tokens", 0),
        "reasoning_tokens": completion.get("reasoning_tokens", 0),
        "cost_basis": "OpenRouter usage.cost",
    }
    settle(rid, u.get("cost"), provider_id=data.get("id"), metadata=metadata)


_reconciled_at = 0


async def reconcile_pending():
    global _reconciled_at
    if time.time() - _reconciled_at < 60:
        return
    _reconciled_at = time.time()
    with core.db() as c:
        rows = c.execute(
            "SELECT * FROM usage_operations WHERE service IN ('model','title','skill_generation','skill_rerank') AND status IN ('reserved','pending') AND provider_id IS NOT NULL AND updated<%s ORDER BY updated LIMIT 10",
            (time.time() - 90,),
        ).fetchall()
    async with httpx.AsyncClient(timeout=10) as client:
        for r in rows:
            try:
                response = await client.get(
                    "https://openrouter.ai/api/v1/generation",
                    params={"id": r["provider_id"]},
                    headers={
                        "Authorization": "Bearer " + credential("OPENROUTER_API_KEY")
                    },
                )
                response.raise_for_status()
                data = response.json()["data"]
                if data.get("total_cost") is None:
                    continue
                settle(
                    r["id"],
                    data["total_cost"],
                    metadata={
                        "prompt_tokens": data.get("native_tokens_prompt", 0),
                        "completion_tokens": data.get("native_tokens_completion", 0),
                        "reasoning_tokens": data.get("native_tokens_reasoning", 0),
                        "cached_tokens": data.get("native_tokens_cached", 0),
                        "cost_basis": "OpenRouter generation.total_cost",
                        "reconciled": True,
                    },
                )
            except Exception:
                billing.record(r["id"], pending=True)


from .integrations import credential
