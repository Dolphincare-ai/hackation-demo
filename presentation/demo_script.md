# Live demo script (about 4 minutes, slide 6)

## Before the meeting (10 min)
`make` is not installed on this PC, so run these in Git Bash from the repo folder.
```bash
# first time only
py -3 -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt
(cd frontend && npm install)

# before each demo
.venv/Scripts/python scripts/seed.py                      # clean mock world + empty platform.db
# terminal 1: backend
cd backend && ../.venv/Scripts/python -m uvicorn app.main:app --port 8001
# terminal 2: frontend
cd frontend && npm run dev
```
Open http://localhost:5173 in a browser and keep a **second terminal** open for the demo commands below. The UI has no "Their world" panel yet, so the terminal plays the vendor and the bank.
For an offline demo, set `AI_MODE=cache` in `.env`. The flow also falls back to regex and templates if the AI is down.

Do a dry run once, then reset:
```bash
curl -s -X POST localhost:8000/mock/reset
```

## Script

| Time | Do | Say |
|---|---|---|
| 0:00 | Acting as **Owner**, View **All buildings**: Portfolio warboard | "This is the owner's wall: ten buildings, worst first, money at risk, what needs the owner." |
| 0:20 | Pick **Riverside Care** in View | "One building's board: residents, money, staffing, to-dos." |
| 0:35 | Terminal: send the invoice email (below) | "Harbor Pharmacy just emailed an invoice to the AP inbox. Nobody touched anything." |
| 0:45 | Click **Workflows** and open the Harbor #4471 run | "The bot read it and ran six checks against the contract, census and delivery log. It caught $600: atorvastatin billed at 0.84 against a 0.52 contract, and apixaban billed for a resident discharged on 10/21. It couldn't find a delivery for enoxaparin, so it made a manual check for the DON." |
| 1:30 | Acting as **Director of nursing**, on the enoxaparin step click **Verified** | "The DON gets that as one email or Teams message. She confirms and she's done." |
| 1:50 | Acting as **Administrator**: open the **Approval packet** | "The packet separates what was verified from what was flagged, with a plain-English summary." |
| 2:10 | In **Your decision**: atorvastatin set to *Approve at contract rate*, apixaban excluded, the rest *Approve as billed*, then **Approve** | "The payable drops from $4,010 to $3,410. Funds are checked against the reserve and pass. A payment task goes to the business office manager, because the platform never moves money." |
| 2:40 | Terminal: post the bank payment (below) | "The BOM pays in the bank like always." |
| 2:50 | Refresh the run: **CLOSED**, the payment is *matched*, and the timeline shows each step | "The bot saw the payment on the bank feed, closed the task and replied to Harbor on the original thread, noting the disputed lines. Here's the full audit trail." |
| 3:15 | Open the chat bubble and ask: *"What's late across my buildings?"* then *"Give approvals 12 hours on this vendor from now on"* | "The agent can explain and propose, but a person confirms it, and there's no tool that moves money." |
| 3:50 | Back to the deck | |

### Terminal commands
```bash
# 0:35 invoice email arrives (runs a tick right away)
curl -s -X POST localhost:8000/mock/email -H "Content-Type: application/json" -d '{"template":"harbor_4471"}'

# 2:40 payment appears on the bank feed
curl -s -X POST localhost:8000/mock/bank/post -H "Content-Type: application/json" \
  -d '{"account_id":"acct_riverside_op","payee":"Harbor Pharmacy","amount":-3410,"reference":"INV-4471"}'
```

### Optional extras (if there's time or a question)
```bash
# Escalation: jump the clock 48h, so reminders and owner alerts fire
curl -s -X POST localhost:8000/mock/advance -H "Content-Type: application/json" -d '{"hours":48}'
# Low funds: do this BEFORE approving, so the CFO gets a $2,410 shortfall task
curl -s -X POST localhost:8000/mock/bank/balance -H "Content-Type: application/json" -d '{"account_id":"acct_riverside_op","balance":6000}'
# Fraud check: invoice with changed bank details, so bank_details fails
curl -s -X POST localhost:8000/mock/email -H "Content-Type: application/json" -d '{"template":"harbor_changed_bank"}'
```

## If something breaks
- Run `curl -s -X POST localhost:8000/mock/reset` and start again from the email.
- If the UI won't load, jump to the backup slides (14 and 15) and walk through the numbers.
