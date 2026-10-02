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

## Running locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

dibs                # start the MCP server (stdio)
ruff check . && ruff format --check .
pytest
```

Configuration comes from environment variables; never commit them.

- `COMPANIES_HOUSE_API_KEY` — a key for the free [Companies House public data API](https://developer.company-information.service.gov.uk/). Without it, every Companies House result is "check manually" with a link to search the register by hand.
