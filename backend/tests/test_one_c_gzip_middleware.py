import gzip

import pytest

from app.core.middleware import OneCGzipRequestMiddleware


@pytest.mark.asyncio
async def test_one_c_gzip_request_is_decompressed_before_routing() -> None:
    original = b'{"entity":"Catalog_Test","records":[{"Ref_Key":"1"}]}'
    request_messages = [
        {
            "type": "http.request",
            "body": gzip.compress(original),
            "more_body": False,
        }
    ]
    routed_bodies = []

    async def receive():
        return request_messages.pop(0)

    async def send(_message):
        return None

    async def routed_app(_scope, routed_receive, _send):
        routed_bodies.append((await routed_receive())["body"])

    middleware = OneCGzipRequestMiddleware(routed_app)
    await middleware(
        {
            "type": "http",
            "path": "/api/v1/integrations/1c/push",
            "headers": [
                (b"content-encoding", b"gzip"),
                (b"content-length", b"123"),
            ],
        },
        receive,
        send,
    )

    assert routed_bodies == [original]
