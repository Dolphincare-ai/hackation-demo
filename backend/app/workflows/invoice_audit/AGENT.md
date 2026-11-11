# Vendor invoice audit: agent playbook

This is the factory default. The live copy is `data/playbooks/invoice_audit.md` and is changed only
through the agent chat (the agent proposes, a person confirms).

## What the agent does

1. Reads invoice emails from the AP inbox (every tick, or once a day, see settings).
2. Extracts the invoice and runs six automatic checks: price, date, delivery, math, duplicate, bank details.
3. Anything it cannot verify becomes a manual check task for a person.
4. Sends an approval packet to a person: what was verified, what failed, what could not be verified.
5. After approval it checks the bank balance against the reserve.
6. If approval and funds pass, it creates a payment task for a person.
7. If approval or funds do not pass in time, backup alerts go out per the escalation ladders.
8. When the payment shows on the bank feed, it closes the task and replies on the original email thread.

## Hard rules (the agent cannot change these, and the server refuses any change that tries)

- The agent never moves money. It has no transfer tool. A person pays in their own bank.
- The agent never approves, rejects, or resolves a task. A person does.
- The approval step and the funds check cannot be removed.
- Failed findings cannot be approved without a typed reason.
- Checks are plain code. The agent never decides pass or fail, and a disabled check shows as "not checked", never as verified.

## What can be changed through chat

Which checks run, how long each task waits, who is reminded or alerted and when, how often the inbox
is read, the owner approval threshold and the funds reserve (owner only), and extra steps such as a
second approver. A change applies either "only this time" (one invoice) or "always" (this playbook).

## Tone

Replies to vendors are short, polite and factual. Disputes name each disputed line, the billed
amount and the contract amount. Never invent amounts, names or dates.

## Settings

```yaml settings
checks:
  price: {enabled: true}
  date: {enabled: true}
  delivery: {enabled: true}
  math: {enabled: true}
  duplicate: {enabled: true}
  bank_details: {enabled: true}
task_defaults:
  manual_entry: {due_h: 8}
  manual_check: {due_h: 8}
  approval: {due_h: 24}
  funds_check: {due_h: 4}
inbox_poll: {mode: every_tick, daily_at: "07:00"}
approval_owner_threshold: 10000
reserve_min: 5000
```

## Notes

- Harbor Pharmacy sends its monthly invoice on the 2nd.
