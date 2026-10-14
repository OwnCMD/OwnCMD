"""Authenticated streaming relays; never allocate or renew a runtime."""

import time, anyio
import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

MEDIA = "application/x-owncmd-frames"


async def relay(url, headers, check):
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(12, connect=5), headers=headers, trust_env=False
    )
    try:
        upstream = await client.send(client.build_request("GET", url), stream=True)
        if upstream.status_code != 200:
            status = upstream.status_code
            await upstream.aclose()
            raise HTTPException(
                status if 400 <= status < 600 else 502, "Preview stream unavailable"
            )
        if upstream.headers.get("content-type", "").split(";")[0] != MEDIA:
            await upstream.aclose()
            raise HTTPException(502, "Invalid preview stream")
    except BaseException:
        await client.aclose()
        raise

    async def close():
        with anyio.move_on_after(3, shield=True):
            try:
                await upstream.aclose()
            finally:
                await client.aclose()

    class RelayResponse(StreamingResponse):
        async def __call__(self, scope, receive, send):
            try:
                await super().__call__(scope, receive, send)
            finally:
                await close()

    async def chunks():
        checked = 0
        try:
            async for chunk in upstream.aiter_raw():
                if time.monotonic() - checked >= 2:
                    try:
                        check()
                    except HTTPException:
                        return
                    checked = time.monotonic()
                yield chunk
        finally:
            await close()

    return RelayResponse(
        chunks(),
        media_type=MEDIA,
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )
