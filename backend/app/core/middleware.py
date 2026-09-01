"""Общие HTTP middleware; tenant/RLS-контекст появится на шаге auth."""

import gzip
from io import BytesIO

from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class OneCGzipRequestMiddleware:
    """Bounded gzip decoding for large, repetitive 1C JSON batches only."""

    MAX_DECOMPRESSED_BYTES = 9 * 1024 * 1024
    MAX_COMPRESSED_BYTES = 8 * 1024 * 1024

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = dict(scope.get("headers", []))
        is_one_c_push = scope.get("path", "").endswith("/integrations/1c/push")
        if (
            scope["type"] != "http"
            or not is_one_c_push
            or headers.get(b"content-encoding", b"").lower() != b"gzip"
        ):
            await self.app(scope, receive, send)
            return

        compressed = bytearray()
        while True:
            message = await receive()
            compressed.extend(message.get("body", b""))
            if len(compressed) > self.MAX_COMPRESSED_BYTES:
                compressed = bytearray()
                break
            if not message.get("more_body", False):
                break
        try:
            with gzip.GzipFile(fileobj=BytesIO(compressed), mode="rb") as stream:
                body = stream.read(self.MAX_DECOMPRESSED_BYTES + 1)
            if len(body) > self.MAX_DECOMPRESSED_BYTES:
                raise ValueError("decompressed request is too large")
        except (OSError, EOFError, ValueError):
            response = (
                b'{"error":{"code":"INVALID_GZIP_BODY",'
                b'"message":"Invalid or oversized gzip request","details":null}}'
            )
            await send(
                {
                    "type": "http.response.start",
                    "status": 400,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(response)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": response})
            return

        new_headers = [
            (name, value)
            for name, value in scope.get("headers", [])
            if name.lower() not in {b"content-encoding", b"content-length"}
        ]
        new_headers.append((b"content-length", str(len(body)).encode("ascii")))
        scope = {**scope, "headers": new_headers}
        delivered = False

        async def receive_decompressed() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, receive_decompressed, send)


class RequestIdMiddleware:
    """Принимает или создаёт request id и возвращает его клиенту."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-request-id", b"").decode("latin-1") or str(uuid4())

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, send_with_request_id)
