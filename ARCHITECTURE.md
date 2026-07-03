# Architecture

This document describes how the MCP Policy Enforcement Platform is put
together: the services, the layers inside them, the life of a request, and
the security design decisions that shape all of it.

## 1. System overview

The platform lets a user operate on an enterprise database in natural
language, while guaranteeing that **no LLM output ever reaches the database
without passing a deterministic policy engine first**.

```
┌────────────┐   prompt    ┌─────────────────┐   MCP call   ┌─────────────────┐
│  Console /  │ ──────────▶ │  Web Gateway     │ ───────────▶ │  MCP Server      │
│  API client │             │  (FastAPI, :8000)│              │  (FastMCP, :8001)│
└────────────┘             │                  │              │                  │
                           │ 1. LLM selects   │              │ 3. Policy Engine │
                           │    a tool        │              │    RBAC → Intent │
                           │ 2. Injects       │              │    → Policy      │
                           │    identity +    │              │ 4. Tool executor │
                           │    raw prompt    │              │    (SQLAlchemy)  │
                           └──────────────────┘              └────────┬────────┘
                                                                      │
                                                              ┌───────▼───────┐
                                                              │  PostgreSQL    │
                                                              │  data + RBAC + │
                                                              │  policies +    │
                                                              │  audit log     │
                                                              └───────────────┘
```

Three containers (see `docker-compose.yml`):

| Service      | Role                                                        | Port |
|--------------|-------------------------------------------------------------|------|
| `web`        | FastAPI gateway: console UI, admin dashboard, JSON API      | 8000 |
| `mcp-server` | FastMCP server: tool registry, policy engine, tool executor | 8001 |
| `db`         | PostgreSQL: business data, RBAC, policies, audit trail      | 5432 |

The enforcement point lives **inside the MCP server**, not in the web
gateway. Even a client that talks to the MCP server directly still goes
through the full authorization pipeline.

## 2. Layered design

1. **Interface layer** (`app/api/`, `app/templates/`, `app/static/`) —
   the HTML console, the admin dashboard, and the JSON API
   (`POST /api/v1/execute` and its SSE twin `/api/v1/execute/stream`).
2. **LLM handler** (`app/services/openai_service.py`) — converts the
   user's prompt into a candidate tool call, and (after an allowed
   execution) summarizes the structured result back into prose.
3. **MCP server** (`app/mcp/server.py`) — registers the tools over the
   Model Context Protocol (streamable HTTP) and auto-syncs one RBAC
   `Permission` row per registered tool at boot.
4. **Enforcement layer** (`app/policy/`) — the Policy Decision Point.
   Three ordered stages; the first failing stage wins (fail-closed).
5. **Execution layer** (`app/services/local_tool_executor.py`) — the only
   code that touches business data, exclusively through SQLAlchemy ORM
   queries (parameterized — raw LLM-generated SQL never exists anywhere
   in the system).
6. **Data layer** (`app/models/`, `app/db/`) — customers, RBAC tables
   (users/roles/permissions), the admin-editable `policies` table, and
   the `audit` decision log.

## 3. Life of a request

`POST /api/v1/execute` with `{username, prompt}`:

1. **Tool selection.** The prompt is sent to the LLM together with the
   registered MCP tool schemas. The LLM proposes one tool + arguments.
   If it cannot map the request to a tool, the request is denied at
   stage `tool-selection`.
2. **Identity & intent injection.** The gateway verifies the user exists,
   then injects `username` (identity) and `raw_prompt` (the verbatim
   user request) into the MCP call. Both fields are *server-injected* —
   see "LLM isolation" below.
3. **Policy Decision Point** (inside the MCP server), in order:
   - **Stage 1 — RBAC**: does the user's role hold the permission named
     after the tool? Permissions are a property of tools, auto-synced at
     boot, so the set of grantable permissions is always exactly the set
     of registered tools.
   - **Stage 2 — Intent alignment**: an independent LLM classifier tags
     the raw prompt (`read` / `create` / `update` / `delete` / `admin` /
     `unknown`) and the request is allowed only if the tags intersect
     the tool's declared intent set (`TOOL_INTENT_MAP`). This catches the
     case where the tool-selection LLM misinterprets the request — e.g.
     picking `delete_customer` for a prompt that only asked to *read*.
     Unclassifiable prompts fail closed.
   - **Stage 3 — Business policies**: argument-level rules whose
     thresholds are read live from the `policies` table on every request
     (max deletes per request, max credit-limit raise %, max starting
     credit limit). Admin edits take effect immediately, no redeploy.
     A policy an admin disabled is simply not enforced; if no row exists
     at all, the catalog's built-in default applies. Dispatch is
     declarative: the catalog binds each policy type to a tool, and
     `app/policy/bindings.py` binds each type to a handler — the engine
     loops over whatever the catalog declares for the called tool, so
     adding a new guarded tool never requires touching the engine.
4. **Execution.** Only if all stages allow. The executor runs the ORM
   operation and returns structured data.
5. **Response shaping.** On ALLOW, the LLM writes a short same-language
   summary of the structured result (the raw JSON is also returned). On
   DENY, the policy engine's reason is returned **verbatim** — it is
   never paraphrased by the LLM.
6. **Audit.** Every final decision — allow or deny, any stage — is
   persisted with username, tool, arguments, stage, reason, and the raw
   prompt. The admin dashboard reconstructs the security story from this
   log.

## 4. LLM isolation

The LLM is treated as an untrusted planner. The design enforces this in
four concrete ways:

1. **The LLM never writes SQL.** It can only *select* from a fixed menu of
   typed tools; the executor builds all queries through the ORM with bound
   parameters.
2. **The LLM cannot assert identity.** The `username` parameter is stripped
   from every tool schema shown to the model and injected server-side from
   the session. Anything the model tries to slip in is dropped defensively
   before execution.
3. **The LLM cannot forge the intent signal.** `raw_prompt` is likewise
   hidden from the model's schema and injected by the gateway, so the
   intent-alignment stage always judges the *user's* words, never text the
   model invented.
4. **The LLM never explains a denial.** Denial reasons come verbatim from
   the deterministic policy engine. Routing them through the LLM would let
   a summarization step blur or soften a security decision.

Scope note: intent alignment defends against LLM *misinterpretation and
hallucination*, not against a malicious authorized user — that adversary
is constrained by RBAC and the business-policy stage.

## 4b. Authentication & trust boundaries

Authorization is only meaningful if the identity it judges is real, so
every trust boundary is authenticated (`app/core/security.py`, stdlib
PBKDF2 + HMAC — no extra dependencies):

- **Users have passwords.** PBKDF2-HMAC-SHA256 with per-user random
  salt; verification is constant-time and fails closed on missing or
  malformed hashes. Seeded demo credentials are documented in the
  README.
- **Admin sessions are signed.** Logging in to the dashboard requires
  username + password; the session cookie is an HMAC-signed, expiring
  token — it cannot be forged or extended without the server's
  `SECRET_KEY`. Login returns one error for "unknown user" and "wrong
  password" alike, so the form can't enumerate accounts.
- **The MCP server only trusts the gateway.** Every request to the MCP
  server must present the shared `MCP_GATEWAY_KEY` header (checked in
  constant time by an ASGI middleware). Reaching port 8001 is not
  enough to call tools.
- **The execute API has two postures.** With `DEMO_MODE=false`,
  `POST /api/v1/execute` requires a Bearer token from
  `POST /api/v1/auth/login`, and the token's identity must match the
  requested username. With `DEMO_MODE=true` (the default), the console
  may switch identities freely — a *documented demo convenience* for
  showing RBAC differences live, never the production posture. The
  admin dashboard and the MCP server are authenticated regardless of
  this flag.

## 5. Natural-language policy authoring

Admins can type a rule in plain language ("don't let anyone delete more
than 3 customers at once"). The authoring service converts it into a
*structured draft* against a closed catalog of policy types — LLM-first,
with a deterministic keyword/number parser as an offline fallback. The
draft is **never saved automatically**: the admin reviews the parsed
structure and explicitly confirms it. Free text is never the live
enforcement artifact; a typed, reviewed row in the `policies` table is.
Unmappable text yields an invalid draft with an explanation (fail-closed),
never a guess.

## 6. Failure philosophy

- Unknown user, unmapped tool, unclassifiable intent, unclear delete
  scope, missing arguments → **deny**, with a human-readable reason.
- Audit logging is best-effort and never blocks an authorization
  decision.
- Result summarization is a nice-to-have: if it fails, the client falls
  back to the raw JSON. A cosmetic failure never breaks the response
  path.

## 7. Testing

`tests/test_policies.py` runs fully offline (in-memory SQLite, no OpenAI,
no Postgres) and covers the NL draft parser, threshold resolution from
the DB (including disabled policies and catalog defaults), and the
engine's business-policy stage. `tests/test_mcp.py` is a live smoke test
against a running MCP server (lists tools, calls `health_check`).