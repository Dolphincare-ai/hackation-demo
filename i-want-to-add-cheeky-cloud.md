# Plan: AP agent (invoice bot) + dashboard chat with propose/confirm

## Context
The repo has the foundations (models, `core/clock|audit|tasks`, `config.yaml`, mock connectors in `connectors/mock.py`, seed world, portfolio/board dashboards). It does **not** have the bot from CLAUDE.md §6a yet: no checks, flow, AI layer, scheduler, or `/runs` APIs. The user wants:
1. The full AP agent: email in, checks, funds, manual checks, approval packet, payment task for a person, backup alerts, and observing the bank to close the run and reply.
2. A **chat agent on the dashboard** that explains status and can change the workflow (add or remove steps, change timing). Changes are **proposed, then confirmed by a person**, and can be **standing** (agent settings) or **this run only**.

The user builds all of it (backend and frontend). CLAUDE.md must be updated in the same commit, because this adds a fifth Claude slot (chat) and new tables.

## Answer to "can the agent be denied transfer permission?"
Yes, and the code enforces it by construction, not by asking the model nicely:
- `BankConnector` has only `available_balance` and `transactions`. No method can send money. `post_transaction` / `set_balance` stay demo-only helpers and are only reachable from `/mock/*` routes, never from the bot or chat tools.
- The chat agent gets an explicit tool whitelist (below). There is no transfer tool, so the model cannot call one.
- The `payment` task is a plain task as in CLAUDE.md §6 and §7 (payable amount, invoice ref, due date). A person makes the payment in their own bank, and the bot sees it on the feed and closes the task (`system_observed`). Preparing a transfer draft is out of scope for now.

## How settings and changes are stored (backend)
**The agent's playbook is a markdown file:** `backend/app/workflows/invoice_audit/AGENT.md`. It has two parts:
- **Prose for Claude:** what the agent does, tone for replies and disputes, vendor notes ("Harbor bills on the 2nd"), and what the chat agent may and may not propose. It is loaded into the chat system prompt. Claude can propose edits to the prose too, such as adding a vendor note.
- **One fenced ```yaml settings``` block for the engine:** check on/off, due times, ladders, inbox schedule, extra steps, and per-vendor sections (`vendors: harbor: {checks: {delivery: {enabled: false}}}`). `core/playbook.py` parses it and validates it against a Pydantic schema. If the file is invalid, the engine refuses to load it and keeps the last good version.

`core/settings.py: effective(run_type, key, run=None)` reads in this order, and the first layer that has a value wins:

| Order | Where | Scope |
|---|---|---|
| 1. This invoice only | `runs.context_json["overrides"]` (SQLite) | one run |
| 2. Playbook, vendor section | live playbook yaml `vendors.<id>` | all invoices from that vendor |
| 3. Playbook, general | live playbook yaml top level | all invoices |
| 4. Engine defaults | `config.yaml` | fallback |

**One live playbook, changed only through the app (no developer edits, no git at runtime):**
- `data/playbooks/invoice_audit.md` (gitignored, next to `platform.db`) is the **single source of truth** the engine and chat agent read. Every change goes chat → proposal → person confirms → backend writes the file.
- Changes persist: restarts, `make seed` and `POST /mock/reset` do **not** touch the playbook. They reset only runs, tasks and the mock world.
- `backend/app/workflows/invoice_audit/AGENT.md` is only the **factory default**. It is copied once if the live playbook is missing, or when an admin clicks **Restore defaults**, which is itself a proposal that is confirmed and audited.
- On Apply of a standing change, the backend rewrites only the yaml block. The prose is kept as is.
- History lives in `audit_log`: action `playbook_changed`, with who confirmed it, the proposal id, and the full before and after text. The user can ask the bot "what changed?" or "undo the last change". A revert is a proposal, is audited, and needs the same permission as the original change.

Only two small generic tables are added in `models.py`, because platform state stays in SQLite:
```
agent_proposals  id, run_id(nullable), run_type, scope(once|standing), vendor_id(nullable),
                 changes_json [{key, from, to}] or prose_patch, rationale,
                 status(pending|applied|rejected), proposed_at, decided_by, decided_at
chat_messages    id, user_id, run_id(nullable), role(user|assistant|tool), content_json, at
```
Every proposal, apply and reject writes to `audit_log`. The audit row for a standing change records the before and after versions of AGENT.md.

**Changeable keys** (the whitelist is the playbook's Pydantic schema, with a type and limits per field):
- `checks.<name>.enabled` (price, date, delivery, math, duplicate, bank_details). A disabled check writes a `skipped` finding, so the packet shows "not checked by request of X". It never shows as verified.
- `task_defaults.<kind>.due_h`, `ladders.<kind>` (timings, recipients), `manual_check_roles.<check>`
- `inbox_poll.mode` (`every_tick` | `daily`), `inbox_poll.daily_at`
- `approval_owner_threshold`, `reserve_min` (min and max limits; owner role only)
- `extra_steps`: add an optional step such as a "second approver" or "notify DON before approval" task. It uses the generic task engine with a role and due_h.

**Locked, and refused by both the validator and the prompt:** removing the approval step, removing the funds check, any money movement, approving or resolving tasks, and editing findings. Permissions (`core/permissions.py`) decide who may confirm which key. For example, reserve and threshold changes need the owner, and timings can be confirmed by the administrator.

**Flow of a change:** user: "Give approvals 12h this time" → Claude calls `propose_change(scope="once", run_id=12, changes=[{key:"task_defaults.approval.due_h", to:12}])` → the backend validates against the whitelist, stores an `agent_proposals` row as `pending`, and the bot asks in chat: "only this time, always, or cancel?" → the user types the answer → Claude calls `confirm_proposal(id, scope)` or `cancel_proposal(id)`. The server runs the confirm only if all of these hold: the proposal is pending and belongs to this chat, the latest user message came after the proposal, and the user (from `X-User-Id`) has permission for the keys. So Claude cannot confirm on its own initiative. The server then then writes to the run (once) or rewrites the live playbook's yaml block (standing), writes audit, and adjusts any affected open task (for example, recomputes `due_at` on the open approval task) → the next tick uses the new values.

## Backend work (in order)

1. **AI layer** `ai/client.py`, `ai/cache.py`, `ai/prompts/*.md`: `classify_email`, `extract_invoice`, `summarize_packet`, `draft_reply`, `draft_dispute`, with Pydantic validation, one retry, cache keyed by input hash in `data/ai_cache/`, and `AI_MODE=cache`. Use `anthropic` with `MODEL` from `.env` (default `claude-sonnet-5-5`).
2. **Checks** `workflows/invoice_audit/checks/{price,date,delivery,math,duplicate,bank_details}.py`: pure functions per §8. They read `effective()` for `enabled`.
3. **Flow** `workflows/invoice_audit/flow.py` and `packet.py`, `approval.py`, `funds.py`, `payment_match.py`: the §6 state machine. Each handler is idempotent and keyed off run state. `extra_steps` inserted as generic tasks before approval.
4. **Engine** `core/sla.py` (escalation ladder scanner using `effective()` ladders), `core/notify.py` (Notification rows + mailbox/Teams feed), `core/bot.py` (generic tick: poll if due → dispatch to `workflows/registry.py` handlers → SLA → observers), `core/playbook.py` (generic: load, validate and rewrite an AGENT.md for any run type; `resident_fall` gets its own AGENT.md later), `core/settings.py`, `core/permissions.py`. Write the first `workflows/invoice_audit/AGENT.md` with prose and a yaml block that mirrors the current defaults.
5. **Inbox trigger**: `inbox_poll` in the playbook. `every_tick` polls each tick. `daily` polls once when `clock.now()` passes `daily_at`, tracked by `last_poll_at` in a small `kv` row, so it works with the demo clock advance. Typing "check the inbox now" in chat calls the `check_inbox_now` tool. `POST /mock/email` drops the email and triggers an immediate poll.
6. **Scheduler**: asyncio loop in the `main.py` lifespan, every 5 s, calling `bot.tick()`. `POST /mock/tick` calls the same function.
7. **Chat agent** `ai/chat.py` + `api/routes_agent.py`:
   - `POST /agent/chat {user_id, message, run_id?}` → manual tool-use loop with Claude, history from `chat_messages`, returns `{reply, proposals[]}`.
   - Tools (read): `list_runs`, `get_run`, `list_tasks`, `get_settings(run_type, run_id?)`, `explain_finding`.
   - Tools (actions): `check_inbox_now` (runs a poll and tick), `propose_change`, `propose_extra_step`, `propose_revert(audit_id | "last")`, `propose_restore_defaults`, `confirm_proposal(id, scope: once|always)`, `cancel_proposal(id)`. The confirm is guarded server-side as described above.
   - The system prompt includes the live playbook prose, states the locked rules, says to always ask "only this time or always" before confirming, says to use only facts returned by tools, and says to never invent amounts. The server-side validator is the real guard.
   - The only HTTP endpoint the UI needs is `POST /agent/chat` (plus `GET /agent/chat/history`). Proposals, settings and history are reached through chat tools, not separate screens.
8. **APIs from §11**: `/runs`, `/runs/{id}`, `/tasks`, `/tasks/{id}/resolve`, `/runs/{id}/approval`, `/dashboard`, `/connectors/health`, `/mock/*`.

## Frontend work
- `frontend/src/AgentBot.jsx`: a **floating bot icon** in the bottom-right corner on every screen, with a small badge when the bot has something to say (for example, a pending proposal or a late task). Clicking it opens a **chat popup** (about 380×560, bottom-right, with close and minimize). It is a normal chat: message bubbles, a typing indicator, a text box with Enter to send, and history kept per user.
- **Everything is done by typing. There are no buttons in the chat.** Examples:
  - "check the inbox now"
  - "what's waiting on me?"
  - "give approvals 12h on this one"
  - "turn off the delivery check for Harbor"
  - "show me the current settings"
  - "undo the last change"
  - "restore defaults"
- **Proposals are bot messages.** For example: *"I'd change the approval due time from 24h to 12h. Should this apply only to invoice #4471, or to all Harbor invoices? Reply 'only this time', 'always' or 'cancel'."* The user answers in text.
- The bot answers "show me the current settings" in plain language, with the source of each value (default / playbook / vendor rule / this invoice only).
- The role switcher sets `X-User-Id`, and the chat sends it so a confirmation is permission-checked.
- Workflows tab (§13) showing runs, check grid, packet, approval form, and payment status.

## Docs
Update CLAUDE.md: §2.4 adds the chat slot (it can only read and propose), §5 adds `agent_proposals` and `chat_messages`, a new section describes the AGENT.md playbook and its resolution order, §7 adds `inbox_poll` and `checks.*.enabled`, §10 adds `chat`, §11 adds the `/agent/*` routes.

## Verification
- `make test` with new tests:
  - table-driven tests for each check
  - state-machine paths (happy path, manual check, insufficient funds then retry, reject, approval-timeout escalation)
  - payment matcher
  - tick idempotency
  - settings resolution order (this run > playbook vendor section > playbook general > config.yaml)
  - an invalid AGENT.md yaml block is rejected and the last good version stays in use
  - a standing apply rewrites only the yaml block of the live playbook, keeps the prose, and revert restores the old version
  - demo reset leaves the playbook unchanged, and Restore defaults (after confirm) copies the factory default
  - validator rejects locked keys (disable approval, any transfer)
  - applying a "once" override changes only that run
  - daily poll fires once per day under `clock.advance`
  - an end-to-end test that runs to `CLOSED` with a reply in `mock_world/mailbox/sent`.
- Chat tests use a stubbed Claude client that returns canned tool calls. They check that:
  - a proposal is created as `pending`, and nothing changes until the user types a confirmation
  - `confirm_proposal` is refused when no user message came after the proposal (Claude can't confirm on its own)
  - `confirm_proposal` is refused for a user without permission
  - "only this time" writes to the run, and "always" writes to the playbook.
- Manual demo (`make seed && make dev`):
  1. Send `harbor_4471`, see the manual check, resolve it, approve, and see the payment task created.
  2. Post the bank payment and see the run close and the reply sent.
  3. Click the bot, type "give approval only 2h on this one", answer "only this time", advance +3h, and see the backup alert.
  4. Type "turn off the delivery check for Harbor", answer "always", send the email again, and see the packet show delivery as skipped.
  5. Type "undo the last change", confirm, and see delivery checked again on the next invoice.
