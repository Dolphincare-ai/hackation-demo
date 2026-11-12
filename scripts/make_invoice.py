"""Build a one-page Harbor Pharmacy invoice PDF from the section 12 seed.

  python scripts/make_invoice.py [--variant changed_bank] [--out out]

Default: #4471, remit-to account 4821. changed_bank: #4480, account 7733 plus a "banking details
changed" note, which triggers the bank_details failure. Output goes to out/ (gitignored).
"""
import argparse
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

LINES = [
    ("Metformin 500 mg", None, 900, 0.09),
    ("Lisinopril 10 mg", None, 700, 0.11),
    ("Atorvastatin 40 mg", None, 600, 0.84),
    ("Apixaban 5 mg", "Resident: Jose Alvarez, 10/22 to 10/31", 60, 6.80),
    ("Enoxaparin 40 mg", None, 120, 24.50),
]
VARIANTS = {
    "default": dict(no="4471", account="4821", note=None),
    "changed_bank": dict(no="4480", account="7733", note="NOTE: our banking details have changed. Please update your records."),
}


def build(variant: str, out_dir: Path) -> Path:
    v = VARIANTS[variant]
    total = sum(round(q * p, 2) for _, _, q, p in LINES)
    path = out_dir / f"invoice_{v['no']}.pdf"
    out_dir.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=letter)
    y = 740

    def text(x, s, size=10, bold=False, right=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        (c.drawRightString if right else c.drawString)(x, y, s)

    text(50, "HARBOR PHARMACY", 20, True); text(560, "INVOICE", 20, True, True); y -= 14
    text(50, "Institutional & Long-Term Care Pharmacy", 9); text(560, f"No. {v['no']}", 10, True, True); y -= 12
    text(50, "218 Wharf Street, Suite 4, Portsmouth, NH 03801", 9); y -= 12
    text(50, "billing@harborpharmacy.example | (603) 555-0142", 9); y -= 36
    text(50, "BILL TO", 10, True); text(300, "Invoice date: 2026-11-02"); y -= 14
    text(50, "Riverside Care"); text(300, "Due date: 2026-12-02"); y -= 14
    text(50, "Attn: Accounts Payable"); text(300, "Service period: 2026-10-01 to 2026-10-31"); y -= 14
    text(50, "ap@riverside.example"); text(300, "Terms: Net 30"); y -= 34
    text(50, "Description", 10, True); text(350, "Qty", 10, True, True); text(430, "Unit price", 10, True, True)
    text(560, "Amount", 10, True, True); y -= 18
    for desc, sub, qty, price in LINES:
        text(50, desc); text(350, str(qty), right=True); text(430, f"${price:.2f}", right=True)
        text(560, f"${qty * price:,.2f}", right=True); y -= 12
        if sub:
            text(50, sub, 8); y -= 12
        y -= 6
    y -= 6
    text(430, "Subtotal", right=True); text(560, f"${total:,.2f}", right=True); y -= 14
    text(430, "Tax", right=True); text(560, "$0.00", right=True); y -= 16
    text(430, "TOTAL DUE", 12, True, True); text(560, f"${total:,.2f}", 12, True, True); y -= 40
    text(50, "REMIT TO", 10, True); y -= 14
    for s in ("Harbor Pharmacy", "Bank: First Harbor Bank", f"Account ending: {v['account']}",
              "Routing ending: 0912", f"Reference: INV-{v['no']}"):
        text(50, s); y -= 14
    if v["note"]:
        y -= 6; text(50, v["note"], 10, True); y -= 14
    c.save()
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=VARIANTS, default="default")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    print(build(args.variant, Path(args.out)))
