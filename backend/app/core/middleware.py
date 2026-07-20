"""Общие HTTP middleware; tenant/RLS-контекст появится на шаге auth."""

from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send


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
