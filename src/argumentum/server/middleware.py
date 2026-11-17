"""Small ASGI security middleware for bounded multipart request bodies."""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from typing import Any

ASGIMessage = dict[str, Any]
ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
ASGISend = Callable[[ASGIMessage], Awaitable[None]]


class RequestBodyTooLarge(Exception):
    """Raised internally when an upload exceeds the configured request limit."""


class UploadBodyLimitMiddleware:
    """Bound upload request bodies before Starlette parses/spools multipart files."""

    def __init__(self, app: Callable[..., Awaitable[None]], *, max_body_bytes: int, expected_bearer_token: str = "", token_validator: Callable[[str], bool] | None = None, path: str = "/api/v1/runs/with-materials") -> None:
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.expected_bearer_token = expected_bearer_token
        self.token_validator = token_validator
        self.path = path

    async def __call__(self, scope: dict[str, Any], receive: ASGIReceive, send: ASGISend) -> None:
        if scope.get("type") != "http" or scope.get("method") != "POST" or scope.get("path") != self.path:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        scheme, separator, supplied_token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer":
            await self._respond(send, 401, "Invalid or missing bearer token")
            return
        if self.token_validator is not None:
            try:
                import anyio
                valid_token = await anyio.to_thread.run_sync(self.token_validator, supplied_token)
            except Exception:
                valid_token = False
            configured = True
        else:
            configured = bool(self.expected_bearer_token)
            valid_token = configured and hmac.compare_digest(supplied_token, self.expected_bearer_token)
        if not configured:
            await self._respond(send, 503, "No API credentials are configured")
            return
        if not valid_token:
            await self._respond(send, 401, "Invalid or missing bearer token")
            return
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                content_length = int(raw_length)
            except ValueError:
                content_length = None
            if content_length is not None and content_length > self.max_body_bytes:
                await self._reject(send)
                return
        received = 0
        response_started = False
        async def limited_receive() -> ASGIMessage:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise RequestBodyTooLarge
            return message
        async def tracking_send(message: ASGIMessage) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)
        try:
            await self.app(scope, limited_receive, tracking_send)
        except RequestBodyTooLarge:
            if not response_started:
                await self._reject(send)

    async def _reject(self, send: ASGISend) -> None:
        await self._respond(send, 413, "Upload request body exceeds the configured limit")

    async def _respond(self, send: ASGISend, status: int, detail: str) -> None:
        import json
        body = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))]})
        await send({"type": "http.response.body", "body": body})
