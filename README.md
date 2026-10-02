# Dibs

Check a shortlist of candidate business names in one go before you commit to one.

For each name, Dibs looks at:

- **Companies House** — applying the "same as" comparison rules (case, spacing, punctuation, "Ltd"/"Limited" and web endings ignored), plus near matches.
- **Domains** — via RDAP, for configurable endings (default `.com`, `.co.uk`, `.ai`, `.io`).
- **UK trademarks** — classes 9 and 42 (software), or a manual-check link where no reliable automated search exists.

When a name is taken at Companies House, Dibs also tries suffix variants (default "Labs", "Studio"), each with its own verdict. Every name gets a verdict — clear, conflict, or check manually — with evidence and links.

Dibs runs as an MCP server so Claude can check names during a brainstorm. See issue #1 for the spec.

## Read-only guarantee

Dibs only ever reads public registers. It never registers, buys, reserves or otherwise acts on any company name, domain or trademark.

## Status

The MCP server exposes one tool, `check_names`: give it a list of candidate names and, optionally, the domain endings to try (with the leading dot, e.g. `.dev`) and the suffixes to try when a name is taken at Companies House.

The hosted server is meant to be added to Claude.ai as a custom connector at `https://dibs.interstellarai.net/mcp`, signing in with the owner's Google account (see "Deploying" below).

## Running locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

dibs                # start the MCP server (stdio)
dibs-http           # start it over Streamable HTTP on $PORT (default 8000): /mcp, plus a public /health
ruff check . && ruff format --check .
pytest
```

Configuration comes from environment variables; never commit them.

- `COMPANIES_HOUSE_API_KEY` — a key for the free [Companies House public data API](https://developer.company-information.service.gov.uk/). Without it, every Companies House result is "check manually" with a link to search the register by hand.

The HTTP server (`dibs-http`) also needs these; `.env.example` lists them all.

- `SECRET_KEY` — signs the OAuth tokens and client IDs. Rotating it signs everyone out and makes Claude.ai register again; tokens can't be revoked one by one.
- `ALLOWED_EMAIL` — the one Google account allowed to sign in. If it's unset, nobody can.
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` — a Google OAuth web client whose redirect URI is `<PUBLIC_BASE_URL>/oauth/callback`.
- `PUBLIC_BASE_URL` — the server's public URL, e.g. `https://dibs.interstellarai.net`.

`/health` works without any of them; the OAuth endpoints answer 503 naming whichever one is missing.

## Deploying (Railway)

The repo deploys to Railway from `Dockerfile`, configured by `railway.toml`. To set it up:

1. Create a Google OAuth web client with redirect URI `https://dibs.interstellarai.net/oauth/callback`.
2. Create a Railway service from `alexsiri7/dibs` that deploys from `main`.
3. Set the Railway variables `COMPANIES_HOUSE_API_KEY`, `SECRET_KEY`, `ALLOWED_EMAIL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `PUBLIC_BASE_URL=https://dibs.interstellarai.net`.
4. Add the custom domain `dibs.interstellarai.net` in Railway.
5. In Cloudflare, create a **DNS-only (grey cloud)** CNAME `dibs` pointing at the Railway target.
6. Check that `curl https://dibs.interstellarai.net/health` returns 200, and that `/mcp` without a token returns 401 with a `WWW-Authenticate` header.
7. Add `https://dibs.interstellarai.net/mcp` as a Claude.ai custom connector and sign in.
8. Add `dibs` to `DEPLOY_URLS` in `alexsiri7/interstellarai.net` so it is monitored.
