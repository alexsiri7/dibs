# Dibs — Developer Guide

## What this is

A FastMCP server that checks candidate business names against Companies House ("same as" rules + near matches), domains (RDAP) and UK trademarks (classes 9 and 42), tries suffix variants when a name is taken, and returns a verdict with evidence per name.

Spec: issue #1 (and `openspec/specs/`). Work breakdown: issues #2–#7.

## Stack

- Python 3.12, `mcp[cli]` (`mcp.server.fastmcp.FastMCP`), httpx, pydantic
- pytest (+ pytest-asyncio, respx for HTTP mocking), ruff (lint + format)
- No persistence

## Commands

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
dibs            # run the MCP server
```

## Project layout

```
src/dibs/
  server.py   FastMCP instance and entry point (tools registered here)
  models.py   Name-report / verdict models
  checks.py   Batch check pipeline with pluggable checks
tests/        pytest suite
```

## Key invariants

- **Strictly read-only** — no code path may register, buy, reserve or otherwise mutate anything at Companies House, a registrar or the IPO. Only GET/lookup requests.
- **Never report "clear" on failure** — if a lookup fails or can't be done, the result is "check manually" with a link.
- **A taken domain alone never makes a verdict "conflict".**
- **No secrets committed** — API keys (e.g. Companies House) come from env vars only; `.env` is gitignored.
- Tests must not hit live services; mock HTTP with respx.
