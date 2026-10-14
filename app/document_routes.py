import asyncio, contextlib
from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse
from . import documents, core, accounts


def register(app, auth, task):
    @app.on_event("startup")
    async def start():
        app.state.document_queue = asyncio.create_task(documents.queue_loop())

    @app.on_event("shutdown")
    async def stop():
        job = getattr(app.state, "document_queue", None)
        if job:
            job.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await job

    @app.post("/api/attachments")
    async def create(req: Request):
        return documents.create(auth(req), await req.json())

    @app.get("/api/attachments/{id}")
    def status(req: Request, id: str):
        owner = auth(req)
        r = documents.owned(owner, id)
        with core.db() as c:
            parts = [
                x["ordinal"]
                for x in c.execute(
                    "SELECT ordinal FROM document_parts WHERE document=%s", (id,)
                )
            ]
        return {**documents.public(r), "parts": parts}

    @app.put("/api/attachments/{id}/parts/{ordinal}")
    async def part(req: Request, id: str, ordinal: int):
        owner = auth(req)
        documents.owned(owner, id)
        data = bytearray()
        async for chunk in req.stream():
            if len(data) + len(chunk) > documents.PART:
                raise HTTPException(413, "Upload part is too large")
            data.extend(chunk)
        return await asyncio.to_thread(documents.put, owner, id, ordinal, bytes(data))

    @app.post("/api/attachments/{id}/complete")
    def complete(req: Request, id: str):
        return documents.finish(auth(req), id)

    @app.delete("/api/attachments/{id}")
    def delete(req: Request, id: str):
        documents.remove(auth(req), id)
        return {"ok": True}

    @app.get("/api/attachments/{id}/download")
    def download(req: Request, id: str):
        from urllib.parse import quote

        r = documents.owned(auth(req), id)
        if r["received"] != r["size"]:
            raise HTTPException(409, "Upload is incomplete")
        return StreamingResponse(
            documents.bytes_iter(r),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(core.dec(r["name"]), safe=""),
                "Content-Length": str(r["size"]),
            },
        )

    @app.get("/api/tasks/{id}/attachments")
    def listing(req: Request, id: str):
        r = task(req, id)
        return {"attachments": documents.listing(r["owner"], id)}

    @app.delete("/api/tasks/{id}/attachments/{document}")
    def detach(req: Request, id: str, document: str):
        r = task(req, id)
        documents.owned(r["owner"], document)
        raise HTTPException(
            409,
            "Sent attachments remain part of the conversation. Unsent uploads can still be removed.",
        )
