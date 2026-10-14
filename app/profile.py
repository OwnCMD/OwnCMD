"""Owner-scoped, encrypted details. Values are disclosed only after user confirmation."""

import json, re, time
from contextlib import nullcontext
from . import core

FIELDS = {
    "full_name": "Full name",
    "preferred_name": "Preferred name",
    "email": "Contact email",
    "phone": "Mobile number",
    "company": "Company",
    "job_title": "Job title",
    "shipping_name": "Shipping recipient",
    "shipping_line1": "Shipping address",
    "shipping_line2": "Apartment / unit",
    "shipping_city": "Shipping city",
    "shipping_region": "Shipping province / state",
    "shipping_postal": "Shipping postal / ZIP code",
    "shipping_country": "Shipping country",
    "billing_name": "Billing recipient",
    "billing_line1": "Billing address",
    "billing_line2": "Billing apartment / unit",
    "billing_city": "Billing city",
    "billing_region": "Billing province / state",
    "billing_postal": "Billing postal / ZIP code",
    "billing_country": "Billing country",
    "delivery_notes": "Delivery instructions",
    "language": "Preferred language",
    "timezone": "Time zone",
}
SENSITIVE = re.compile(
    r"credit.?card|debit.?card|card.?number|\bcvv\b|\bcvc\b|password|passcode|\botp\b|one.time.code|bank.account|social.security|\bsin\b|passport",
    re.I,
)


def initialize(c):
    c.execute(
        "CREATE TABLE IF NOT EXISTS personal_details(owner TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,body TEXT NOT NULL,version BIGINT NOT NULL,updated DOUBLE PRECISION NOT NULL)"
    )


def safe_text(label, value):
    if not isinstance(value, str) or len(value) > 1000:
        raise ValueError(
            "Each personal detail must be text of at most 1,000 characters"
        )
    if SENSITIVE.search(label):
        raise ValueError(
            "Do not store payment credentials, passwords, verification codes or identity-document numbers here"
        )
    for match in re.finditer(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)", value):
        digits = re.sub(r"\D", "", match.group())
        nums = [int(x) for x in digits][::-1]
        if (
            13 <= len(nums) <= 19
            and sum(
                n if i % 2 == 0 else n * 2 - 9 if n * 2 > 9 else n * 2
                for i, n in enumerate(nums)
            )
            % 10
            == 0
        ):
            raise ValueError("Card numbers cannot be stored in personal details")
    return value.strip()


def get(owner, connection=None):
    with nullcontext(connection) if connection is not None else core.db() as c:
        r = c.execute(
            "SELECT * FROM personal_details WHERE owner=%s", (owner,)
        ).fetchone()
    return {
        **(
            json.loads(core.dec(r["body"]))
            if r
            else {"enabled": True, "fields": {}, "custom": []}
        ),
        "version": r["version"] if r else 0,
        "updated": r["updated"] if r else None,
        "labels": FIELDS,
    }


def save(owner, b):
    if (
        not isinstance(b, dict)
        or not isinstance(b.get("fields", {}), dict)
        or not isinstance(b.get("custom", []), list)
    ):
        raise ValueError("Invalid personal details")
    if type(b.get("enabled", True)) is not bool:
        raise ValueError("Invalid prefill preference")
    fields = {
        k: safe_text(FIELDS[k], v)
        for k, v in b.get("fields", {}).items()
        if k in FIELDS
    }
    custom = []
    seen = set()
    if len(b.get("custom", [])) > 20:
        raise ValueError("Save up to 20 additional details")
    for x in b.get("custom", []):
        if not isinstance(x, dict):
            raise ValueError("Invalid additional detail")
        key = str(x.get("id") or core.ident())
        label = str(x.get("label", "")).strip()[:80]
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", key) or key in seen or not label:
            raise ValueError("Each additional detail needs a unique ID and label")
        seen.add(key)
        custom.append(
            {"id": key, "label": label, "value": safe_text(label, x.get("value", ""))}
        )
    data = {"enabled": b.get("enabled", True), "fields": fields, "custom": custom}
    with core.db() as c:
        c.begin_write()
        r = c.execute(
            "SELECT version FROM personal_details WHERE owner=%s", (owner,)
        ).fetchone()
        version = r["version"] if r else 0
        if b.get("version") != version:
            raise ValueError(
                "Your details changed in another tab. Reload before saving"
            )
        c.execute(
            "INSERT INTO personal_details VALUES(%s,%s,%s,%s) ON CONFLICT(owner) DO UPDATE SET body=excluded.body,version=excluded.version,updated=excluded.updated",
            (owner, core.enc(json.dumps(data)), version + 1, time.time()),
        )
        c.commit()
    return get(owner)


def values(owner, connection=None):
    p = get(owner, connection)
    if not p["enabled"]:
        return {}
    result = {
        **{k: {"label": FIELDS[k], "value": v} for k, v in p["fields"].items() if v},
        **{
            "custom_" + x["id"]: {"label": x["label"], "value": x["value"]}
            for x in p["custom"]
            if x["value"]
        },
    }
    parts = p["fields"].get("full_name", "").split()
    if len(parts) >= 2:
        result["first_name"] = {"label": "First name", "value": " ".join(parts[:-1])}
        result["last_name"] = {"label": "Last name", "value": parts[-1]}
    return result


def requested_keys(args):
    if args.get("input_type") in ("secret", "otp") or SENSITIVE.search(
        str(args.get("question", ""))
    ):
        return []
    keys = args.get("profile_fields", [])
    if isinstance(keys, list) and keys:
        return list(dict.fromkeys(str(k) for k in keys))[:15]
    # Only unambiguous single-field fallbacks. Never infer a third party's identity.
    q = str(args.get("question", "")).lower()
    if re.search(r"\b(their|recipient|friend|passenger|guest|someone)\b", q):
        return []
    if args.get("input_type") == "email":
        return ["email"]
    if args.get("input_type") == "phone":
        return ["phone"]
    if re.search(r"\byour (full )?name\b", q):
        return ["full_name"]
    return []


FORM_LABELS = {
    **FIELDS,
    "first_name": "First name",
    "last_name": "Last name",
    "username": "Desired username",
    "password": "Password",
    "date_of_birth": "Date of birth",
    "otp": "Verification code",
}
FORM_TYPES = {
    "email": "email",
    "phone": "phone",
    "password": "secret",
    "otp": "otp",
    "date_of_birth": "date",
}
FORM_ALLOWED = {"text", "textarea", "email", "phone", "number", "date", "secret", "otp"}


def form_fields(args):
    """Build a complete review form, independently of which values are saved.

    Explicit field descriptors are preferred. The fallback also handles older
    pending requests and models that return a consolidated natural-language ask.
    Model-supplied values are deliberately ignored: only the owner's profile can
    supply defaults, and the user must confirm them before they reach the worker.
    """
    q = str(args.get("question", ""))
    third = bool(
        re.search(r"\b(their|recipient|friend|passenger|guest|someone)\b", q, re.I)
    )
    raw = args.get("fields")
    result = []
    seen = set()

    def add(key, label=None, kind=None, profile_key=None, required=True):
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", key)
            or key in seen
            or len(result) >= 30
        ):
            return
        label = str(
            label or FORM_LABELS.get(key) or key.replace("_", " ").capitalize()
        )[:120]
        kind = (
            kind
            if isinstance(kind, str) and kind in FORM_ALLOWED
            else FORM_TYPES.get(key, "text")
        )
        if re.search(r"\buser ?name\b", label, re.I) and kind == "email":
            kind = "text"
        sensitive = kind in ("secret", "otp") or bool(
            SENSITIVE.search(key + " " + label)
        )
        if sensitive and kind != "otp":
            kind = "secret"
        source = (
            ""
            if third or sensitive
            else (profile_key if isinstance(profile_key, str) else key)
        )
        seen.add(key)
        result.append(
            {
                "key": key,
                "label": label,
                "type": kind,
                "profile_key": source,
                "required": required is not False,
                "sensitive": sensitive,
            }
        )

    if isinstance(raw, list):
        for f in raw:
            if isinstance(f, dict):
                add(
                    f.get("key"),
                    f.get("label"),
                    f.get("type"),
                    f.get("profile_key"),
                    f.get("required", True),
                )
        if result:
            return result
    keys = args.get("profile_fields", [])
    if isinstance(keys, list):
        for key in keys:
            add(key)
    # Future-step mentions are context, not fields needed on the current form.
    current = re.split(
        r"\b(?:may (?:also )?(?:ask|request|require)|on the next step|later\b)",
        q,
        flags=re.I,
    )[0]
    patterns = [
        ("first_name", r"\b(first|given) name\b"),
        ("last_name", r"\b(last|family) name\b|\bsurname\b"),
        ("full_name", r"\bfull name\b"),
        (
            "username",
            r"\buser ?name\b|\b(?:desired|new|choose|preferred)\s+(?:\w+\s+)?(?:email|address)\b|\bpart before\s+@",
        ),
        ("password", r"\bpassword\b"),
        ("date_of_birth", r"\bdate of birth\b|\bbirth ?date\b|\bdob\b"),
        ("phone", r"\b(?:mobile|phone|telephone)(?: number)?\b"),
        ("otp", r"\bverification code\b|\bone.time.code\b|\botp\b"),
    ]
    for key, pattern in patterns:
        if re.search(pattern, current, re.I):
            add(key)
    if "username" not in seen and re.search(r"\be-?mail\b", current, re.I):
        add("email")
    if not result:
        for key in requested_keys(args):
            add(key)
    if not result and args.get("input_type") in ("secret", "otp"):
        add(
            "answer",
            "Password" if args["input_type"] == "secret" else "Verification code",
            args["input_type"],
            profile_key="",
        )
    return result


def sensitive_answer(args):
    return (
        args.get("input_type") in ("secret", "otp")
        or bool(SENSITIVE.search(str(args.get("question", ""))))
        or any(f["sensitive"] for f in form_fields(args))
    )


def answer_text(args, body):
    """Validate keyed answers against this exact request, never a profile snapshot."""
    if "field_values" not in body:
        return str(body.get("text", ""))[:8000]
    fields = form_fields(args)
    answers = body["field_values"]
    if (
        not fields
        or not isinstance(answers, dict)
        or set(answers) - {f["key"] for f in fields}
    ):
        raise ValueError("Invalid answer fields")
    lines = []
    for f in fields:
        value = answers.get(f["key"], "")
        if not isinstance(value, str) or len(value) > 4000:
            raise ValueError("Each answer must be text of at most 4,000 characters")
        if f["required"] and not value.strip():
            raise ValueError("Complete " + f["label"])
        lines.append(f["label"] + ": " + value)
    extra = body.get("text", "")
    if not isinstance(extra, str):
        raise ValueError("Invalid additional details")
    if extra.strip():
        lines.append("Additional details: " + extra)
    text = "\n".join(lines)
    if len(text) > 8000:
        raise ValueError("Keep the combined answer under 8,000 characters")
    return text


def prefill(owner, approval):
    if not approval or approval.get("name") != "ask_user":
        return approval
    args = approval.get("arguments") or {}
    v = values(owner)
    fields = []
    for f in form_fields(args):
        saved = v.get(f["profile_key"], {})
        fields.append(
            {
                **f,
                "label": (
                    saved.get("label", f["label"])
                    if f["key"].startswith("custom_")
                    else f["label"]
                ),
                "value": saved.get("value", ""),
                "prefilled": bool(saved.get("value")),
            }
        )
    return {
        **approval,
        "fields": fields,
        "prefill": [f for f in fields if f["prefilled"]],
    }
