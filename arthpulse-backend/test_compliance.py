"""Every planted violation must be flagged; every near-miss must stay unflagged."""
from app.database import SessionLocal
from app.compliance import build_compliance

db = SessionLocal()
report = build_compliance(db)
rules = {r["id"]: r for r in report["rules"]}
failures = []

def check(name, condition):
    print(("PASS  " if condition else "FAIL  ") + name)
    if not condition:
        failures.append(name)

def parties(rule_id):
    return [f["party"] for f in rules[rule_id]["findings"]]

def text(rule_id):
    return " ".join(f["summary"] + f["title"] for f in rules[rule_id]["findings"])

# 1. Section 269ST
check("269ST: Sapphire Retail split cash (2,15,000) flagged", parties("cash_received") == ["Sapphire Retail"])
check("269ST: exposure is exactly 2,15,000", rules["cash_received"]["findings"][0]["exposure"] == 215000)
check("269ST: Fresh Mart 1,90,000 NOT flagged but on watch list", "Fresh Mart" not in parties("cash_received")
      and any("Fresh Mart" in w for w in rules["cash_received"]["watch"]))

# 2. Section 40A(3)
check("40A(3): Apex Packaging 13,000 cash in a day flagged", parties("cash_paid") == ["Apex Packaging"])
check("40A(3): transporter 30,000 (limit 35,000) NOT flagged", "Swift Logistics" not in parties("cash_paid"))
check("40A(3): CleanCo 9,000 NOT flagged", "CleanCo Supplies" not in parties("cash_paid"))

# 3. GST
gst = rules["gst"]["findings"]
titles = [f["title"] for f in gst]
check("GST: August input credit excess flagged", any("Aug 2026" in t and "credit" in t for t in titles))
check("GST: July output tax gap (30,000) flagged", any("Jul 2026" in t and "GSTR-1" in t for t in titles))
check("GST: June small ITC gap NOT flagged", not any("Jun 2026" in t for t in titles))
check("GST: May small output gap (2,000) NOT flagged", not any("May 2026" in t for t in titles))
aug = [f for f in gst if "Aug 2026" in f["title"] and "credit" in f["title"]][0]
check("GST: August chase list names Apex Packaging and Orchard Nuts",
      {r[0] for r in aug["evidence"]["rows"]} == {"Apex Packaging", "Orchard Nuts"})
check("GST: August excess equals 71,800 + 33,148", aug["exposure"] == 104948)

# 4. MSME 43B(h)
msme = rules["msme"]["findings"]
gh = [f for f in msme if f["party"] == "Golden Hive"]
check("MSME: Golden Hive 2,10,000 bill (day 46 of 45) flagged", len(gh) == 1 and gh[0]["exposure"] >= 210000)
check("MSME: non-MSME suppliers never flagged",
      not {"Harvest Foods", "Sunrise Traders", "Orchard Nuts"} & set(parties("msme")))
apex = [f for f in msme if f["party"] == "Apex Packaging"]
check("MSME: Apex bill dated 20 Aug (day 5 of 15) NOT in evidence",
      all("20 Aug 2026" not in str(f["evidence"]["rows"]) for f in apex))

# 5. TDS
tds = {f["party"]: f for f in rules["tds"]["findings"]}
check("TDS: BuildRight (1.2L contractor, no TDS) flagged, 2% = 2,400 required",
      "BuildRight Works" in tds and "₹2,400" in tds["BuildRight Works"]["summary"])
check("TDS: CA Desai short deduction flagged, shortfall 4,000",
      "CA Desai & Associates" in tds and "short by ₹4,000" in tds["CA Desai & Associates"]["title"])
check("TDS: Shah Properties rent, 5 months x 6,000 = 30,000 short",
      "Shah Properties" in tds and "short by ₹30,000" in tds["Shah Properties"]["title"])
check("TDS: Star Agencies commission 600 short", "Star Agencies" in tds and "short by ₹600" in tds["Star Agencies"]["title"])
check("TDS: Kiran Legal (correct 10%) NOT flagged, listed as compliant",
      "Kiran Legal" not in tds and any("Kiran Legal" in o for o in rules["tds"]["ok"]))
check("TDS: Sharma Contractors (28,000, under limits) NOT flagged", "Sharma Contractors" not in tds)
check("TDS: Agent Raman (18,000 of 20,000) NOT flagged, on watch list",
      "Agent Raman" not in tds and any("Agent Raman" in w for w in rules["tds"]["watch"]))

print("\nSUMMARY:", report["summary"])
for r in report["rules"]:
    print(f"  {r['name']:<28} {r['status']:<8} {r['headline']}")
print("\nRESULT:", "ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}")