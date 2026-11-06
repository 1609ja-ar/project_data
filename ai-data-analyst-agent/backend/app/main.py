"""FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import router as api_router
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import RequestIdMiddleware, setup_logging
from app.core.ratelimit import GeneralLimit, limiter
from app.core.security_headers import SecurityHeadersMiddleware
from app.db import mongo
from app.services.datasets import recover_interrupted
from app.services.jobs import shutdown_executor


@asynccontextmanager
async def lifespan(app: FastAPI):
    await mongo.connect()
    await recover_interrupted()
    yield
    shutdown_executor()
    await mongo.close()


LEGACY_COOKIES = [("access_token", "/"), ("csrf_token", "/"), ("refresh_token", "/api/auth")]


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()
    problems = settings.production_problems()
    if problems:
        raise RuntimeError("Unsafe production settings in backend/.env:\n- " + "\n- ".join(problems))
    prod = settings.is_production
    # debug=False: errors never return stack traces. The interactive docs and the API schema exist only outside production.
    app = FastAPI(title=settings.app_name, lifespan=lifespan, debug=False,
                  docs_url=None if prod else "/api/docs", redoc_url=None, openapi_url=None if prod else "/api/openapi.json")
    app.state.limiter = limiter
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=prod)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Requested-With", "Authorization", "X-Request-ID"],
        max_age=600,
    )
    if settings.allowed_host_list:
        # Added last so it runs first: requests with an unexpected Host header are refused before anything else.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)

    @app.middleware("http")
    async def drop_legacy_auth_cookies(request, call_next):
        # Browsers that signed in before sessions replaced JWTs still hold these cookies; they do nothing now,
        # so they are deleted on the next request instead of lingering until they expire.
        response = await call_next(request)
        for name, path in LEGACY_COOKIES:
            if name in request.cookies:
                response.delete_cookie(name, path=path, secure=settings.secure_cookies, samesite="lax")
        return response

    install_error_handlers(app)
    app.include_router(api_router, prefix="/api", dependencies=[GeneralLimit])
    return app


app = create_app()
