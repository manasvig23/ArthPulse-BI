"""
Talk to TallyPrime over the local XML gateway (default http://localhost:9000).

TallyPrime Educational only accepts voucher dates on the 1st, 2nd and 31st.
The full synthetic Excel set is for the presentation. This module builds a
matching Educational import (same parties, products and planted compliance
stories, compressed onto those three days) and can pull that company back
into ArthPulse when the user clicks Sync TallyPrime.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from io import BytesIO

import requests
from dotenv import load_dotenv

load_dotenv()

TALLY_URL = os.environ.get("TALLY_URL", "http://localhost:9000")
TALLY_COMPANY = os.environ.get("TALLY_COMPANY", "").strip()
TALLY_YEAR = int(os.environ.get("TALLY_YEAR", "2026"))
TIMEOUT = int(os.environ.get("TALLY_TIMEOUT", "25"))

# Educational-legal days in Apr–Aug of TALLY_YEAR
def educational_dates(year=TALLY_YEAR):
    days = []
    for month in (4, 5, 6, 7, 8):
        days.append(date(year, month, 1))
        days.append(date(year, month, 2))
        if month in (5, 7, 8):
            days.append(date(year, month, 31))
    return days


def _xml(tag, text="", attrs=None):
    a = "".join(f' {k}="{v}"' for k, v in (attrs or {}).items())
    if text == "":
        return f"<{tag}{a}></{tag}>"
    return f"<{tag}{a}>{text}</{tag}>"


def _envelope(inner, request="Export"):
    return f"""<ENVELOPE>
 <HEADER>
  <VERSION>1</VERSION>
  <TALLYREQUEST>{request}</TALLYREQUEST>
 </HEADER>
 <BODY>
  {inner}
 </BODY>
</ENVELOPE>
"""


def ping(url=None):
    url = url or TALLY_URL
    body = _envelope("<DESC></DESC>")
    try:
        r = requests.post(url, data=body.encode("utf-8"),
                          headers={"Content-Type": "text/xml"}, timeout=TIMEOUT)
        return r.status_code == 200, r.text[:2000]
    except requests.RequestException as e:
        return False, str(e)


def post_xml(xml_text, url=None):
    url = url or TALLY_URL
    r = requests.post(url, data=xml_text.encode("utf-8"),
                      headers={"Content-Type": "text/xml;charset=utf-8"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def list_companies(url=None):
    tdl = """<DESC>
  <STATICVARIABLES>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
  </STATICVARIABLES>
  <TDL>
   <TDLMESSAGE>
    <REPORT NAME="ArthPulseCos">
     <FORMS>ArthPulseCos</FORMS>
    </REPORT>
    <FORM NAME="ArthPulseCos">
     <PARTS>ArthPulseCos</PARTS>
    </FORM>
    <PART NAME="ArthPulseCos">
     <LINES>ArthPulseCos</LINES>
     <REPEAT>ArthPulseCos : ArthPulseCoCol</REPEAT>
     <SCROLLED>Vertical</SCROLLED>
    </PART>
    <LINE NAME="ArthPulseCos">
     <FIELDS>ArthPulseCoName</FIELDS>
    </LINE>
    <FIELD NAME="ArthPulseCoName">
     <SET>$Name</SET>
     <XMLTAGS>COMPANYNAME</XMLTAGS>
    </FIELD>
    <COLLECTION NAME="ArthPulseCoCol">
     <TYPE>Company</TYPE>
    </COLLECTION>
   </TDLMESSAGE>
  </TDL>
 </DESC>"""
    raw = post_xml(_envelope(tdl), url)
    names = re.findall(r"<COMPANYNAME>(.*?)</COMPANYNAME>", raw, re.I | re.S)
    return [n.strip() for n in names if n.strip()]


def _local(tag):
    return tag.split("}")[-1].upper() if tag else ""


def _text(el):
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _amount(text):
    if not text:
        return 0.0
    t = text.replace(",", "").replace("Dr", "").replace("Cr", "").replace("₹", "").strip()
    try:
        return abs(float(t))
    except ValueError:
        return 0.0


def _parse_date(text):
    if not text:
        return None
    t = text.strip()
    for fmt in ("%Y%m%d", "%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t[:len(datetime.now().strftime(fmt)) if False else len(t)], fmt).date()
        except ValueError:
            continue
    if re.fullmatch(r"\d{8}", t):
        return date(int(t[:4]), int(t[4:6]), int(t[6:8]))
    return None


def parse_vouchers(xml_text):
    """Turn a Tally export into dicts our importer understands."""
    rows = []
    try:
        root = ET.parse(BytesIO(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)).getroot()
    except ET.ParseError:
        xml_text = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)", "&amp;", xml_text)
        root = ET.fromstring(xml_text)

    for node in root.iter():
        if _local(node.tag) != "VOUCHER":
            continue
        fields = {_local(c.tag): _text(c) for c in list(node) if len(c) == 0}
        vtype = (fields.get("VOUCHERTYPENAME") or node.attrib.get("VCHTYPE") or "Journal").strip()
        party = fields.get("PARTYLEDGERNAME") or fields.get("PARTYNAME") or "Unknown"
        day = _parse_date(fields.get("DATE") or fields.get("EFFECTIVEDATE"))
        amount = _amount(fields.get("AMOUNT"))
        if not amount:
            for led in node.iter():
                if _local(led.tag) == "AMOUNT" and _text(led):
                    amount = max(amount, _amount(_text(led)))
        item = ""
        qty = 0.0
        for inv in node.iter():
            if _local(inv.tag) in ("STOCKITEMNAME",):
                item = _text(inv) or item
            if _local(inv.tag) == "ACTUALQTY":
                qty = _amount(_text(inv)) or qty
        kind = "Sales"
        low = vtype.lower()
        if "purchase" in low:
            kind = "Purchase"
        elif "receipt" in low or "contra" in low:
            kind = "Receipt"
        elif "payment" in low:
            kind = "Payment"
        elif "sales" in low or "invoice" in low:
            kind = "Sales"
        else:
            continue
        mode = "Cash" if "cash" in (fields.get("NARRATION") or "").lower() else "Bank"
        for led in node.iter():
            if _local(led.tag) == "LEDGERNAME" and "cash" in _text(led).lower():
                mode = "Cash"
        rows.append({
            "date": day,
            "voucher_type": kind,
            "party": party,
            "product": item or "Unspecified",
            "amount": amount,
            "quantity": qty,
            "invoice": fields.get("VOUCHERNUMBER") or fields.get("REFERENCE"),
            "guid": node.attrib.get("GUID") or fields.get("GUID"),
            "mode": mode,
            "narration": fields.get("NARRATION") or "",
            "gstin": fields.get("PARTYGSTIN") or "",
        })
    return rows


def parse_stock(xml_text):
    rows = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        xml_text = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)", "&amp;", xml_text)
        root = ET.fromstring(xml_text)
    for node in root.iter():
        if _local(node.tag) != "STOCKITEM":
            continue
        fields = {_local(c.tag): _text(c) for c in list(node) if len(c) == 0}
        name = fields.get("NAME") or node.attrib.get("NAME")
        if not name:
            continue
        rows.append({
            "product": name,
            "quantity": _amount(fields.get("CLOSINGBALANCE") or fields.get("CLOSINGQTY")),
            "value": _amount(fields.get("CLOSINGVALUE") or fields.get("CLOSINGBALANCEVALUE")),
            "category": fields.get("PARENT") or "Unassigned",
        })
    return rows


def export_vouchers(company=None, url=None):
    company = company or TALLY_COMPANY
    from_date = f"{TALLY_YEAR}0401"
    to_date = f"{TALLY_YEAR}0831"
    company_tag = f"<SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY>" if company else ""
    tdl = f"""<DESC>
  <STATICVARIABLES>
    {company_tag}
    <SVFROMDATE>{from_date}</SVFROMDATE>
    <SVTODATE>{to_date}</SVTODATE>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
  </STATICVARIABLES>
  <TDL>
   <TDLMESSAGE>
    <REPORT NAME="ArthPulseVch">
     <FORMS>ArthPulseVch</FORMS>
    </REPORT>
    <FORM NAME="ArthPulseVch">
     <PARTS>ArthPulseVch</PARTS>
    </FORM>
    <PART NAME="ArthPulseVch">
     <LINES>ArthPulseVch</LINES>
     <REPEAT>ArthPulseVch : ArthPulseVchCol</REPEAT>
     <SCROLLED>Vertical</SCROLLED>
    </PART>
    <LINE NAME="ArthPulseVch">
     <FIELDS>ArthPulseVchDummy</FIELDS>
     <XMLTAGS>VOUCHER</XMLTAGS>
    </LINE>
    <FIELD NAME="ArthPulseVchDummy">
     <SET>""</SET>
    </FIELD>
    <COLLECTION NAME="ArthPulseVchCol">
     <TYPE>Voucher</TYPE>
     <FETCH>Date, VoucherTypeName, PartyLedgerName, Amount, VoucherNumber, Narration, PartyGSTIN, GUID</FETCH>
     <FILTER>ArthPulseDateFilter</FILTER>
    </COLLECTION>
    <SYSTEM TYPE="Formulae" NAME="ArthPulseDateFilter">$Date &gt;= {from_date} AND $Date &lt;= {to_date}</SYSTEM>
   </TDLMESSAGE>
  </TDL>
 </DESC>"""
    return post_xml(_envelope(tdl), url)


def export_stock(company=None, url=None):
    company = company or TALLY_COMPANY
    company_tag = f"<SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY>" if company else ""
    tdl = f"""<DESC>
  <STATICVARIABLES>
    {company_tag}
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
  </STATICVARIABLES>
  <TDL>
   <TDLMESSAGE>
    <COLLECTION NAME="ArthPulseStock">
     <TYPE>StockItem</TYPE>
     <FETCH>Name, Parent, ClosingBalance, ClosingValue, BaseUnits</FETCH>
    </COLLECTION>
    <REPORT NAME="ArthPulseStockR">
     <FORMS>ArthPulseStockR</FORMS>
    </REPORT>
    <FORM NAME="ArthPulseStockR">
     <PARTS>ArthPulseStockR</PARTS>
    </FORM>
    <PART NAME="ArthPulseStockR">
     <LINES>ArthPulseStockR</LINES>
     <REPEAT>ArthPulseStockR : ArthPulseStock</REPEAT>
     <SCROLLED>Vertical</SCROLLED>
    </PART>
    <LINE NAME="ArthPulseStockR">
     <FIELDS>ArthPulseStName, ArthPulseStParent, ArthPulseStQty, ArthPulseStVal</FIELDS>
     <XMLTAGS>STOCKITEM</XMLTAGS>
    </LINE>
    <FIELD NAME="ArthPulseStName"><SET>$Name</SET><XMLTAGS>NAME</XMLTAGS></FIELD>
    <FIELD NAME="ArthPulseStParent"><SET>$Parent</SET><XMLTAGS>PARENT</XMLTAGS></FIELD>
    <FIELD NAME="ArthPulseStQty"><SET>$ClosingBalance</SET><XMLTAGS>CLOSINGBALANCE</XMLTAGS></FIELD>
    <FIELD NAME="ArthPulseStVal"><SET>$ClosingValue</SET><XMLTAGS>CLOSINGVALUE</XMLTAGS></FIELD>
   </TDLMESSAGE>
  </TDL>
 </DESC>"""
    return post_xml(_envelope(tdl), url)


def _d(d: date) -> str:
    return d.strftime("%Y%m%d")


def _ledger(name, parent, gstin=""):
    gst = f"<LEDGERGSTIN>{gstin}</LEDGERGSTIN>" if gstin else ""
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
 <LEDGER NAME="{name}" ACTION="Create">
  <NAME.LIST><NAME>{name}</NAME></NAME.LIST>
  <PARENT>{parent}</PARENT>
  {gst}
  <ISBILLWISEON>Yes</ISBILLWISEON>
 </LEDGER>
</TALLYMESSAGE>
"""


def _stock_item(name, parent):
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
 <STOCKITEM NAME="{name}" ACTION="Create">
  <NAME.LIST><NAME>{name}</NAME></NAME.LIST>
  <PARENT>{parent}</PARENT>
  <BASEUNITS>Nos</BASEUNITS>
 </STOCKITEM>
</TALLYMESSAGE>
"""


def _voucher(vchtype, day, party, amount, other_ledger, cash=False, narration="", invoice=""):
    mode_ledger = "Cash" if cash else other_ledger
    # Sales/Receipt: party debit, income/cash credit — signs follow Tally's ISDEEMEDPOSITIVE
    if vchtype in ("Sales", "Receipt"):
        party_pos, party_amt = "Yes", f"-{amount:.2f}"
        other_pos, other_amt = "No", f"{amount:.2f}"
        other_name = "Sales Accounts" if vchtype == "Sales" else mode_ledger
        if vchtype == "Receipt":
            other_name = "Cash" if cash else "Bank"
    else:
        party_pos, party_amt = "No", f"{amount:.2f}"
        other_pos, other_amt = "Yes", f"-{amount:.2f}"
        other_name = "Purchase Accounts" if vchtype == "Purchase" else ("Cash" if cash else "Bank")
    return f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
 <VOUCHER VCHTYPE="{vchtype}" ACTION="Create">
  <DATE>{_d(day)}</DATE>
  <EFFECTIVEDATE>{_d(day)}</EFFECTIVEDATE>
  <VOUCHERTYPENAME>{vchtype}</VOUCHERTYPENAME>
  <PARTYLEDGERNAME>{party}</PARTYLEDGERNAME>
  <REFERENCE>{invoice}</REFERENCE>
  <NARRATION>{narration}</NARRATION>
  <ALLLEDGERENTRIES.LIST>
   <LEDGERNAME>{party}</LEDGERNAME>
   <ISDEEMEDPOSITIVE>{party_pos}</ISDEEMEDPOSITIVE>
   <AMOUNT>{party_amt}</AMOUNT>
  </ALLLEDGERENTRIES.LIST>
  <ALLLEDGERENTRIES.LIST>
   <LEDGERNAME>{other_name}</LEDGERNAME>
   <ISDEEMEDPOSITIVE>{other_pos}</ISDEEMEDPOSITIVE>
   <AMOUNT>{other_amt}</AMOUNT>
  </ALLLEDGERENTRIES.LIST>
 </VOUCHER>
</TALLYMESSAGE>
"""


def build_educational_import(company=""):
    """
    Same story as the synthetic set, on Educational-legal dates only:
    split cash 269ST, 40A(3) cash, MSME overdue, TDS shortfall, plus SPIP activity.
    """
    y = TALLY_YEAR
    d = lambda m, day: date(y, m, day)
    customers = [
        ("Sapphire Retail", "27AAAAA0000A1Z1"),
        ("Metro Grocers", "07BBBBB0000B1Z2"),
        ("HomeStyle", "27CCCCC0000C1Z3"),
        ("Lakshmi Provisions", "29DDDDD0000D1Z4"),
        ("Fresh Mart", "33EEEEE0000E1Z5"),
        ("Kisan Stores", "10FFFFF0000F1Z6"),
        ("Daily Needs", "03GGGGG0000G1Z7"),
    ]
    suppliers = [
        ("Apex Packaging", "27HHHHH0000H1Z8"),
        ("Harvest Foods", "27IIIII0000I1Z9"),
        ("Golden Hive", "27JJJJJ0000J1Z0"),
        ("CleanCo Supplies", "27KKKKK0000K1Z1"),
        ("Swift Logistics", "27LLLLL0000L1Z2"),
        ("BuildRight Works", "27MMMMM0000M1Z3"),
        ("CA Desai & Associates", "27NNNNN0000N1Z4"),
        ("Shah Properties", "27OOOOO0000O1Z5"),
    ]
    products = [
        ("Organic Oats 1kg", "Breakfast"),
        ("Almond Granola 500g", "Breakfast"),
        ("Wildflower Honey 500g", "Honey"),
        ("Peanut Butter 340g", "Spreads"),
        ("Jaggery Powder 1kg", "Staples"),
        ("Compostable Pouches", "Packaging"),
        ("Rolled Oats Bulk", "Raw Material"),
        ("Honey Bulk", "Raw Material"),
    ]
    extras = ["Sales Accounts", "Purchase Accounts", "Cash", "Bank"]
    groups = ["Breakfast", "Honey", "Spreads", "Staples", "Packaging", "Raw Material"]

    parts = []
    for g in groups:
        parts.append(f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
 <STOCKGROUP NAME="{g}" ACTION="Create"><NAME.LIST><NAME>{g}</NAME></NAME.LIST><PARENT>Primary</PARENT></STOCKGROUP>
</TALLYMESSAGE>
""")
    for name, gstin in customers:
        parts.append(_ledger(name, "Sundry Debtors", gstin))
    for name, gstin in suppliers:
        parts.append(_ledger(name, "Sundry Creditors", gstin))
    for name in extras:
        parent = "Cash-in-Hand" if name == "Cash" else ("Bank Accounts" if name == "Bank" else "Direct Incomes" if "Sales" in name else "Direct Expenses")
        if name in ("Sales Accounts",):
            parent = "Sales Accounts" if False else "Direct Incomes"
        parts.append(_ledger(name, parent))
    for name, parent in products:
        parts.append(_stock_item(name, parent))

    v = []
    # Regular SPIP activity on 1st/2nd
    v.append(_voucher("Sales", d(4, 1), "Sapphire Retail", 180000, "Sales Accounts", invoice="S/0001", narration="Oats bulk order"))
    v.append(_voucher("Sales", d(4, 2), "Metro Grocers", 95000, "Sales Accounts", invoice="S/0002"))
    v.append(_voucher("Sales", d(5, 1), "Fresh Mart", 220000, "Sales Accounts", invoice="S/0003"))
    v.append(_voucher("Sales", d(5, 2), "Lakshmi Provisions", 140000, "Sales Accounts", invoice="S/0004"))
    v.append(_voucher("Sales", d(5, 31), "HomeStyle", 88000, "Sales Accounts", invoice="S/0005"))
    v.append(_voucher("Sales", d(6, 1), "Kisan Stores", 76000, "Sales Accounts", invoice="S/0006"))
    v.append(_voucher("Sales", d(6, 2), "Sapphire Retail", 165000, "Sales Accounts", invoice="S/0007"))
    v.append(_voucher("Sales", d(7, 2), "Fresh Mart", 210000, "Sales Accounts", invoice="S/0008"))
    v.append(_voucher("Sales", d(8, 1), "Lakshmi Provisions", 155000, "Sales Accounts", invoice="S/0009"))
    v.append(_voucher("Sales", d(8, 2), "Metro Grocers", 42000, "Sales Accounts", invoice="S/0010", narration="Declining customer"))

    v.append(_voucher("Purchase", d(4, 1), "Harvest Foods", 120000, "Purchase Accounts", invoice="SI/0001"))
    v.append(_voucher("Purchase", d(5, 1), "Apex Packaging", 80000, "Purchase Accounts", invoice="SI/0002"))
    v.append(_voucher("Purchase", d(6, 1), "CleanCo Supplies", 45000, "Purchase Accounts", invoice="SI/0003"))
    v.append(_voucher("Purchase", d(7, 1), "Golden Hive", 210000, "Purchase Accounts", invoice="SI/MSME"))
    v.append(_voucher("Purchase", d(8, 1), "Apex Packaging", 80000, "Purchase Accounts", invoice="SI/0004"))

    v.append(_voucher("Receipt", d(5, 31), "Fresh Mart", 220000, "Bank", invoice="R/0001"))
    v.append(_voucher("Receipt", d(6, 2), "Lakshmi Provisions", 140000, "Bank", invoice="R/0002"))
    v.append(_voucher("Receipt", d(8, 2), "HomeStyle", 40000, "Bank", invoice="R/0003"))

    # 269ST split cash, same party, 1 Jul (Educational-legal)
    v.append(_voucher("Receipt", d(7, 1), "Sapphire Retail", 120000, "Cash", cash=True, invoice="R/C1", narration="Cash receipt 1 of 2"))
    v.append(_voucher("Receipt", d(7, 1), "Sapphire Retail", 95000, "Cash", cash=True, invoice="R/C2", narration="Cash receipt 2 of 2"))
    # Near-miss under 2 lakh
    v.append(_voucher("Receipt", d(6, 1), "Fresh Mart", 90000, "Cash", cash=True, invoice="R/C3", narration="Cash"))
    v.append(_voucher("Receipt", d(6, 1), "Fresh Mart", 100000, "Cash", cash=True, invoice="R/C4", narration="Cash"))

    # 40A(3) cash 13,000 in a day
    v.append(_voucher("Payment", d(8, 1), "Apex Packaging", 6000, "Cash", cash=True, invoice="P/C1", narration="Cash"))
    v.append(_voucher("Payment", d(8, 1), "Apex Packaging", 7000, "Cash", cash=True, invoice="P/C2", narration="Cash"))
    v.append(_voucher("Payment", d(8, 2), "Swift Logistics", 30000, "Cash", cash=True, invoice="P/C3", narration="Cash transporter"))
    v.append(_voucher("Payment", d(7, 31), "CleanCo Supplies", 9000, "Cash", cash=True, invoice="P/C4", narration="Cash"))

    # Open MSME payable (Golden Hive 1 Jul, still unpaid)
    v.append(_voucher("Payment", d(7, 1), "Golden Hive", 210000, "Bank", invoice="P/MSME", narration="MSME bill pending ArthPulse"))

    # TDS stories
    v.append(_voucher("Payment", d(4, 1), "BuildRight Works", 30000, "Bank", invoice="P/T1", narration="Contractor TDS none"))
    v.append(_voucher("Payment", d(5, 1), "BuildRight Works", 30000, "Bank", invoice="P/T2", narration="Contractor TDS none"))
    v.append(_voucher("Payment", d(6, 1), "BuildRight Works", 30000, "Bank", invoice="P/T3", narration="Contractor TDS none"))
    v.append(_voucher("Payment", d(7, 1), "BuildRight Works", 30000, "Bank", invoice="P/T4", narration="Contractor TDS none"))
    v.append(_voucher("Payment", d(5, 2), "CA Desai & Associates", 50000, "Bank", invoice="P/T5", narration="Professional TDS short"))
    v.append(_voucher("Payment", d(7, 2), "CA Desai & Associates", 30000, "Bank", invoice="P/T6", narration="Professional TDS short"))
    v.append(_voucher("Payment", d(5, 31), "Shah Properties", 60000, "Bank", invoice="P/T7", narration="Rent TDS none"))
    v.append(_voucher("Payment", d(6, 2), "Shah Properties", 60000, "Bank", invoice="P/T8", narration="Rent TDS none"))
    v.append(_voucher("Payment", d(7, 31), "Shah Properties", 60000, "Bank", invoice="P/T9", narration="Rent TDS none"))
    v.append(_voucher("Payment", d(8, 1), "Shah Properties", 60000, "Bank", invoice="P/T10", narration="Rent TDS none"))

    parts.extend(v)
    company_tag = f"<SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY>" if company else ""
    return f"""<ENVELOPE>
 <HEADER>
  <TALLYREQUEST>Import Data</TALLYREQUEST>
 </HEADER>
 <BODY>
  <IMPORTDATA>
   <REQUESTDESC>
    <REPORTNAME>All Masters</REPORTNAME>
    <STATICVARIABLES>
     {company_tag}
    </STATICVARIABLES>
   </REQUESTDESC>
   <REQUESTDATA>
    {''.join(parts)}
   </REQUESTDATA>
  </IMPORTDATA>
 </BODY>
</ENVELOPE>
"""


def write_educational_file(path):
    xml = build_educational_import(TALLY_COMPANY)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    return path
