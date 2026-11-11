# CLAUDE.md: SNF Operating Layer, Scenario 1 (vendor invoice audit)

Read this fully before writing code. Two developers work in parallel, each with their own Claude Code session. Stay inside your own directories (see Ownership). If you need a change to the contract in sections 5 to 9, tell the other developer first and update this file in the same commit.

## 1. What we are building

A prototype of an operating layer for skilled nursing facilities. It connects to the systems a building already uses and turns one event into tracked work. We build **one scenario end to end: the vendor invoice audit.** A later scenario (resident fall) must be addable without changing the engine.

The flow, in the user's words:

1. An invoice arrives by email.
2. Automatic checks verify items, prices, dates and delivery.
3. Anything that cannot be verified becomes a manual check task.
4. A packet goes to a person for approval, listing what was verified and flagging what was not.
5. The bank balance is checked for funds.
6. If approval and funds both pass, a payment task is created.
7. If approval or funds do not pass within a set time, backup alerts fire.
8. When the payment appears on the bank feed, the task is closed and the original email thread gets a reply.

Hackathon constraints: the whole thing is built in about 3 hours by two people, shown in a 5-minute demo, with synthetic data. Favor a working end-to-end path over completeness.

## 2. Non-negotiable principles

1. **Every wait is a task** with a due time and an escalation ladder. Approvals, manual checks, funds retries and payments all use the same task engine.
2. **The platform never moves money.** It creates a payment task for a person and observes the bank feed.
3. **Connectors are read-only mocks behind interfaces.** The mock "world" is plain files in `mock_world/`. Platform state is SQLite. Never mix the two.
4. **Checks are plain deterministic code.** Claude is used only to classify emails, extract invoices, write summaries, and draft replies. Claude never decides pass or fail.
5. **A person approves.** Failed findings cannot be approved without a typed reason.
6. **Audit everything.** Every state change, task change, AI call, notification and approval writes to `audit_log`.
7. **Invoice logic never goes in `core/`.** `core/` must stay generic so `resident_fall` can reuse it.
8. **Config over code** for roles, ladders, thresholds and reserves (`backend/app/config.yaml`).
9. **The clock is injectable.** Use `core/clock.now()` everywhere, never `datetime.now()`.

## 3. Stack and commands

- Backend: Python 3.11+, FastAPI, SQLModel (SQLite), Pydantic, pytest, `anthropic` SDK.
- Frontend: React (Vite) and Tailwind. Plain fetch, no state library.
- Scheduler: one asyncio background loop started in FastAPI lifespan, ticking every 5 seconds. `POST /mock/tick` runs the same tick on demand.
- Config: `.env` holds `ANTHROPIC_API_KEY`, `MODEL`, `AI_MODE` (`live` or `cache`).

```
make setup     # create venv, install backend and frontend deps
make seed      # rebuild mock_world/ and reset data/platform.db
make dev       # backend on :8000, frontend on :5173
make test      # pytest
```

## 4. Repo layout and ownership

`[A]` marks Developer A's directories, `[B]` marks Developer B's. `[both]` is edited by both with care.

```
CLAUDE.md                           [both]
backend/app/
  main.py config.py config.yaml     [A]
  db.py models.py schemas.py        [A]  schemas.py is the shared contract
  core/        clock audit tasks sla notify permissions  [A]
  workflows/
    registry.py                     [A]
    invoice_audit/
      flow.py                       [A]  state machine
      checks/                       [A]  price date delivery math duplicate bank_details
      packet.py approval.py funds.py payment_match.py   [A]
      extract.py classify.py        [B]  call the AI layer
    resident_fall/README.md         [A]  stub only
  connectors/  base.py              [both] interfaces, written first
               mailbox vendors ehr bank outbox   [B]
  ai/          client.py cache.py prompts/       [B]
  api/         routes_*.py          [A]
backend/tests/                      [A] for core, checks, flow; [B] for connectors, ai
mock_world/                         [B]
scripts/seed.py reset.py            [B]
frontend/                           [B]
```

## 5. Data model (SQLModel, SQLite at `data/platform.db`)

Generic tables (reused by every scenario):

```
events        id, type, source, building_id, payload_json, received_at
runs          id, type, state, building_id, title, context_json, created_at, updated_at, closed_at
tasks         id, run_id, kind, title, role, assignee_id, status(open|done|cancelled),
              created_at, due_at, escalation_level(int), last_escalated_at,
              payload_json, via(email|teams|text|ehr_alert), blocks_json (generic content blocks the UI renders),
              completed_at, completed_by, completion_source(user|system_observed)
approvals     id, run_id, task_id, decision(approve|reject), decided_by, decided_at, reason, snapshot_json
notifications id, run_id, channel(email|teams|text), to, subject, body, thread_ref, sent_at
audit_log     id, at, actor(system|claude|<user_id>), run_id, action, detail_json
users         id, name, role, building_id          (seeded, no login; UI sends X-User-Id)
```

Invoice tables:

```
invoices      id, run_id, vendor_id, invoice_no, invoice_date, due_date, period_from, period_to,
              total, remit_to_json, source_event_id, payable_amount(nullable), status
invoice_lines id, invoice_id, description, item_key(nullable), resident_id(nullable),
              service_from, service_to, qty, unit_price, amount, decision(null|approve|approve_at_contract|exclude)
findings      id, invoice_id, line_id(nullable), check(price|date|delivery|math|duplicate|bank_details),
              status(verified|failed|unverified|skipped|manually_verified|manually_rejected),   # skipped = check switched off in the playbook; never counts as verified
              
              expected, actual, amount_at_risk, message, evidence_json,
              resolved_by, resolved_at, resolution_note
payments      id, invoice_id, amount, account_id, expected_ref, matched_txn_id, matched_at,
              status(pending|matched|mismatch)
```

`findings.evidence_json` must hold exactly what was compared (the contract row, delivery rows, census row) so an approval can be reproduced later.

## 6. Invoice run state machine

States: `RECEIVED, EXTRACTED, CHECKED, NEEDS_INFO, PENDING_APPROVAL, FUNDS_CHECK, FUNDS_INSUFFICIENT, AWAITING_PAYMENT, PAID, CLOSED, REJECTED, MANUAL_ENTRY`

| From | Event | To | Side effects |
|---|---|---|---|
| (new) | email classified as invoice | RECEIVED | create run, event |
| RECEIVED | extraction valid | EXTRACTED | save invoice and lines |
| RECEIVED | extraction invalid twice | MANUAL_ENTRY | task `manual_entry` |
| EXTRACTED | checks run | CHECKED | save findings |
| CHECKED | any `unverified` finding | NEEDS_INFO | one `manual_check` task per unverified finding |
| CHECKED | none unverified | PENDING_APPROVAL | create `approval` task with packet |
| NEEDS_INFO | all manual checks resolved | PENDING_APPROVAL | create `approval` task with packet |
| PENDING_APPROVAL | approved | FUNDS_CHECK | compute `payable_amount` |
| PENDING_APPROVAL | rejected | REJECTED | notify, close |
| FUNDS_CHECK | balance minus payable >= reserve | AWAITING_PAYMENT | create `payment` task, create `payments` row |
| FUNDS_CHECK | otherwise | FUNDS_INSUFFICIENT | create `funds_check` task |
| FUNDS_INSUFFICIENT | retry passes (tick) | AWAITING_PAYMENT | close `funds_check` task, create `payment` task |
| AWAITING_PAYMENT | bank transaction matches | PAID | close `payment` task (system_observed), reply on original thread |
| PAID | reply sent | CLOSED | |

Payable amount: sum of lines with decision `approve` (billed amount) or `approve_at_contract` (qty times contract rate). Lines with `exclude` are left out. Excluded failed lines are noted in the packet and the reply as disputed.

## 6a. The bot (orchestrator)

The bot is the product: the background agent that runs the workflow from email to closed. It is a **deterministic orchestrator with Claude in four narrow slots** (section 10). It is not a free-roaming LLM agent. It lives in `core/` (generic loop) and `workflows/` (handlers registered by run type). One tick (every 5 s, or `POST /mock/tick`) does, in order:

1. Poll mailbox, classify each email (Claude), start a run if it is an invoice.
2. Extract invoice and lines (Claude, schema-validated, retry once, else `MANUAL_ENTRY`).
3. Run the six checks (plain code) and save findings.
4. Create one `manual_check` task per unverified finding; when all resolve, build the packet (code) with a summary (Claude) and create the `approval` task.
5. After approval: compute payable, check funds, create the `payment` task or the `funds_check` task; retry funds on every tick.
6. Run the SLA scanner: raise `escalation_level` one step at a time and send notifications per the ladders.
7. Match bank transactions to pending payments; on match close the task (`system_observed`), draft and send the reply on the original thread, close the run.

Rules: the bot never moves money, never decides approval, and writes every action to `audit_log` (actor `system` or `claude`). A tick must be idempotent: running it twice with no new input changes nothing. A new scenario adds a handler to `workflows/registry.py`, never a change to the loop.

## 7. Tasks, roles and escalation ladders

Task kinds and default roles:

| kind | role | due_at |
|---|---|---|
| manual_entry | business_office_manager | +8h |
| extra_step | from playbook `extra_steps` (role, due_h per step) | per step |
| manual_check | depends on check: delivery -> don, price -> business_office_manager, date -> administrator | +8h |
| approval | administrator (owner if payable over `approval_owner_threshold`) | +24h |
| funds_check | cfo | +4h |
| payment | business_office_manager | invoice due_date minus 2 days |

Ladders live in `config.yaml`. Hours are measured since task creation (for `payment`, since `due_at`). The SLA scanner raises `escalation_level` one step at a time, logs it, and sends a notification.

```yaml
ladders:
  manual_check: [{after_h: 8,  action: remind, to: [assignee_role]}, {after_h: 24, action: alert, to: [administrator]}]
  approval:     [{after_h: 24, action: remind, to: [assignee_role]}, {after_h: 48, action: alert, to: [owner, backup_approver]}]
  funds_check:  [{after_h: 4,  action: alert,  to: [cfo, business_office_manager]}]
  payment:      [{after_h: 0,  action: alert,  to: [business_office_manager, administrator]}]
approval_owner_threshold: 10000
reserve_min: 5000
backup_approver_role: owner
```

## 8. Automatic checks (all in `workflows/invoice_audit/checks/`)

Each check is a pure function `(invoice, line, ctx) -> list[Finding]`. `ctx` exposes connectors. Statuses: `verified`, `failed`, `unverified` (information could not be found).

- **price:** contract rate for vendor and `item_key` on the service date. No contract or item -> `unverified`. Billed above rate -> `failed`, `amount_at_risk = (billed - rate) * qty`.
- **date:** service dates inside the invoice period and the contract's validity. For lines with a `resident_id`, the resident must be on the census for those dates. Unknown resident -> `unverified`. Billing after discharge -> `failed` for the days after discharge.
- **delivery:** delivery records for vendor, item and period. None -> `unverified`. Billed qty over delivered qty -> `failed`.
- **math:** `qty * unit_price == amount` per line, and lines sum to the total. Mismatch -> `failed`.
- **duplicate:** same line within this invoice, or the same invoice number from the same vendor earlier. -> `failed`.
- **bank_details:** `remit_to` matches the vendor master. A change -> `failed` (possible payment fraud). Missing master data -> `unverified`.

Write table-driven pytest cases for every rule.

## 9. Connectors (interfaces in `connectors/base.py`)

```python
class MailboxConnector(Protocol):
    def poll(self) -> list[Email]: ...        # reads mock_world/mailbox/inbox, marks as seen
    def send(self, msg: Outgoing) -> None: ...  # writes to mock_world/mailbox/sent
class VendorConnector(Protocol):
    def vendor_master(self, vendor_id): ...
    def contract_rate(self, vendor_id, item_key, on_date): ...
    def deliveries(self, vendor_id, item_key, date_from, date_to): ...
class EHRConnector(Protocol):
    def resident(self, resident_id): ...      # admit_date, discharge_date, building_id
class BankConnector(Protocol):
    def available_balance(self, account_id): ...
    def transactions(self, since): ...
```

`get_connectors()` returns the mock implementations. `GET /connectors/health` reports each connector's mode (`mock`) and last read time. This is what makes the "real systems plug in here" story honest.

### Mock world file formats

```
mock_world/mailbox/inbox/<id>.json
  {"id","from","to","subject","received_at","body","thread_ref",
   "attachments":[{"filename","text"}]}      # invoice content is plain text, no PDF parsing
mock_world/mailbox/templates/*.json          # emails that POST /mock/email can drop into inbox
mock_world/vendors/vendor_master.json
  [{"vendor_id","name","email_domain","remit_to":{"bank","account_last4","routing_last4"},"payment_terms_days"}]
mock_world/vendors/contracts.json
  [{"vendor_id","item_key","description","unit","rate","valid_from","valid_to"}]
mock_world/vendors/deliveries.json
  [{"vendor_id","item_key","date","qty","building_id"}]
mock_world/ehr/census.json
  [{"resident_id","name","building_id","room","admit_date","discharge_date"(nullable)}]
mock_world/bank/accounts.json
  [{"account_id","name","building_id","balance"}]
mock_world/bank/transactions.json
  [{"txn_id","account_id","date","payee","amount","reference"}]
```

## 10. AI layer (`backend/app/ai/`)

Four functions, each with a Pydantic input and output, one prompt file, and a cache keyed by input hash in `data/ai_cache/`:

1. `classify_email(email) -> {kind: invoice|statement|question|other, vendor_hint, confidence}`
2. `extract_invoice(email) -> InvoiceExtract` (vendor, invoice_no, dates, remit_to, lines with `item_key` chosen from the known contract keys or null, resident name mapped to `resident_id` or null, total)
3. `summarize_packet(packet) -> str`: plain-language summary, **only from the facts in the packet**.
4. `draft_reply(payment, invoice, thread) -> str` and `draft_dispute(findings) -> str`.

Rules: validate every response against its schema, retry once, then fall back (a manual task for extraction, a plain template for text). `AI_MODE=cache` serves from the cache only so the demo works offline. Never put API keys in code. Prompts must say: use only the facts provided, never invent amounts, names or dates.

## 11. API contract

Auth: no login. The UI sends `X-User-Id`. `permissions.py` enforces who may resolve or approve what.

```
GET  /runs                      -> [{id, type, state, building_id, title, vendor, invoice_no, total, payable,
                                      at_risk, open_tasks, late_tasks, updated_at}]
GET  /runs/{id}                 -> {run, invoice{...lines[]}, findings[], tasks[], approval|null,
                                      payment|null, packet|null, timeline[]}      # timeline = audit_log rows
GET  /tasks?role=&user_id=&status=open
                                -> [{id, run_id, kind, title, role, due_at, late, escalation_level, payload}]
POST /tasks/{id}/resolve        {user_id, response: "verified"|"not_verified"|"dispute", note}
POST /runs/{id}/approval        {user_id, decision: "approve"|"reject", reason,
                                  lines:[{line_id, decision: "approve"|"approve_at_contract"|"exclude"}]}
GET  /dashboard                 -> {invoices_by_state, dollars_at_risk, dollars_verified, dollars_paid,
                                      late_tasks, open_tasks_by_role}
GET  /connectors/health
GET  /buildings/{id}/overview   -> {kpis{open_workflows, late_steps, waiting_on_you, money_held_back},
                                      needs_you[], late_and_escalated[], due_24h[], by_workflow_type{}}
GET  /buildings/{id}/board      -> {building{id,name,beds}, as_of,
                                      quadrants:[{key,title,headline,tone: good|warn|bad|neutral,
                                                  lines[], source, live: bool}],   # residents, money, staffing
                                      todos:[{title, owner, bucket: today|week|month, late, source: agent|mock}]}
                                    # four-quadrant board; live=false means mock connector data
GET  /portfolio                 -> {kpis{open_workflows, late_steps, dollars_at_risk, dollars_paid},
                                      buildings:[{id, name, status: on_track|watch|act_now, open_runs, late_tasks,
                                                  at_risk, held_back}],   # sorted worst first
                                      needs_owner[], live_feed[]}          # live_feed = recent audit_log rows

# demo controls
POST /mock/email                {template: "harbor_4471" | "harbor_changed_bank" | ...}
POST /mock/bank/post            {account_id, payee, amount, reference}
POST /mock/bank/balance         {account_id, balance}
POST /mock/advance              {hours}
POST /mock/tick
POST /mock/reset
```

`packet` shape:

```json
{"summary": "...",
 "verified":   [{"line_id":1,"check":"price","message":"...","source":"contract Harbor-ATOR-40 rate 0.52"}],
 "manually_verified": [{"line_id":5,"check":"delivery","by":"u_don_rc","at":"...","note":"..."}],
 "failed":     [{"line_id":3,"check":"price","message":"...","amount_at_risk":192.0}],
 "unverified": [{"line_id":5,"check":"delivery","reason":"No delivery record found"}],
 "totals": {"billed":4010.0,"verified":158.0,"at_risk":600.0}}
```

## 12. Seed scenario (must exercise every branch)

Vendor Harbor Pharmacy, invoice #4471, Riverside Care, period Oct 2026, dated 2026-11-02, due 2026-12-02, total $4,010.00.

| Line | Qty x price | Planted case | Expected |
|---|---|---|---|
| Metformin 500 mg | 900 x 0.09 = 81.00 | matches contract and delivery | verified |
| Lisinopril 10 mg | 700 x 0.11 = 77.00 | matches | verified |
| Atorvastatin 40 mg | 600 x 0.84 = 504.00 | contract rate 0.52 | price failed, at risk 192.00 |
| Apixaban 5 mg, Jose Alvarez, 10/22 to 10/31 | 60 x 6.80 = 408.00 | resident discharged 2026-10-21 | date failed, at risk 408.00 |
| Enoxaparin 40 mg | 120 x 24.50 = 2,940.00 | no delivery record | delivery unverified -> manual check |

Operating account balance 12,000, reserve 5,000. Expected demo path: delivery manual check resolved as verified, approver approves metformin, lisinopril and enoxaparin, `approve_at_contract` for atorvastatin (312.00), excludes apixaban. Payable 3,410.00. Funds pass. Switch the balance to 6,000 to demo `FUNDS_INSUFFICIENT`. Second template `harbor_changed_bank` carries a different remit-to account to trigger the bank_details failure.

Users seeded: administrator (Riverside), business_office_manager, don, cfo, owner, one each.

## 13. Frontend screens (React, Tailwind, `frontend/`)

There is no "My work" task list: staff handle tasks in their own tools (inbox, Teams, EHR). The platform shows the work, not a to-do app. Three tabs plus a side panel:

1. **Their world** (left panel): fake inbox with a "send invoice email" button per template, fake Teams and EHR feed showing where tasks land (`via`), and a fake bank screen with "post payment" (prefilled from the payment task) and a balance field. These call the `/mock/*` endpoints. Shows that staff do not enter anything into the platform. Includes the demo bar: advance the clock (+3h, +24h, +48h), tick, reset.
2. **Workflows (shared):** workflow-type tabs (All, Vendor invoice audit, Resident fall, ... with counts), a list of open workflows of that type, and a detail panel: progress strip, steps with owner, due time and channel, per-line check grid (verified, failed, unverified), packet with verified and flagged items clearly separated, approval form with per-line decisions, manual-check buttons (Verified / Not verified / Dispute plus note), funds and payment status, timeline from `timeline[]`. Steps closed by observation are marked. Rendered generically from task `blocks` and run `context`, so a new workflow needs no new screen.
3. **Overview (administrator, one building):** KPIs, Needs you, Late and escalated, Due in 24 hours, count by workflow type. Data from `GET /buildings/{id}/overview`.
4. **Portfolio (owner, warboard):** dark wall-style screen from `GET /portfolio`. Big KPI numbers, one tile per building (about 10) sorted worst first with status word (On track / Watch / Act now), a Needs the owner panel, money at risk by building, and a live feed. Seed the nine non-Riverside buildings with a few synthetic runs and tasks so the board looks alive; only Riverside runs the live scenario.
5. A role switcher at the top (owner, administrator, business office manager, don, cfo) sets `X-User-Id`. Landing is the Portfolio for owner, Overview for administrator, Workflows for everyone else.

No setup screens. Plain-language task titles. Empty states say what to do next.

## 14. Tests

Table-driven tests for each check. State-machine tests: happy path, manual-check loop, insufficient funds then retry, rejection, approval timeout escalation (use the clock). Payment matcher: exact match, wrong amount, no match. Bot tick idempotency test: a second tick with no new input changes no rows. One end-to-end test: template email in, resolve manual check, approve, post bank transaction, assert run `CLOSED` and a reply exists in `mock_world/mailbox/sent`.

## 15. Working agreements

- Branch per developer (`dev-a`, `dev-b`). Merge to `main` at each checkpoint, never leave `main` broken.
- Commit at least every 20 minutes. Run `make test` before merging.
- Do not edit the other developer's directories. Ask first, or put the request in a `TODO(A)` / `TODO(B)` comment.
- `schemas.py` and section 9, 11 of this file are the contract. Change them only by agreement.
- Until the other side lands, work against fixtures: A uses `backend/tests/fixtures/extracted_4471.json`, B uses a mocked API (`frontend/src/mockApi.js`) that returns the section 11 shapes.

## 16. Out of scope for now

Real PDF parsing, real email, real bank or PointClickCare connections, authentication, multi-building rollups beyond the Portfolio board (synthetic data for the other buildings), the resident fall scenario (stub only), mobile layout, and anything that moves money.


## 17. Engine notes (Developer A)

- **Playbook schema:** `workflows/invoice_audit/playbook_schema.py` is the whitelist (`extra="forbid"`, limits per value). Anything not declared there cannot be written. Writers call `core.playbook.write_settings(run_type, settings) -> (before, after)`; it validates, then writes, and raises `PlaybookError` without touching the live file.
- **Finding status `skipped`:** a disabled check writes one invoice-level `skipped` finding. The packet lists it under `skipped` ("not checked by request") and it never counts toward `totals.verified`.
- **Packet additions:** `skipped[]` and `disputed[]` (lines excluded or paid at contract, with billed and payable) next to the section 11 keys.
- **extra_steps** are generic `extra_step` tasks created next to the manual checks. The run stays in `NEEDS_INFO` until every manual check and extra step is done, then the approval task is created.
- **AI slots:** `workflows/invoice_audit/slots.py` is the only place the flow calls the AI layer. It tries B's `classify.classify_email`, `extract.extract_invoice` and `app.ai.summarize_packet / draft_reply / draft_dispute`, and falls back to a regex reader and text templates, so tests and the demo work offline. Each call writes an `ai_call` audit row with `via: ai|fallback`.
- **Payment matching:** a bank transaction matches when it is on the payment's account, its reference contains `INV-<invoice_no>` (or the payee is the vendor) and `abs(amount)` equals the payable. A different amount marks the payment `mismatch` (reported once) and leaves the run in `AWAITING_PAYMENT`.
- **Demo endpoints** run a tick immediately. `POST /mock/reset` rebuilds runs, tasks, the mock world and the clock, and leaves `data/playbooks/` alone.
- Env: `DISABLE_SCHEDULER=1` turns off the 5 s loop (tests).
