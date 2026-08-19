from __future__ import annotations

import hmac
import os
import sys

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

TOKEN_ENV_VAR = "PHAROS_RAG_ENGINE_TOKEN"

EXEMPT_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})

UNSET_WARNING = (
    f"WARNING: {TOKEN_ENV_VAR} unset - auth disabled, for local dev only"
)


def install_bearer_auth(app: FastAPI) -> str | None:
    expected_token = (os.getenv(TOKEN_ENV_VAR) or "").strip() or None

    if expected_token is None:
        print(UNSET_WARNING, file=sys.stderr, flush=True)

    @app.middleware("http")
    async def bearer_auth(request: Request, call_next):
        if expected_token is None or request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")

        if scheme.lower() != "bearer" or not hmac.compare_digest(
            presented.encode("utf-8"), expected_token.encode("utf-8")
        ):
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        return await call_next(request)

    return expected_token