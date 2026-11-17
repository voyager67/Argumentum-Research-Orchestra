import pytest

from argumentum.server.middleware import UploadBodyLimitMiddleware


@pytest.mark.anyio
async def test_upload_requires_token_before_body_parsing():
    called = []
    messages = []

    async def app(scope, receive, send):
        called.append(True)

    async def receive():
        return {"type": "http.request", "body": b"large"}

    async def send(message):
        messages.append(message)

    middleware = UploadBodyLimitMiddleware(app, max_body_bytes=2, expected_bearer_token="secret")
    await middleware(
        {"type": "http", "method": "POST", "path": "/api/v1/runs/with-materials", "headers": []}, receive, send
    )
    assert not called and messages[0]["status"] == 401
