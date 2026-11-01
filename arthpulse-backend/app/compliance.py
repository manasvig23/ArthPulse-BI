"""
Compliance engine.

Five checks an Indian SME can actually be penalised for, all computed from
the voucher data (plus a few small extra inputs):

    1. Cash received  - Section 269ST  (>= Rs 2 lakh in a day from one party)
    2. Cash paid      - Section 40A(3) (> Rs 10,000 in a day to one party)
    3. GST            - input credit vs GSTR-2B, and GSTR-1 vs GSTR-3B
    4. MSME payments  - Section 43B(h) (45 / 15 day payment limit)
    5. TDS shortfall  - Section 393 (Income-tax Act 2025)

Every finding carries: severity, party, plain-English summary, rupee
exposure, a recommended action and the evidence rows behind it.

"""

import math
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .models import Voucher, SupplierProfile, Gstr2bInvoice, GstReturn
from .rules import REFERENCE_DATE

# ------------------------------------------------------------- settings
# kind: "statute" = taken from the law as I understand it (verify)
#       "demo"    = deliberately low so a small business can trigger it
#       "assumed" = a modelling assumption
SETTINGS = {
    "cash_receipt_limit":   (200000, "statute"),
    "cash_payment_limit":   (10000, "statute"),
    "cash_payment_limit_transporter": (35000, "statute"),
    "assumed_tax_rate":     (0.25, "assumed"),
    "itc_excess_min":       (10000, "demo"),     # portal limits are far higher (e.g. Rs 25 lakh)
    "itc_excess_pct":       (5.0, "demo"),
    "output_gap_min":       (10000, "demo"),
    "output_gap_pct":       (5.0, "demo"),
    "gst_interest_pct_pa":  (18.0, "assumed"),
    "msme_days_agreement":  (45, "statute"),
    "msme_days_no_agreement": (15, "statute"),
    "tds_interest_pct_month": (1.0, "assumed"),
    "watch_ratio":          (0.8, "assumed"),    # show "close to the limit" items from 80%
}


def S(key):
    return SETTINGS[key][0]


# TDS: nature of payment -> threshold and rate (Section 393 tables, FY 2026-27 as I understand them)
TDS_NATURES = {
    "Contractor":     {"label": "Contractor payments", "single": 30000, "annual": 100000,
                       "rate_individual": 1.0, "rate_other": 2.0},
    "Professional":   {"label": "Professional fees", "annual": 50000, "rate": 10.0},
    "Commission":     {"label": "Commission / brokerage", "annual": 20000, "rate": 2.0},
    "Rent-Building":  {"label": "Rent (land / building)", "monthly": 50000, "rate": 10.0},
    "Rent-Machinery": {"label": "Rent (plant / machinery)", "monthly": 50000, "rate": 2.0},
}

NOT_COVERED = [
    "E-invoicing and e-way bills",
    "GSTR-9 annual return and GSTR-9C",
    "Advance tax",
    "Exceptions to the cash-payment limit (for example payments to banks)",
    "TDS: missing PAN (higher rate), technical fees, late deposit of TDS",
]


# -------------------------------------------------------------- helpers
def inr(n):
    """1234567 -> Rs 12,34,567 (Indian digit grouping)."""
    n = int(round(n))
    sign = "-" if n < 0 else ""
    digits = str(abs(n))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        digits = ",".join(parts + [tail])
    return f"{sign}\u20b9{digits}"


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _fmt_date(d):
    return d.strftime("%d %b %Y")


def _month_label(ym):
    y, m = ym.split("-")
    return date(int(y), int(m), 1).strftime("%b %Y")


def _months_since(d):
    """Whole or part months from d to the reference date (minimum 1)."""
    return max(1, math.ceil((REFERENCE_DATE - d).days / 30))


def _finding(severity, party, title, summary, exposure, exposure_kind, action, columns, rows):
    return {
        "severity": severity, "party": party, "title": title, "summary": summary,
        "exposure": round(exposure), "exposure_kind": exposure_kind, "action": action,
        "evidence": {"columns": columns, "rows": rows},
    }


def _settings_view(*keys):
    labels = {
        "cash_receipt_limit": "Cash receipt limit per party per day",
        "cash_payment_limit": "Cash payment limit per party per day",
        "cash_payment_limit_transporter": "Cash limit for goods transporters",
        "assumed_tax_rate": "Tax rate used to estimate tax impact",
        "itc_excess_min": "ITC excess that triggers a flag",
        "itc_excess_pct": "ITC excess as % of GSTR-2B",
        "output_gap_min": "Output tax gap that triggers a flag",
        "output_gap_pct": "Output tax gap as % of GSTR-1",
        "gst_interest_pct_pa": "Interest on GST shortfall (per year)",
        "msme_days_agreement": "MSME payment limit with written agreement",
        "msme_days_no_agreement": "MSME payment limit without agreement",
        "tds_interest_pct_month": "Interest on TDS shortfall (per month)",
    }
    out = []
    for k in keys:
        v, kind = SETTINGS[k]
        if k == "assumed_tax_rate":
            shown = f"{v * 100:.0f}%"
        elif k.endswith("_pct") or k in ("gst_interest_pct_pa", "tds_interest_pct_month"):
            shown = f"{v:g}%"
        elif k.startswith("msme_days"):
            shown = f"{v} days"
        else:
            shown = inr(v)
        out.append([labels[k], shown, kind])
    return out


def _rule(rid, name, law, explain, findings, settings, watch=None, ok=None, tables=None, notes=None):
    exposure = sum(f["exposure"] for f in findings)
    return {
        "id": rid, "name": name, "law": law, "explain": explain,
        "status": "at_risk" if findings else "ok",
        "headline": (f"{_plural(len(findings), 'finding')}, {inr(exposure)} flagged" if findings
                     else "No issues found in the data checked"),
        "exposure": exposure, "findings": findings, "settings": settings,
        "watch": watch or [], "ok": ok or [], "tables": tables or [], "notes": notes or [],
    }


# ----------------------------------------------- 1. Section 269ST (cash in)
def check_cash_received(db: Session):
    limit = S("cash_receipt_limit")
    rows = db.query(Voucher).filter(Voucher.voucher_type == "Receipt",
                                    Voucher.payment_mode == "Cash").all()
    groups = defaultdict(list)
    for v in rows:
        groups[(v.party_name, v.voucher_date)].append(v)

    findings, watch = [], []
    for (party, day), vs in sorted(groups.items(), key=lambda kv: kv[0][1]):
        total = sum(v.amount for v in vs)
        if total >= limit:
            kind = "Split cash receipts" if len(vs) > 1 else "Single large cash receipt"
            findings.append(_finding(
                "high", party, f"{kind} reached the {inr(limit)} limit",
                f"{party} paid {inr(total)} in cash on {_fmt_date(day)} across {_plural(len(vs), 'receipt')}. "
                f"A person may not receive {inr(limit)} or more in cash from one party in a day; "
                f"splitting it into several receipts does not avoid the limit.",
                total, "Penalty equal to the cash received",
                "Take the balance by bank transfer or cheque and stop accepting cash from this party. "
                "Keep a written note of why cash was received.",
                ["Voucher #", "Date", "Party", "Cash received"],
                [[v.id, _fmt_date(v.voucher_date), v.party_name, inr(v.amount)] for v in vs]))
        elif total >= limit * S("watch_ratio"):
            watch.append(f"{party} paid {inr(total)} in cash on {_fmt_date(day)} "
                         f"({total / limit * 100:.0f}% of the limit).")

    return _rule(
        "cash_received", "Cash received limit",
        "Section 269ST (old Act). Reported as Section 186 in the Income-tax Act 2025 \u2013 verify.",
        "Adds up cash receipts per party per day and flags totals of \u20b92 lakh or more, "
        "including receipts split across several vouchers.",
        findings, _settings_view("cash_receipt_limit"), watch=watch,
        notes=["Cannot detect the 'single transaction' and 'one event or occasion' limbs across days, "
               "because receipts are not linked to invoices."])


# --------------------------------------------- 2. Section 40A(3) (cash out)
def check_cash_paid(db: Session):
    profiles = {p.party_name: p for p in db.query(SupplierProfile).all()}
    rows = db.query(Voucher).filter(Voucher.voucher_type == "Payment",
                                    Voucher.payment_mode == "Cash").all()
    groups = defaultdict(list)
    for v in rows:
        groups[(v.party_name, v.voucher_date)].append(v)

    rate = S("assumed_tax_rate")
    findings, watch = [], []
    for (party, day), vs in sorted(groups.items(), key=lambda kv: kv[0][1]):
        prof = profiles.get(party)
        transporter = bool(prof and prof.is_transporter)
        limit = S("cash_payment_limit_transporter") if transporter else S("cash_payment_limit")
        total = sum(v.amount for v in vs)
        if total > limit:
            findings.append(_finding(
                "medium", party, f"Cash payments above {inr(limit)} in one day",
                f"{inr(total)} was paid in cash to {party} on {_fmt_date(day)} across {_plural(len(vs), 'payment')}. "
                f"If this is a business expense it can be disallowed in full; at an assumed "
                f"{rate * 100:.0f}% tax rate that is about {inr(total * rate)} of extra tax.",
                total, "Expense that may be disallowed",
                "Pay by cheque, bank transfer or UPI from now on. For this payment, check whether any "
                "exception applies before filing.",
                ["Voucher #", "Date", "Party", "Cash paid"],
                [[v.id, _fmt_date(v.voucher_date), v.party_name, inr(v.amount)] for v in vs]))
        elif total >= limit * S("watch_ratio"):
            tag = " (transporter limit)" if transporter else ""
            watch.append(f"{party} was paid {inr(total)} in cash on {_fmt_date(day)}{tag} "
                         f"\u2013 {total / limit * 100:.0f}% of the {inr(limit)} limit.")

    return _rule(
        "cash_paid", "Cash payment limit",
        "Section 40A(3) (old Act). New-Act section number not verified.",
        "Adds up cash payments per party per day and flags totals above \u20b910,000 "
        "(\u20b935,000 for goods transporters).",
        findings, _settings_view("cash_payment_limit", "cash_payment_limit_transporter", "assumed_tax_rate"),
        watch=watch,
        notes=["Checks payments only; the law also looks at the bill amount. "
               "Exceptions (for example payments to banks) are not modelled."])


# --------------------------------------------------------- 3. GST returns
def _gst_checks(db: Session):
    """Returns (findings, monthly_itc_table, chase_table, output_table)."""
    interest_pa = S("gst_interest_pct_pa")

    purchases = db.query(Voucher).filter(Voucher.voucher_type == "Purchase").all()
    sales = db.query(Voucher).filter(Voucher.voucher_type == "Sales").all()
    two_b = {(i.supplier_gstin, i.invoice_no): i for i in db.query(Gstr2bInvoice).all()}
    two_b_by_month = defaultdict(float)
    for i in two_b.values():
        two_b_by_month[i.month] += i.tax_amount
    returns = db.query(GstReturn).order_by(GstReturn.month).all()

    # --- match each purchase invoice against GSTR-2B
    unmatched_by_month = defaultdict(list)
    books_itc = defaultdict(float)
    for v in purchases:
        month = v.voucher_date.strftime("%Y-%m")
        books_itc[month] += v.gst_amount or 0
        match = two_b.get((v.gstin, v.invoice_no))
        if match is None:
            unmatched_by_month[month].append((v, "Missing from GSTR-2B"))
        elif abs(match.tax_amount - (v.gst_amount or 0)) > 1:
            unmatched_by_month[month].append((v, "Amount differs"))

    findings, itc_rows = [], []
    for r in returns:
        claimed = r.gstr3b_itc_claimed
        in_2b = two_b_by_month.get(r.month, 0)
        excess = claimed - in_2b
        pct = (excess / in_2b * 100) if in_2b else 0
        flagged = excess >= S("itc_excess_min") and pct >= S("itc_excess_pct")
        status = "Flag" if flagged else ("Minor gap" if excess > 1 else "OK")
        itc_rows.append([_month_label(r.month), inr(books_itc.get(r.month, 0)), inr(in_2b),
                         inr(claimed), inr(max(excess, 0)), f"{max(pct, 0):.1f}%", status])
        if flagged:
            items = unmatched_by_month.get(r.month, [])
            per_supplier = defaultdict(float)
            for v, _ in items:
                per_supplier[v.party_name] += v.gst_amount or 0
            who = ", ".join(f"{s} ({inr(t)})" for s, t in
                            sorted(per_supplier.items(), key=lambda kv: -kv[1]))
            month_end = date(int(r.month[:4]), int(r.month[5:]), 28) + timedelta(days=4)
            month_end = month_end - timedelta(days=month_end.day)
            months_late = max(1, math.ceil(max((REFERENCE_DATE - month_end).days, 0) / 30))
            interest = excess * interest_pa / 100 / 12 * months_late
            findings.append(_finding(
                "high" if pct >= 20 else "medium", "GST input credit",
                f"{_month_label(r.month)}: credit claimed exceeds GSTR-2B by {inr(excess)}",
                f"You claimed {inr(claimed)} of input credit in GSTR-3B but GSTR-2B shows only "
                f"{inr(in_2b)} \u2013 {pct:.0f}% more. The gap comes from invoices your suppliers have not "
                f"reported: {who or 'see evidence'}. If reversed late, interest could be about "
                f"{inr(interest)} (assumed {interest_pa:g}% a year).",
                excess, "Input credit at risk",
                f"Ask {', '.join(per_supplier) or 'the suppliers'} to file their GSTR-1, or reverse "
                f"{inr(excess)} of credit in your next GSTR-3B until they do.",
                ["Supplier", "Invoice", "Invoice date", "Tax", "Issue"],
                [[v.party_name, v.invoice_no, _fmt_date(v.voucher_date), inr(v.gst_amount or 0), why]
                 for v, why in items]))

    # --- chase list: every unmatched invoice, grouped by supplier
    chase = defaultdict(lambda: {"n": 0, "tax": 0.0, "oldest": None})
    for items in unmatched_by_month.values():
        for v, _ in items:
            c = chase[v.party_name]
            c["n"] += 1
            c["tax"] += v.gst_amount or 0
            c["oldest"] = v.voucher_date if c["oldest"] is None else min(c["oldest"], v.voucher_date)
    chase_rows = [[s, c["n"], inr(c["tax"]), _fmt_date(c["oldest"])]
                  for s, c in sorted(chase.items(), key=lambda kv: -kv[1]["tax"])]

    # --- output tax: GSTR-1 reported vs GSTR-3B paid
    books_out = defaultdict(float)
    for v in sales:
        books_out[v.voucher_date.strftime("%Y-%m")] += v.gst_amount or 0
    out_rows = []
    for r in returns:
        gap = r.gstr1_tax - r.gstr3b_tax_paid
        pct = (gap / r.gstr1_tax * 100) if r.gstr1_tax else 0
        flagged = gap >= S("output_gap_min") and pct >= S("output_gap_pct")
        out_rows.append([_month_label(r.month), inr(books_out.get(r.month, 0)), inr(r.gstr1_tax),
                         inr(r.gstr3b_tax_paid), inr(max(gap, 0)),
                         "Flag" if flagged else ("Minor gap" if gap > 1 else "OK")])
        if flagged:
            month_end = date(int(r.month[:4]), int(r.month[5:]), 28) + timedelta(days=4)
            month_end = month_end - timedelta(days=month_end.day)
            months_late = max(1, math.ceil(max((REFERENCE_DATE - month_end).days, 0) / 30))
            interest = gap * interest_pa / 100 / 12 * months_late
            findings.append(_finding(
                "high" if pct >= 20 else "medium", "GST output tax",
                f"{_month_label(r.month)}: tax reported in GSTR-1 is {inr(gap)} more than paid in GSTR-3B",
                f"GSTR-1 shows {inr(r.gstr1_tax)} of output tax but only {inr(r.gstr3b_tax_paid)} was "
                f"paid in GSTR-3B ({pct:.0f}% short). Estimated interest on the shortfall is about "
                f"{inr(interest)} (assumed {interest_pa:g}% a year).",
                gap, "Tax shortfall",
                "Check whether GSTR-1 was over-reported or GSTR-3B under-paid. If under-paid, pay the "
                "difference with interest before the portal asks for it.",
                ["Month", "Per sales books", "GSTR-1 tax", "GSTR-3B paid", "Gap"],
                [[_month_label(r.month), inr(books_out.get(r.month, 0)), inr(r.gstr1_tax),
                  inr(r.gstr3b_tax_paid), inr(gap)]]))

    return findings, itc_rows, chase_rows, out_rows


def check_gst(db: Session):
    findings, itc_rows, chase_rows, out_rows = _gst_checks(db)
    tables = [
        {"title": "Input credit: books vs GSTR-2B vs GSTR-3B",
         "columns": ["Month", "Per purchase books", "In GSTR-2B", "Claimed in GSTR-3B",
                     "Excess claimed", "Excess %", "Status"], "rows": itc_rows},
        {"title": "Supplier chase list (invoices not in GSTR-2B)",
         "columns": ["Supplier", "Invoices", "Credit at risk", "Oldest invoice"], "rows": chase_rows},
        {"title": "Output tax: GSTR-1 vs GSTR-3B",
         "columns": ["Month", "Per sales books", "GSTR-1 tax", "GSTR-3B paid", "Gap", "Status"],
         "rows": out_rows},
    ]
    return _rule(
        "gst", "GST return reconciliation",
        "CGST Rules 88C and 88D (the checks behind notices DRC-01B and DRC-01C).",
        "Compares input credit claimed with what suppliers reported in GSTR-2B, and output tax "
        "reported in GSTR-1 with tax paid in GSTR-3B \u2013 before the GST portal does.",
        findings, _settings_view("itc_excess_min", "itc_excess_pct", "output_gap_min",
                                 "output_gap_pct", "gst_interest_pct_pa"),
        tables=tables,
        notes=["Flag limits are deliberately low demo values. The portal's own limits for notices "
               "are much higher, so a small business would rarely get a notice \u2013 the real value "
               "here is catching supplier gaps early.",
               "GSTR-2B and GSTR-3B figures are synthetic in this build."])


# ---------------------------------------------------- 4. MSME 43B(h)
def check_msme(db: Session):
    profiles = {p.party_name: p for p in db.query(SupplierProfile).all()}
    bills = db.query(Voucher).filter(Voucher.voucher_type == "Payment",
                                     Voucher.payment_type == "Payable",
                                     Voucher.status != "Cleared").all()
    rate = S("assumed_tax_rate")
    breached = defaultdict(list)
    watch = []
    for v in sorted(bills, key=lambda b: b.voucher_date):
        prof = profiles.get(v.party_name)
        if not prof or not prof.is_msme:
            continue
        limit = S("msme_days_agreement") if prof.has_agreement else S("msme_days_no_agreement")
        days = (REFERENCE_DATE - v.voucher_date).days
        if days > limit:
            breached[v.party_name].append((v, days, limit))
        elif limit - days <= 7:
            watch.append(f"{v.party_name}: {inr(v.amount)} bill dated {_fmt_date(v.voucher_date)} "
                         f"has {limit - days} day(s) left before the {limit}-day limit.")

    findings = []
    for party, items in breached.items():
        total = sum(v.amount for v, _, _ in items)
        limit = items[0][2]
        oldest = max(d for _, d, _ in items)
        findings.append(_finding(
            "high", party, f"{_plural(len(items), 'bill')} unpaid past the {limit}-day MSME limit",
            f"{party} is marked as a micro/small supplier. {_plural(len(items), 'bill')} totalling "
            f"{inr(total)} {'is' if len(items) == 1 else 'are'} past the {limit}-day limit "
            f"(oldest {oldest} days). If still unpaid on 31 March, the "
            f"amount cannot be claimed as an expense \u2013 about {inr(total * rate)} of extra tax at an "
            f"assumed {rate * 100:.0f}% rate.",
            total, "Expense that may be disallowed",
            "Pay these bills now, oldest first. Check whether the supplier is a manufacturer or "
            "service provider, since traders may fall outside the rule.",
            ["Bill date", "Amount", "Days outstanding", "Limit (days)", "Days over"],
            [[_fmt_date(v.voucher_date), inr(v.amount), d, lim, d - lim] for v, d, lim in items]))
    findings.sort(key=lambda f: -f["exposure"])

    return _rule(
        "msme", "MSME payment deadline",
        "Section 43B(h) (old Act). Reported as Section 37(2)(g) in the Income-tax Act 2025 \u2013 verify.",
        "Finds unpaid bills to micro and small suppliers that are past 45 days (with a written "
        "agreement) or 15 days (without one).",
        findings, _settings_view("msme_days_agreement", "msme_days_no_agreement", "assumed_tax_rate"),
        watch=watch,
        notes=["Counts days from the bill date; the law counts from acceptance of the goods.",
               "Whether a supplier is MSME comes from the supplier profile table, not from Tally."])


# ------------------------------------------------------------- 5. TDS
def _fy_start():
    ref = REFERENCE_DATE
    return date(ref.year if ref.month >= 4 else ref.year - 1, 4, 1)


def check_tds(db: Session):
    profiles = {p.party_name: p for p in db.query(SupplierProfile).all()}
    fy_start = _fy_start()
    pays = [v for v in db.query(Voucher).filter(Voucher.voucher_type == "Payment").all()
            if v.nature and v.voucher_date >= fy_start]
    groups = defaultdict(list)
    for v in pays:
        groups[(v.party_name, v.nature)].append(v)

    interest_pm = S("tds_interest_pct_month")
    findings, watch, ok = [], [], []
    for (party, nature), vs in sorted(groups.items()):
        spec = TDS_NATURES.get(nature)
        if not spec:
            continue
        total = sum(v.amount for v in vs)
        prof = profiles.get(party)
        if nature == "Contractor":
            rate = spec["rate_individual"] if (prof and prof.payee_type == "Individual") else spec["rate_other"]
        else:
            rate = spec["rate"]

        if "monthly" in spec:
            eligible = [v for v in vs if v.amount > spec["monthly"]]
        else:
            triggered = total > spec["annual"] or (
                "single" in spec and any(v.amount > spec["single"] for v in vs))
            eligible = vs if triggered else []

        if not eligible:
            if "annual" in spec and total >= spec["annual"] * S("watch_ratio"):
                watch.append(f"{party} ({spec['label'].lower()}): {inr(total)} paid this year, "
                             f"{total / spec['annual'] * 100:.0f}% of the {inr(spec['annual'])} threshold.")
            continue

        required = sum(rate / 100 * v.amount for v in eligible)
        deducted = sum(v.tds_deducted or 0 for v in eligible)
        rows, shortfall, interest = [], 0.0, 0.0
        for v in eligible:
            req = rate / 100 * v.amount
            short = max(0.0, req - (v.tds_deducted or 0))
            shortfall += short
            interest += short * interest_pm / 100 * _months_since(v.voucher_date)
            rows.append([_fmt_date(v.voucher_date), inr(v.amount), f"{rate:g}%", inr(req),
                         inr(v.tds_deducted or 0), inr(short)])

        if shortfall < 1:
            ok.append(f"{party} ({spec['label'].lower()}): {inr(total)} paid, TDS {inr(deducted)} "
                      f"deducted at {rate:g}% \u2013 correct.")
            continue

        findings.append(_finding(
            "high" if shortfall >= 10000 else "medium", party,
            f"TDS short by {inr(shortfall)} on {spec['label'].lower()}",
            f"{party} was paid {inr(total)} for {spec['label'].lower()} this financial year. "
            f"At {rate:g}% the TDS required is {inr(required)}, but {inr(deducted)} was deducted \u2013 "
            f"a shortfall of {inr(shortfall)}, plus about {inr(interest)} interest "
            f"(assumed {interest_pm:g}% a month).",
            shortfall + interest, "Tax shortfall plus interest",
            "Deposit the shortfall with interest and deduct at the correct rate from the next payment. "
            "Collect the payee's PAN and category (individual or company) before paying.",
            ["Payment date", "Gross payment", "Rate", "TDS required", "TDS deducted", "Shortfall"], rows))

    findings.sort(key=lambda f: -f["exposure"])
    return _rule(
        "tds", "TDS shortfall",
        "Section 393, Income-tax Act 2025 (applies from 1 April 2026).",
        "For each payee and nature of payment this financial year, checks whether the payments crossed "
        "the TDS threshold and whether enough tax was deducted.",
        findings, _settings_view("tds_interest_pct_month"), watch=watch, ok=ok,
        tables=[{"title": "Thresholds and rates used (verify before relying on them)",
                 "columns": ["Nature of payment", "Threshold", "Rate"],
                 "rows": [["Contractor", "\u20b930,000 single or \u20b91,00,000 a year", "1% individual, 2% others"],
                          ["Professional fees", "\u20b950,000 a year", "10%"],
                          ["Commission / brokerage", "\u20b920,000 a year", "2%"],
                          ["Rent (land / building)", "\u20b950,000 a month", "10%"],
                          ["Rent (plant / machinery)", "\u20b950,000 a month", "2%"]]}],
        notes=["Applies the rate to every payment once a threshold is crossed (a simplification).",
               "Not covered: missing PAN (higher rate), technical fees and late deposit of TDS."])


# ------------------------------------------------------------- assembly
def build_compliance(db: Session):
    rules = [check_cash_received(db), check_cash_paid(db), check_gst(db),
             check_msme(db), check_tds(db)]
    findings = [f for r in rules for f in r["findings"]]
    return {
        "reference_date": REFERENCE_DATE.isoformat(),
        "summary": {
            "rules": len(rules),
            "rules_at_risk": sum(1 for r in rules if r["status"] == "at_risk"),
            "findings": len(findings),
            "high": sum(1 for f in findings if f["severity"] == "high"),
            "amount_flagged": sum(f["exposure"] for f in findings),
        },
        "rules": rules,
        "not_covered": NOT_COVERED,
        "disclaimer": ("Indicative findings generated from your data and public rules. "
                       "This is not tax advice. Thresholds tagged 'demo' or 'assumed' are "
                       "adjustable settings; confirm all figures against official sources."),
    }


def alert_rows(db: Session):
    """Findings in the [severity, title, description] shape the Alert Centre uses."""
    rows = []
    for rule in build_compliance(db)["rules"]:
        for f in rule["findings"]:
            rows.append([f["severity"], f"{rule['name']}: {f['title']}", f["summary"]])
    return rows