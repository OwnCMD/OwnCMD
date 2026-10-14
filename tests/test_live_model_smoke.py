"""The installer's live probes must match production-compatible provider inputs."""

import asyncio, json
import httpx, pytest
from app import operations, providers


def completed():
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "id": "smoke",
                            "type": "function",
                            "function": {
                                "name": "smoke_check",
                                "arguments": '{"status":"ready"}',
                            },
                        }
                    ]
                },
            }
        ]
    }


@pytest.mark.parametrize(
    "model", ["google/gemini-3.5-flash-lite", "openai/gpt-5.6-luna"]
)
def test_model_probe_uses_production_token_parameter_and_validates_call(
    monkeypatch, model
):
    seen = []

    async def request(url, body, key, exa=False, **kwargs):
        seen.append(body)
        assert "max_tokens" not in body and "tool_choice" not in body
        assert body["max_completion_tokens"] == 4096
        assert body["provider"] == {"allow_fallbacks": True, "require_parameters": True}
        assert kwargs == {"diagnostics": True}
        return completed()

    monkeypatch.setattr(operations, "request", request)
    asyncio.run(operations.live_model_smoke(model, {"supported_parameters": ["tools"]}))
    assert len(seen) == 1 and seen[0]["model"] == model


def test_probe_respects_catalog_output_limit(monkeypatch):
    async def request(url, body, *args, **kwargs):
        assert body["max_completion_tokens"] == 1024
        return completed()

    monkeypatch.setattr(operations, "request", request)
    asyncio.run(
        operations.live_model_smoke(
            "small",
            {
                "supported_parameters": ["tools"],
                "top_provider": {"max_completion_tokens": 1024},
            },
        )
    )


@pytest.mark.parametrize(
    "response",
    [
        {},
        None,
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "ready"}}]},
        {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {
                        "tool_calls": completed()["choices"][0]["message"]["tool_calls"]
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "wrong_tool",
                                    "arguments": '{"status":"ready"}',
                                },
                            }
                        ]
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "smoke_check",
                                    "arguments": '{"status":',
                                },
                            }
                        ]
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "smoke_check",
                                    "arguments": '{"status":"failed"}',
                                },
                            }
                        ]
                    },
                }
            ]
        },
    ],
)
def test_incomplete_or_wrong_call_never_passes(monkeypatch, response):
    async def request(*args, **kwargs):
        return response

    monkeypatch.setattr(operations, "request", request)
    with pytest.raises(RuntimeError, match="did not return a complete"):
        asyncio.run(
            operations.live_model_smoke(
                "configured", {"supported_parameters": ["tools"]}
            )
        )


@pytest.mark.parametrize("metadata", [None, {}, {"supported_parameters": []}])
def test_unsupported_catalog_model_fails_before_network(monkeypatch, metadata):
    async def request(*args, **kwargs):
        pytest.fail("Unexpected network request")

    monkeypatch.setattr(operations, "request", request)
    with pytest.raises(RuntimeError, match="absent or lacks tools"):
        asyncio.run(operations.live_model_smoke("configured", metadata))


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422, 429, 503])
def test_provider_failure_identifies_model_and_does_not_retry_or_pass(
    monkeypatch, status
):
    calls = []

    async def request(*args, **kwargs):
        calls.append(args)
        raise providers.ProviderError(
            "Public error", status, "param=max_tokens; Unsupported parameter"
        )

    monkeypatch.setattr(operations, "request", request)
    with pytest.raises(
        RuntimeError, match="OpenRouter model configured failed"
    ) as error:
        asyncio.run(
            operations.live_model_smoke(
                "configured", {"supported_parameters": ["tools"]}
            )
        )
    assert str(status) in str(error.value) and "param=max_tokens" in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("diagnostics", [False, True])
def test_diagnostics_are_opt_in_redacted_and_not_in_public_error(
    monkeypatch, diagnostics
):
    key = "test-private-credential"
    payload = {
        "error": {
            "message": "Provider returned error",
            "metadata": {
                "provider_name": "Example",
                "raw": json.dumps(
                    {
                        "error": {
                            "message": "Unsupported max_tokens; "
                            + key
                            + " Bearer other-secret sk-or-v1-secret\nnext",
                            "param": "max_tokens",
                            "code": "unsupported_parameter",
                        },
                        "headers": {"secret": "DO_NOT_LOG_HEADERS"},
                    }
                ),
            },
        }
    }

    async def respond(request):
        return httpx.Response(400, json=payload)

    client = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(respond)),
    )
    with pytest.raises(providers.ProviderError) as error:
        asyncio.run(
            providers.request(
                "https://provider.invalid", {}, key, diagnostics=diagnostics
            )
        )
    assert error.value.status == 400 and "Unsupported" not in str(error.value)
    detail = error.value.diagnostic
    assert (
        key not in detail
        and "other-secret" not in detail
        and "sk-or-v1-secret" not in detail
        and "DO_NOT_LOG_HEADERS" not in detail
    )
    if diagnostics:
        assert (
            "Unsupported max_tokens" in detail
            and "provider=Example" in detail
            and "\n" not in detail
        )
    else:
        assert detail == ""


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, text="<html>error</html>"),
        httpx.Response(400, json=[]),
        httpx.Response(400, json={"error": "bad request"}),
        httpx.Response(400, json={"error": {"message": "x" * 5000}}),
    ],
)
def test_diagnostics_handle_unstructured_and_long_errors(response):
    assert 0 < len(providers.provider_diagnostic(response, "key")) <= 1200


@pytest.mark.parametrize("fail_work", [False, True])
def test_live_smoke_checks_both_models_and_exa_and_cleans_up(
    monkeypatch, capsys, fail_work
):
    from app import accounts, core

    class Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args):
            return self

        def raise_for_status(self):
            pass

    monkeypatch.setattr(operations.httpx, "AsyncClient", Client)
    calls = []

    async def broker(task, op, body=None):
        calls.append(op)
        if op == "run":
            return {
                "exit_code": 0,
                "output": "SMOKE_OK EGRESS_BLOCKED REGISTRY_OK UNLISTED_BLOCKED",
            }
        if op == "file":
            return {"content": "OwnCMD smoke test"}
        if op == "snapshot":
            return {"data": "snapshot"}
        if op == "action":
            return {"elements": []}
        if op == "frame":
            return {"image": "x" * 150}
        return {}

    async def public(task):
        return "https://registry.npmjs.org/express/latest"

    async def catalog():
        return {
            name: {"supported_parameters": ["tools"]}
            for name in ["chat-model", "work-model"]
        }

    requests = []

    async def request(url, body, *args, **kwargs):
        requests.append(body.get("model", "exa"))
        if fail_work and body.get("model") == "work-model":
            raise providers.ProviderError("Rejected", 400, "Unsupported parameter")
        return {"results": [{}]} if "exa.ai" in url else completed()

    monkeypatch.setattr(operations, "broker", broker)
    monkeypatch.setattr(operations, "public_browser_smoke", public)
    monkeypatch.setattr(operations, "catalog", catalog)
    monkeypatch.setattr(operations, "request", request)
    monkeypatch.setattr(
        accounts, "resolve_model", lambda owner, mode, choice="auto": mode + "-model"
    )
    if fail_work:
        with pytest.raises(RuntimeError, match="work-model failed"):
            asyncio.run(operations.smoke(True))
    else:
        asyncio.run(operations.smoke(True))
    assert (
        requests
        == (
            ["chat-model", "work-model"]
            if fail_work
            else ["chat-model", "work-model", "exa"]
        )
        and calls[-1] == "stop"
    )
    with core.db() as c:
        assert c.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    assert ("Smoke checks passed." in capsys.readouterr().out) == (not fail_work)
