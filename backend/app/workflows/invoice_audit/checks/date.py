from .base import days, finding, money


def check(invoice, line, ctx):
    if line is None:
        return []
    problems: list[str] = []
    risk_days = 0
    ev: dict = {"service": [line.service_from, line.service_to], "period": [invoice.period_from, invoice.period_to]}
    total_days = max(days(line.service_from, line.service_to), 1)

    outside = 0
    if line.service_from < invoice.period_from:
        outside += (invoice.period_from - line.service_from).days
    if line.service_to > invoice.period_to:
        outside += (line.service_to - invoice.period_to).days
    if outside:
        problems.append(f"{outside} day(s) fall outside the invoice period")
        risk_days = max(risk_days, outside)

    if line.item_key:
        for d in (line.service_from, line.service_to):
            c = ctx.vendors.contract_rate(invoice.vendor_id, line.item_key, d)
            if c is None:
                problems.append(f"no contract valid on {d}")
                risk_days = total_days
                break
            ev["contract_valid"] = [c["valid_from"], c["valid_to"]]

    unknown = False
    if line.resident_id:
        res = ctx.ehr.resident(line.resident_id)
        ev["census"] = res
        if res is None:
            unknown = True
        else:
            admit = res.get("admit_date")
            discharge = res.get("discharge_date")
            before = after = 0
            if admit and line.service_from.isoformat() < admit:
                before = min((_d(admit) - line.service_from).days, total_days)
            if discharge and line.service_to.isoformat() > discharge:
                after = min((line.service_to - _d(discharge)).days, total_days)
            if before:
                problems.append(f"{before} day(s) before admission on {admit}")
            if after:
                problems.append(f"{after} day(s) after discharge on {discharge}")
            risk_days = max(risk_days, min(before + after, total_days))

    src = "invoice period, contract validity" + (", census" if line.resident_id else "")
    if problems:
        risk = line.amount * min(risk_days, total_days) / total_days
        return [finding(invoice, line, "date", "failed", "Service dates: " + "; ".join(problems) + ".",
                        expected="dates within period, contract and stay", actual=f"{line.service_from} to {line.service_to}",
                        at_risk=risk, evidence=ev, source=src)]
    if unknown:
        return [finding(invoice, line, "date", "unverified",
                        f"Resident {line.resident_id} is not on the census.", evidence=ev, source="census: not found")]
    return [finding(invoice, line, "date", "verified", "Service dates are inside the period, contract and stay.",
                    evidence=ev, source=src)]


def _d(s: str):
    from datetime import date
    return date.fromisoformat(s)
