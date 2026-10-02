"""OAuth 2.1 for the hosted MCP server, signing in with one Google account.

Implements the MCP Authorization spec
(https://modelcontextprotocol.io/specification/draft/basic/authorization):

  - GET  /.well-known/oauth-protected-resource     (RFC 9728)
  - GET  /.well-known/oauth-authorization-server   (RFC 8414)
  - POST /oauth/register                            (RFC 7591)
  - GET  /oauth/authorize  → 302 to Google sign-in
  - GET  /oauth/callback   ← Google redirects back with an auth code
  - POST /oauth/token      → issues HS256 JWT access and refresh tokens

Only the Google account named by ALLOWED_EMAIL gets a token; with ALLOWED_EMAIL unset nobody
does. Client IDs and refresh tokens are signed JWTs so they survive a redeploy; pending logins
and authorization codes live in memory for a few minutes.
"""

import base64
import functools
import hashlib
import logging
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from dibs.server import mcp

logger = logging.getLogger(__name__)

SECRET_KEY = "SECRET_KEY"
ALLOWED_EMAIL = "ALLOWED_EMAIL"
PUBLIC_BASE_URL = "PUBLIC_BASE_URL"
GOOGLE_CLIENT_ID = "GOOGLE_CLIENT_ID"
GOOGLE_CLIENT_SECRET = "GOOGLE_CLIENT_SECRET"

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

ACCESS_TOKEN_TTL = 60 * 60 * 24 * 7
REFRESH_TOKEN_TTL = 60 * 60 * 24 * 30
PENDING_TTL = 60 * 10
MAX_PENDING = 1000

SCOPE = "mcp"


class NotConfiguredError(Exception):
    """A required environment variable is unset."""


class StoreFullError(Exception):
    """Too many logins are in progress."""


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise NotConfiguredError(name)
    return value


def _base_url() -> str:
    return _env(PUBLIC_BASE_URL).rstrip("/")


Handler = Callable[[Request], Awaitable[Response]]


def _unavailable_as_503(handler: Handler) -> Handler:
    @functools.wraps(handler)
    async def wrapper(request: Request) -> Response:
        try:
            return await handler(request)
        except NotConfiguredError as exc:
            description = f"{exc.args[0]} is not set"
        except StoreFullError:
            description = "Too many sign-ins in progress; try again shortly"
        return JSONResponse(
            {"error": "server_error", "error_description": description}, status_code=503
        )

    return wrapper


_pending_logins: dict[str, dict[str, Any]] = {}
_auth_codes: dict[str, dict[str, Any]] = {}


def _purge_expired(store: dict[str, dict[str, Any]]) -> None:
    now = time.time()
    for key in [k for k, v in store.items() if v["expires_at"] <= now]:
        del store[key]


def _store(store: dict[str, dict[str, Any]], key: str, value: dict[str, Any]) -> None:
    _purge_expired(store)
    if len(store) >= MAX_PENDING:
        raise StoreFullError
    store[key] = {**value, "expires_at": time.time() + PENDING_TTL}


def _take(store: dict[str, dict[str, Any]], key: str) -> dict[str, Any] | None:
    _purge_expired(store)
    return store.pop(key, None)


def _email_allowed(email: str) -> bool:
    return email.casefold() == _env(ALLOWED_EMAIL).casefold()


def _create_token(sub: str, email: str, typ: str, ttl: int) -> str:
    now = int(time.time())
    claims = {"sub": sub, "email": email, "typ": typ, "iat": now, "exp": now + ttl}
    return jwt.encode(claims, _env(SECRET_KEY), algorithm="HS256")


def create_access_token(sub: str, email: str) -> str:
    return _create_token(sub, email, "access", ACCESS_TOKEN_TTL)


def create_refresh_token(sub: str, email: str) -> str:
    return _create_token(sub, email, "refresh", REFRESH_TOKEN_TTL)


def _signed_claims(token: str, typ: str) -> dict[str, Any] | None:
    try:
        claims = jwt.decode(token, _env(SECRET_KEY), algorithms=["HS256"])
    except (jwt.PyJWTError, NotConfiguredError):
        return None
    return claims if claims.get("typ") == typ else None


def _user_claims(token: str, typ: str) -> dict[str, Any] | None:
    claims = _signed_claims(token, typ)
    if claims is None or not _email_allowed(str(claims.get("email", ""))):
        return None
    return claims


def verify_access_token(token: str) -> dict[str, Any] | None:
    try:
        return _user_claims(token, "access")
    except NotConfiguredError:
        return None


def _pkce_s256(verifier: str) -> str:
    """``BASE64URL(SHA256(verifier))`` with no padding (RFC 7636 §4.6)."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _token_response(sub: str, email: str, scope: str) -> JSONResponse:
    return JSONResponse(
        {
            "access_token": create_access_token(sub, email),
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_TTL,
            "refresh_token": create_refresh_token(sub, email),
            "scope": scope,
        },
        headers={"Cache-Control": "no-store"},
    )


def _token_error(error: str, description: str) -> JSONResponse:
    """RFC 6749 §5.2 error response."""
    return JSONResponse({"error": error, "error_description": description}, status_code=400)


def _bad_request(description: str) -> JSONResponse:
    return JSONResponse(
        {"error": "invalid_request", "error_description": description}, status_code=400
    )


async def exchange_google_code(code: str, redirect_uri: str) -> dict[str, str] | None:
    """Exchange a Google auth code; return ``{"sub", "email"}`` only for the allowed account."""
    data = {
        "code": code,
        "client_id": _env(GOOGLE_CLIENT_ID),
        "client_secret": _env(GOOGLE_CLIENT_SECRET),
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(GOOGLE_TOKEN_URL, data=data)
        if response.status_code != 200:
            logger.warning("Google token exchange returned %s", response.status_code)
            return None
        id_token = response.json().get("id_token")
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.warning("Google token exchange failed: %s", type(exc).__name__)
        return None
    if not id_token:
        logger.warning("Google token response has no id_token")
        return None
    try:
        # Unverified is safe only because this came straight from Google's token endpoint over
        # TLS (OIDC Core §3.1.3.7). Never accept an id_token from the client.
        claims = jwt.decode(id_token, options={"verify_signature": False})
    except jwt.PyJWTError:
        logger.warning("Google id_token could not be decoded")
        return None
    sub, email = claims.get("sub"), claims.get("email")
    if not sub or not email:
        logger.warning("Google id_token lacks sub or email")
        return None
    if claims.get("email_verified") is not True or not _email_allowed(email):
        logger.warning("Refused sign-in for %s", email)
        return None
    return {"sub": str(sub), "email": str(email)}


def _allowed_redirect_uri(uri: Any) -> bool:
    return isinstance(uri, str) and uri.startswith(
        ("https://", "http://localhost", "http://127.0.0.1")
    )


def _registered_redirect_uris(client_id: str) -> list[str]:
    claims = _signed_claims(client_id, "client")
    return claims.get("redirect_uris", []) if claims else []


@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
@_unavailable_as_503
async def protected_resource_metadata(_request: Request) -> Response:
    base = _base_url()
    return JSONResponse(
        {
            "resource": f"{base}/mcp",
            "authorization_servers": [base],
            "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"],
        }
    )


@mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
@_unavailable_as_503
async def authorization_server_metadata(_request: Request) -> Response:
    base = _base_url()
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": [SCOPE],
        }
    )


@mcp.custom_route("/oauth/register", methods=["POST"])
@_unavailable_as_503
async def register(request: Request) -> Response:
    try:
        body = await request.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    redirect_uris = body.get("redirect_uris")
    if (
        not isinstance(redirect_uris, list)
        or not redirect_uris
        or not all(_allowed_redirect_uri(uri) for uri in redirect_uris)
    ):
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)
    client_id = jwt.encode(
        {"typ": "client", "redirect_uris": redirect_uris, "iat": int(time.time())},
        _env(SECRET_KEY),
        algorithm="HS256",
    )
    return JSONResponse(
        {
            "client_id": client_id,
            # Issued for compatibility with how Claude.ai registers, but never stored or checked:
            # PKCE, redirect_uri binding and ALLOWED_EMAIL are what protect the flow.
            "client_secret": secrets.token_urlsafe(32),
            "redirect_uris": redirect_uris,
            "client_name": body.get("client_name", ""),
            "grant_types": body.get("grant_types", ["authorization_code", "refresh_token"]),
            "response_types": body.get("response_types", ["code"]),
            "token_endpoint_auth_method": body.get("token_endpoint_auth_method", "none"),
            "scope": body.get("scope", SCOPE),
        },
        status_code=201,
    )


@mcp.custom_route("/oauth/authorize", methods=["GET"])
@_unavailable_as_503
async def authorize(request: Request) -> Response:
    _env(SECRET_KEY)
    google_client_id = _env(GOOGLE_CLIENT_ID)
    base = _base_url()

    params = request.query_params
    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")
    code_challenge = params.get("code_challenge", "")
    if params.get("response_type", "code") != "code":
        return _bad_request("Only response_type=code is supported")
    if not code_challenge or params.get("code_challenge_method", "S256") != "S256":
        return _bad_request("PKCE with code_challenge_method=S256 is required")
    if not redirect_uri or redirect_uri not in _registered_redirect_uris(client_id):
        return _bad_request("Unknown client_id or unregistered redirect_uri")

    flow_key = secrets.token_urlsafe(32)
    _store(
        _pending_logins,
        flow_key,
        {
            "client_state": params.get("state"),
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "client_id": client_id,
            "scope": params.get("scope", SCOPE),
        },
    )
    google_params = {
        "client_id": google_client_id,
        "redirect_uri": f"{base}/oauth/callback",
        "response_type": "code",
        "scope": "openid email",
        "state": flow_key,
        "prompt": "select_account",
    }
    return RedirectResponse(f"{GOOGLE_AUTHORIZE_URL}?{urlencode(google_params)}", status_code=302)


@mcp.custom_route("/oauth/callback", methods=["GET"])
@_unavailable_as_503
async def callback(request: Request) -> Response:
    base = _base_url()
    params = request.query_params
    if params.get("error"):
        return _bad_request(f"Google sign-in failed: {params['error']}")
    code, state = params.get("code"), params.get("state")
    if not code or not state:
        return _bad_request("code and state are required")
    login = _take(_pending_logins, state)
    if login is None:
        return _bad_request("Invalid or expired login")

    user = await exchange_google_code(code, f"{base}/oauth/callback")
    if user is None:
        return JSONResponse(
            {
                "error": "access_denied",
                "error_description": "This Google account is not allowed to use Dibs",
            },
            status_code=403,
        )

    auth_code = secrets.token_urlsafe(32)
    _store(
        _auth_codes,
        auth_code,
        {
            **user,
            "code_challenge": login["code_challenge"],
            "redirect_uri": login["redirect_uri"],
            "client_id": login["client_id"],
            "scope": login["scope"],
        },
    )
    redirect_params = {"code": auth_code}
    if login["client_state"] is not None:
        redirect_params["state"] = login["client_state"]
    separator = "&" if "?" in login["redirect_uri"] else "?"
    return RedirectResponse(
        f"{login['redirect_uri']}{separator}{urlencode(redirect_params)}", status_code=302
    )


@mcp.custom_route("/oauth/token", methods=["POST"])
@_unavailable_as_503
async def token(request: Request) -> Response:
    _env(SECRET_KEY)
    form = await request.form()
    grant_type = str(form.get("grant_type", ""))

    if grant_type == "refresh_token":
        claims = _user_claims(str(form.get("refresh_token", "")), "refresh")
        if claims is None:
            return _token_error("invalid_grant", "Invalid or expired refresh_token")
        return _token_response(claims["sub"], claims["email"], SCOPE)

    if grant_type != "authorization_code":
        return _token_error("unsupported_grant_type", f"Unsupported grant_type: {grant_type}")

    grant = _take(_auth_codes, str(form.get("code", "")))
    if grant is None:
        return _token_error("invalid_grant", "Invalid or expired authorization code")
    if str(form.get("redirect_uri", "")) != grant["redirect_uri"]:
        return _token_error("invalid_grant", "redirect_uri mismatch")
    client_id = form.get("client_id")
    if client_id and str(client_id) != grant["client_id"]:
        return _token_error("invalid_grant", "client_id mismatch")
    verifier = str(form.get("code_verifier", ""))
    if not verifier or _pkce_s256(verifier) != grant["code_challenge"]:
        return _token_error("invalid_grant", "PKCE verification failed")
    return _token_response(grant["sub"], grant["email"], grant["scope"])
