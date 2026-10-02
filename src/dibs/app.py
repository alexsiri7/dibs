"""The MCP server over Streamable HTTP, with `/mcp` behind OAuth bearer tokens."""

import os

import uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from dibs import oauth
from dibs.server import mcp

PUBLIC_PREFIXES = ("/.well-known/", "/oauth/")


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> Response:
    return JSONResponse({"status": "ok"})


def _is_public(path: str) -> bool:
    return path == "/health" or path.startswith(PUBLIC_PREFIXES)


def _bearer_token(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            return token.strip() if scheme.lower() == "bearer" else None
    return None


def _challenge() -> str:
    base = os.environ.get(oauth.PUBLIC_BASE_URL, "").rstrip("/")
    if not base:
        return 'Bearer error="invalid_token"'
    return (
        f'Bearer error="invalid_token", '
        f'resource_metadata="{base}/.well-known/oauth-protected-resource"'
    )


def require_auth(app: ASGIApp) -> ASGIApp:
    """Let only requests with a valid access token past, except to the public paths."""

    async def gate(scope: Scope, receive: Receive, send: Send) -> None:
        # Lifespan must reach the app so the MCP session manager starts.
        if scope["type"] != "http" or _is_public(scope["path"]):
            await app(scope, receive, send)
            return
        token = _bearer_token(scope)
        if token and oauth.verify_access_token(token):
            await app(scope, receive, send)
            return
        response = JSONResponse(
            {"error": "unauthorized"}, status_code=401, headers={"www-authenticate": _challenge()}
        )
        await response(scope, receive, send)

    return gate


def build_app() -> ASGIApp:
    return require_auth(mcp.streamable_http_app())


def main() -> None:
    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
