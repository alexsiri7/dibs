import base64
import hashlib
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
import respx

from dibs import app, oauth

SECRET = "s" * 48
OWNER = "owner@example.com"
BASE = "https://dibs.example"
CLIENT_REDIRECT = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "v" * 64


@pytest.fixture
def oauth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(oauth.SECRET_KEY, SECRET)
    monkeypatch.setenv(oauth.ALLOWED_EMAIL, OWNER)
    monkeypatch.setenv(oauth.GOOGLE_CLIENT_ID, "google-client")
    monkeypatch.setenv(oauth.GOOGLE_CLIENT_SECRET, "google-secret")
    monkeypatch.setenv(oauth.PUBLIC_BASE_URL, BASE)


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app.build_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def google_id_token(email: str, verified: bool = True) -> str:
    return jwt.encode(
        {"sub": "g-123", "email": email, "email_verified": verified},
        "google" * 8,
        algorithm="HS256",
    )


def challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def register(client: httpx.AsyncClient) -> str:
    response = await client.post("/oauth/register", json={"redirect_uris": [CLIENT_REDIRECT]})
    assert response.status_code == 201
    return response.json()["client_id"]


async def sign_in(client: httpx.AsyncClient) -> httpx.Response:
    """Register, authorize and come back from Google; return the callback response."""
    client_id = await register(client)
    authorize = await client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CLIENT_REDIRECT,
            "state": "client-state",
            "code_challenge": challenge(VERIFIER),
            "code_challenge_method": "S256",
        },
    )
    assert authorize.status_code == 302
    location = urlparse(authorize.headers["location"])
    assert location.netloc == "accounts.google.com"
    state = parse_qs(location.query)["state"][0]
    return await client.get("/oauth/callback", params={"code": "g", "state": state})


def issued_code(callback: httpx.Response) -> str:
    assert callback.status_code == 302
    location = callback.headers["location"]
    assert location.startswith(CLIENT_REDIRECT + "?")
    query = parse_qs(urlparse(location).query)
    assert query["state"] == ["client-state"]
    return query["code"][0]


def token_form(code: str, verifier: str = VERIFIER) -> dict[str, str]:
    return {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": CLIENT_REDIRECT,
        "code_verifier": verifier,
    }


async def test_health_is_public_and_offline(
    client: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_mcp_without_token_is_401_with_resource_metadata(
    oauth_env: None, client: httpx.AsyncClient
) -> None:
    response = await client.post("/mcp", json={})

    assert response.status_code == 401
    assert (
        f'resource_metadata="{BASE}/.well-known/oauth-protected-resource"'
        in response.headers["www-authenticate"]
    )


def expired_access_token() -> str:
    now = int(time.time())
    claims = {"sub": "g-123", "email": OWNER, "typ": "access", "iat": now - 20, "exp": now - 10}
    return jwt.encode(claims, SECRET, algorithm="HS256")


@pytest.mark.parametrize(
    ("make_token", "unset_allowed_email"),
    [
        pytest.param(lambda: "garbage", False, id="garbage"),
        pytest.param(
            lambda: jwt.encode(
                {"sub": "g-123", "email": OWNER, "typ": "access"}, "k" * 48, algorithm="HS256"
            ),
            False,
            id="other-key",
        ),
        pytest.param(expired_access_token, False, id="expired"),
        pytest.param(
            lambda: oauth.create_access_token("g-9", "someone@else.com"), False, id="other-email"
        ),
        pytest.param(lambda: oauth.create_refresh_token("g-123", OWNER), False, id="refresh"),
        pytest.param(
            lambda: oauth.create_access_token("g-123", OWNER), True, id="allowed-email-unset"
        ),
    ],
)
async def test_mcp_rejects_bad_tokens(
    oauth_env: None,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    make_token,
    unset_allowed_email: bool,
) -> None:
    token = make_token()
    if unset_allowed_email:
        monkeypatch.delenv(oauth.ALLOWED_EMAIL)

    response = await client.post("/mcp", json={}, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


async def test_valid_token_reaches_mcp(oauth_env: None) -> None:
    calls = []

    async def stub(scope, receive, send) -> None:
        calls.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    transport = httpx.ASGITransport(app=app.require_auth(stub))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        token = oauth.create_access_token("g-123", OWNER)
        response = await c.post("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert calls == ["/mcp"]


async def test_discovery_metadata(oauth_env: None, client: httpx.AsyncClient) -> None:
    resource = (await client.get("/.well-known/oauth-protected-resource")).json()
    server = (await client.get("/.well-known/oauth-authorization-server")).json()

    assert resource["resource"] == f"{BASE}/mcp"
    assert resource["authorization_servers"] == [BASE]
    assert server["issuer"] == BASE
    assert server["authorization_endpoint"] == f"{BASE}/oauth/authorize"
    assert server["token_endpoint"] == f"{BASE}/oauth/token"
    assert server["registration_endpoint"] == f"{BASE}/oauth/register"
    assert server["code_challenge_methods_supported"] == ["S256"]


async def test_sign_in_flow_for_allowed_account(
    oauth_env: None, client: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(oauth.GOOGLE_TOKEN_URL).respond(
        json={"id_token": google_id_token("Owner@Example.com")}
    )

    code = issued_code(await sign_in(client))
    tokens = await client.post("/oauth/token", data=token_form(code))

    assert tokens.status_code == 200
    assert oauth.verify_access_token(tokens.json()["access_token"])

    refreshed = await client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": tokens.json()["refresh_token"]},
    )
    assert refreshed.status_code == 200
    assert oauth.verify_access_token(refreshed.json()["access_token"])

    reused = await client.post("/oauth/token", data=token_form(code))
    assert reused.status_code == 400
    assert reused.json()["error"] == "invalid_grant"


@pytest.mark.parametrize(
    "id_token",
    [
        pytest.param(google_id_token("someone@else.com"), id="other-account"),
        pytest.param(google_id_token(OWNER, verified=False), id="unverified-email"),
    ],
)
async def test_other_google_accounts_are_refused(
    oauth_env: None, client: httpx.AsyncClient, respx_mock: respx.MockRouter, id_token: str
) -> None:
    respx_mock.post(oauth.GOOGLE_TOKEN_URL).respond(json={"id_token": id_token})

    callback = await sign_in(client)

    assert callback.status_code == 403
    assert "location" not in callback.headers
    assert oauth._auth_codes == {}


async def test_token_rejects_wrong_pkce_verifier(
    oauth_env: None, client: httpx.AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(oauth.GOOGLE_TOKEN_URL).respond(json={"id_token": google_id_token(OWNER)})
    code = issued_code(await sign_in(client))

    response = await client.post("/oauth/token", data=token_form(code, verifier="w" * 64))

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


@pytest.mark.parametrize("problem", ["unregistered-redirect", "forged-client"])
async def test_authorize_rejects_unregistered_redirect_or_forged_client(
    oauth_env: None, client: httpx.AsyncClient, problem: str
) -> None:
    client_id = await register(client)
    redirect_uri = CLIENT_REDIRECT
    if problem == "unregistered-redirect":
        redirect_uri = "https://evil.example/callback"
    else:
        client_id = jwt.encode(
            {"typ": "client", "redirect_uris": [CLIENT_REDIRECT]}, "k" * 48, algorithm="HS256"
        )

    response = await client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge(VERIFIER),
            "code_challenge_method": "S256",
        },
    )

    assert response.status_code == 400
    assert "location" not in response.headers


async def test_oauth_endpoints_report_missing_config(
    oauth_env: None, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = await register(client)
    monkeypatch.delenv(oauth.GOOGLE_CLIENT_ID)

    response = await client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": CLIENT_REDIRECT,
            "code_challenge": challenge(VERIFIER),
        },
    )

    assert response.status_code == 503
    assert oauth.GOOGLE_CLIENT_ID in response.json()["error_description"]
