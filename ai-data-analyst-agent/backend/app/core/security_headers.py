"""HTTP security headers on every API response.

The API only returns JSON and file downloads, so it can use the strictest policy: nothing in a response may load
scripts, styles or frames, and no other site may embed it. Responses hold private data, so browsers and proxies
are told not to store them unless a route says otherwise.
"""
from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

BASE = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "X-Permitted-Cross-Domain-Policies": "none",
}
HSTS = "max-age=31536000; includeSubDomains"
DOCS_PATHS = ("/api/docs",)  # development only; Swagger UI needs its own scripts


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        docs = scope.get("path", "").startswith(DOCS_PATHS)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                for k, v in BASE.items():
                    if docs and k == "Content-Security-Policy":
                        continue
                    h.setdefault(k, v)
                h.setdefault("Cache-Control", "no-store")
                if self.hsts:
                    h.setdefault("Strict-Transport-Security", HSTS)
                if "server" in h:
                    del h["server"]
            await send(message)

        await self.app(scope, receive, send_with_headers)
