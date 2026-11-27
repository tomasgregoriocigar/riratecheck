#!/usr/bin/env python3
"""scripts/update_rates.py — RI Rate Check nightly Empower RI update (v4, Nov 26, 2026)
DRAFT ONLY — not seeded. Paste path in repo: scripts/update_rates.py

Source: the Empower RI rate card (RI DPUC),
https://www.ri.gov/app/dpuc/empowerri/rate_card
Parser pinned to the snapshot saved Nov 26, 2026
(tests/fixtures/empower_rate_card.html) and covered by
tests/test_update_rates.py against the known-good card of Nov 24-26, 2026:
benchmark 17.029c, 10/01/2026-03/31/2027, plus 8 competitive offers —
Major 15.29/12, Archer 15.319/19, Direct 15.49/11, Major 15.49/24,
Direct 15.69/12, Archer 15.999/12, Town Square 16.97/24, Think 17.1/12 (100%).

Standing standard (Nov 21, 2026):
- Apply ONLY offers explicitly listed on the card, matched on
  supplier + term. New/changed card offers get checked_date = today (ET);
  unchanged card offers keep their date; plan name / ETF / monthly fee stay
  null (not confirmed) unless a supplier's own published materials confirm
  them (the Major Energy 12-month $0/$0 confirmation is the standing example
  and is preserved, never extended to other offers by analogy).
- Card offers that disappear are removed.
- Advertised-only entries (not on the card, not the benchmark) keep their
  checked_date — never roll it forward — and are subject to the EXPIRY RULE
  below.
- EXPIRY RULE (PROPOSED Nov 26, 2026, for Tomás' approval): an
  advertised-only offer is removed, and listed in the run log, once its
  checked_date is more than 45 days old. Rationale: 30 days is too tight
  (monthly re-verification cadence would kill entries between checks);
  90 days would let a full rate season pass on a stale advertised price.
  45 days = one full monthly cycle plus a two-week grace window. The
  constant is ADVERTISED_ONLY_EXPIRY_DAYS below; nothing else in the script
  depends on the number.
- BENCHMARK (v4 sanity, Tomás Nov 26, 2026): the benchmark rate and
  period AUTO-APPLY from the card when (a) the rate is inside the 5c-40c
  band and (b) the period is continuous: if the period changed, the new
  period must start the day after the old period ends and must not start
  in the future. (The v3 25%-move limit was dropped in v4: it rejected
  every legitimate seasonal reset — summer 11.092c to winter 17.029c is
  +54%.) An applied change is reported in the run log. A benchmark that
  fails the checks is NOT applied: drift path (offers still apply, exit 2).
- BENCHMARK TEXT (v4): the benchmark rate and period also appear in
  index.html prose (hero, FAQ) and the meta description. The prose spots
  sit behind AUTO:benchmark_rate / AUTO:benchmark_period /
  AUTO:benchmark_next_start marker pairs, rewritten on every run from
  the dataset; the meta description rate is rewritten by a checked regex
  substitution (a comment marker cannot live inside an attribute value).
- TOWN DRIFT (v2 rule, unchanged): if a town program's stated rate period
  has ended, the script STILL applies and writes all offer changes first,
  then exits 2 with a clear DRIFT message. The workflow commits the offer
  changes and then fails the run on that exit code.
- HOMEPAGE DATE (v3): the index checked date NEVER moves backward — it is
  max(the date already on the page, the newest Empower checked_date).
- WRITE ORDER (v3): the new index.html content (checked date + the static
  offers table, item below) is fully built BEFORE the offers file is
  written, so a marker or build failure can never leave the dataset
  updated without its page.
- STATIC OFFERS TABLE (v3): the offers table is written into index.html
  through the <!--AUTO:offers_table--> marker pair, so the offers are in
  the page text for search engines and readers without JavaScript.
  Variable-rate offers are shown in their own table, apart, with no
  comparison column: a variable rate is never ranked as beating the
  default (Tomás, Nov 26, 2026 — same rule as app.js).
- Card unreachable or unparseable: exit 1, write nothing. Never guess.

All date stamps use America/New_York. index.html is rewritten ONLY through
the <!--AUTO:checked_date-->...<!--/AUTO--> marker pair, with an assert
that the new date landed, exactly as in update_oil.py.
"""
import json, re, sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")
TODAY_ET = datetime.now(ET).date()
ROOT = Path(__file__).resolve().parent.parent
OFFERS = ROOT / "data" / "supplier_offers.json"
TOWNS = ROOT / "data" / "aggregation_towns.json"
INDEX = ROOT / "index.html"
CARD = "https://www.ri.gov/app/dpuc/empowerri/rate_card"
ADVERTISED_ONLY_EXPIRY_DAYS = 45  # approved by Tomás Nov 26, 2026
BENCH_SANITY_MIN_CENTS = 5.0
BENCH_SANITY_MAX_CENTS = 40.0
NAME_MAP = {
    "Major Energy Electric Services, LLC": "Major Energy",
    "Archer Energy, LLC": "Archer Energy",
    "Think Energy, LLC": "Think Energy",
    "Direct Energy": "Direct Energy",
    "Town Square Energy": "Town Square Energy",
    "RI Energy": "Rhode Island Energy",
}

# ---------- Empower card parser (pinned to the saved snapshot) ----------
# Offers live in <tr class='offer-data'> rows. Supplier = logo img alt text.
# Competitive rows carry <p> cells: "N months", "R.CCC¢", "$ cost",
# "$ savings", renewable ("N/A" or "100%"). The benchmark row (RI Energy)
# has no term cell; its period appears in the Standard Offer table as
# MM/DD/YYYY- MM/DD/YYYY and its term in its plan-details modal.
def parse_empower_card(html: str) -> dict:
    rows = re.findall(r"<tr class='offer-data'>(.*?)</tr>", html, re.S)
    if len(rows) < 2:
        raise ValueError(f"Empower card: only {len(rows)} offer rows — unparseable")
    asof = re.search(r"As of:\s*([A-Za-z]+ \d{1,2}, \d{4})", html)
    benchmark, offers = None, []
    for row in rows:
        alt = re.search(r'alt="([^"]+)"', row)
        if not alt:
            raise ValueError("Empower card: offer row without supplier alt text")
        supplier = NAME_MAP.get(alt.group(1).strip(), alt.group(1).strip())
        cells = [c.strip() for c in re.findall(r"<p>([^<]+)</p>", row)]
        rate_m = [c for c in cells if c.endswith("¢")]
        if len(rate_m) != 1:
            raise ValueError(f"Empower card: {supplier} row has {len(rate_m)} rate cells")
        rate = float(rate_m[0].rstrip("¢"))
        term_m = [c for c in cells if re.fullmatch(r"\d+ months", c)]
        renewable = 0
        pct = [c for c in cells if re.fullmatch(r"\d+%", c)]
        if pct:
            renewable = int(pct[0].rstrip("%"))
        if supplier == "Rhode Island Energy":
            # The benchmark row's term cell carries the period as two <b>
            # dates: <b>10/01/2026-</b> <b>03/31/2027</b> (pinned, snapshot).
            dates = re.findall(r"(\d{2}/\d{2}/\d{4})", row)
            if len(dates) != 2:
                raise ValueError("Empower card: benchmark period not found in its row")
            benchmark = {"supplier": supplier, "rate_cents_per_kwh": rate,
                         "term_months": 6,
                         "period_start": dates[0], "period_end": dates[1],
                         "renewable_pct": renewable}
        else:
            if len(term_m) != 1:
                raise ValueError(f"Empower card: {supplier} row has no term cell")
            offers.append({"supplier": supplier, "rate_cents_per_kwh": rate,
                           "term_months": int(term_m[0].split()[0]),
                           "renewable_pct": renewable})
    if benchmark is None:
        raise ValueError("Empower card: benchmark (RI Energy) row not found")
    return {"as_of": asof.group(1) if asof else None,
            "benchmark": benchmark, "offers": offers}

# ---------- dataset helpers ----------
def is_benchmark(e: dict) -> bool:
    return e.get("supplier") == "Rhode Island Energy" and "Last Resort" in (e.get("plan_name") or "")

def is_empower(e: dict) -> bool:
    return "Empower RI" in (e.get("source_name") or "")

def town_drift(towns: list, today: date) -> list:
    problems = []
    months = {m: i + 1 for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"])}
    for t in towns:
        m = re.search(r"until (\w+) (\d{4})|-\s*(\w+) (\d{4})", t.get("rate_period", ""))
        if m:
            mon = months.get(m.group(1) or m.group(3))
            yr = int(m.group(2) or m.group(4))
            if mon and (yr, mon) < (today.year, today.month):
                problems.append(f"town {t.get('town')}: rate_period ended {m.group(0)}")
    return problems

def rewrite_index(html: str, key: str, val: str) -> str:
    return rewrite_index_multi(html, {key: val})

def rewrite_index_multi(html: str, values: dict) -> str:
    for key, val in values.items():
        pat = re.compile(rf'(<!--AUTO:{key}-->).*?(<!--/AUTO-->)', re.S)
        if not pat.search(html):
            raise ValueError(f"index.html: marker pair AUTO:{key} missing — refusing to write")
        n_pairs = len(pat.findall(html))
        html = pat.sub(lambda m: f"{m.group(1)}{val}{m.group(2)}", html)
        landed = re.findall(rf'<!--AUTO:{key}-->(.*?)<!--/AUTO-->', html, re.S)
        assert len(landed) == n_pairs and all(v == val for v in landed), \
            f"index.html: {key} rewrite count/landing wrong"
    return html

def index_checked_date(html: str):
    m = re.search(r'<!--AUTO:checked_date-->(\d{4}-\d{2}-\d{2})<!--/AUTO-->', html)
    return m.group(1) if m else None

def homepage_date(current_html: str, candidate: str) -> str:
    """The homepage date NEVER moves backward (v3 rule)."""
    existing = index_checked_date(current_html)
    return max(existing, candidate) if existing else candidate

def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def is_caution_flagged(e: dict) -> bool:
    """Same rule as app.js isCautionFlagged: 'Caution flag' in the notes,
    or a RI DPUC average premium of $900+ parsed from the notes."""
    notes = e.get("notes") or ""
    if "caution flag" in notes.lower():
        return True
    m = re.search(r'\+\$([\d,]+)', notes)
    return bool(m) and int(m.group(1).replace(",", "")) >= 900

def build_offers_table(dataset: list, bench_rate: float) -> str:
    """Static offers table for index.html (v4). Rules (Tomás, Nov 26, 2026):
    - a Status column on every table (Verified / Advertised only /
      Not served / Flagged);
    - ONLY verified offers are ranked (the main fixed-rate table);
    - flagged suppliers are listed APART, as app.js lists them;
    - variable-rate offers stay in their own table, never ranked as
      beating the default; unverified offers are listed apart, unranked.
    Display note: this static table is the page text for search engines
    and no-JavaScript readers. When app.js loads it renders the live
    cards into #offers and HIDES this static block (#offers-static), so
    offers are never shown twice."""
    served = [e for e in dataset if e.get("availability") != "not_served"
              and not is_benchmark(e)]
    notserved = [e for e in dataset if e.get("availability") == "not_served"
                 and not is_benchmark(e)]
    flagged = sorted([e for e in served if is_caution_flagged(e)],
                     key=lambda e: e["rate_cents_per_kwh"])
    rest = [e for e in served if not is_caution_flagged(e)]
    ranked = sorted([e for e in rest if e.get("rate_type") != "variable"
                     and e.get("verified")], key=lambda e: e["rate_cents_per_kwh"])
    variable = sorted([e for e in rest if e.get("rate_type") == "variable"],
                      key=lambda e: e["rate_cents_per_kwh"])
    unverified = sorted([e for e in rest if e.get("rate_type") != "variable"
                         and not e.get("verified")],
                        key=lambda e: e["rate_cents_per_kwh"])
    def status(e):
        if e.get("availability") == "not_served":
            return "Not served in RI"
        if is_caution_flagged(e):
            return "Flagged — track record"
        return "Verified" if e.get("verified") else "Advertised only"
    def row(e, compare):
        cells = [f"<td>{_esc(e['supplier'])}</td>",
                 f"<td>{_esc(e['plan_name'] or 'plan name not confirmed')}</td>",
                 f"<td>{e['rate_cents_per_kwh']}c/kWh</td>",
                 f"<td>{e['term_months']} months</td>" if e.get("term_months")
                 else "<td>not confirmed</td>",
                 f"<td>{status(e)}</td>",
                 f"<td>checked {e['checked_date']}</td>"]
        if compare:
            diff = bench_rate - e["rate_cents_per_kwh"]
            cells.append(f"<td>{'below' if diff > 0 else 'above'} the default by "
                         f"{abs(diff):.3f}c</td>")
        return "<tr>" + "".join(cells) + "</tr>"
    def table(cls, caption, rows, compare):
        head = ("<thead><tr><th>Supplier</th><th>Plan</th><th>Rate</th><th>Term</th>"
                "<th>Status</th><th>Checked</th>"
                + ("<th>Vs default</th>" if compare else "") + "</tr></thead>")
        return ([f'<table class="offers-static {cls}">', f"<caption>{caption}</caption>",
                 head, "<tbody>"] + rows + ["</tbody></table>"])
    out = table("ranked",
                f"Verified fixed-rate offers, ranked by rate. Default (Last Resort): "
                f"{bench_rate}c/kWh.", [row(e, True) for e in ranked], True)
    if variable:
        out += table("variable-offers",
                     "Variable-rate offers — shown apart. A variable rate can change "
                     "at any time, so these are never ranked as beating the default.",
                     [row(e, False) for e in variable], False)
    if unverified:
        out += table("unverified",
                     "Advertised offers not yet verified — listed for the record, "
                     "not ranked.", [row(e, False) for e in unverified], False)
    if flagged:
        out += table("flagged",
                     "Flagged on track record — listed apart on purpose. These "
                     "suppliers' RI customers paid far more than the default on "
                     "average, 2017-2024 (RI DPUC data).",
                     [row(e, False) for e in flagged], False)
    if notserved:
        out += table("not-served",
                     "Advertised but verified as NOT serving Rhode Island — listed "
                     "for the record, never ranked.",
                     [row(e, False) for e in notserved], False)
    return "\n".join(out)

def _parse_date_any(s):
    from datetime import datetime as _dt
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%b %d %Y", "%B %d %Y"):
        try:
            return _dt.strptime(str(s).replace(",", "").strip(), fmt).date()
        except ValueError:
            continue
    return None

def benchmark_period_of(bench: dict):
    """The benchmark entry's current period as (start, end) dates: from
    its period_start/period_end fields when present, else parsed from
    the 'Mon D YYYY - Mon D YYYY' span in its notes."""
    ps = _parse_date_any(bench.get("period_start") or "")
    pe = _parse_date_any(bench.get("period_end") or "")
    if ps and pe:
        return (ps, pe)
    m = re.search(r'([A-Z][a-z]+ \d{1,2},? \d{4}) - ([A-Z][a-z]+ \d{1,2},? \d{4})',
                  bench.get("notes") or "")
    if m:
        ps, pe = _parse_date_any(m.group(1)), _parse_date_any(m.group(2))
        if ps and pe:
            return (ps, pe)
    return None

def fmt_rate(v) -> str:
    s = f"{float(v):.3f}".rstrip("0").rstrip(".")
    return s if "." in s else s + ".0"

def fmt_long_date(d) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"

def apply_card(current: list, card: dict, today: date):
    """Returns (new_dataset, changes, drift_messages). Pure — no I/O."""
    changes, drift = [], []
    bench = next((e for e in current if is_benchmark(e)), None)
    if bench is None:
        raise ValueError("dataset: benchmark entry not found")
    cb = card["benchmark"]
    # v3: auto-apply the benchmark inside a sanity range, and report it.
    if (abs(bench["rate_cents_per_kwh"] - cb["rate_cents_per_kwh"]) > 0.0005
            or bench.get("period_start") not in (None, cb["period_start"])):
        from datetime import datetime as _dt
        try:
            ps = _dt.strptime(cb["period_start"], "%m/%d/%Y").date()
            pe = _dt.strptime(cb["period_end"], "%m/%d/%Y").date()
            period_ok = pe > ps
            term = max(1, round((pe - ps).days / 30.44))
        except Exception:
            period_ok, term = False, None
        old_period = benchmark_period_of(bench)
        if old_period is None:
            continuity_ok, why = False, "old period unknown — cannot verify continuity"
        elif (ps, pe) == old_period:
            continuity_ok, why = True, "period unchanged"
        else:
            from datetime import timedelta as _td
            continuity_ok = (ps == old_period[1] + _td(days=1) and ps <= today)
            why = (f"new start {ps} vs old end {old_period[1]}"
                   if not continuity_ok else "period rolls over contiguously")
        sane = (BENCH_SANITY_MIN_CENTS <= cb["rate_cents_per_kwh"] <= BENCH_SANITY_MAX_CENTS
                and period_ok and continuity_ok)
        if sane:
            changes.append(f"BENCHMARK APPLIED: {bench['rate_cents_per_kwh']}c -> "
                           f"{cb['rate_cents_per_kwh']}c, period {cb['period_start']} - "
                           f"{cb['period_end']} (was {bench.get('period_start')} - "
                           f"{bench.get('period_end')})")
            bench = {**bench, "rate_cents_per_kwh": cb["rate_cents_per_kwh"],
                     "term_months": term, "checked_date": today.isoformat(),
                     "period_start": cb["period_start"],
                     "period_end": cb["period_end"]}
        else:
            drift.append(f"BENCHMARK FAILED SANITY CHECKS: dataset "
                         f"{bench['rate_cents_per_kwh']}c vs card "
                         f"{cb['rate_cents_per_kwh']}c (band_ok="
                         f"{BENCH_SANITY_MIN_CENTS <= cb['rate_cents_per_kwh'] <= BENCH_SANITY_MAX_CENTS}, "
                         f"period_ok={period_ok}, continuity: {why}) — benchmark "
                         f"NOT applied; human review required")
    out, seen = [], set()
    card_keys = {(o["supplier"], o["term_months"]) for o in card["offers"]}
    for e in current:
        if is_benchmark(e):
            out.append(bench)
            continue
        if is_empower(e):
            k = (e["supplier"], e["term_months"])
            if k not in card_keys:
                changes.append(f"removed (left card): {e['supplier']} {e['rate_cents_per_kwh']}c/{e['term_months']}mo")
                continue
            seen.add(k)
            match = next(o for o in card["offers"] if (o["supplier"], o["term_months"]) == k)
            if (abs(e["rate_cents_per_kwh"] - match["rate_cents_per_kwh"]) > 0.0005
                    or e.get("renewable_pct") != match["renewable_pct"]):
                changes.append(f"changed: {e['supplier']} {e['rate_cents_per_kwh']}c -> "
                               f"{match['rate_cents_per_kwh']}c / {match['term_months']}mo")
                e = {**e, "rate_cents_per_kwh": match["rate_cents_per_kwh"],
                     "renewable_pct": match["renewable_pct"],
                     "checked_date": today.isoformat()}
            out.append(e)
            continue
        # advertised-only: expiry rule (proposed 45 days), dates never rolled
        age = (today - date.fromisoformat(e["checked_date"])).days
        if age > ADVERTISED_ONLY_EXPIRY_DAYS:
            changes.append(f"expired (advertised-only, {age}d > {ADVERTISED_ONLY_EXPIRY_DAYS}d): "
                           f"{e['supplier']} {e['rate_cents_per_kwh']}c checked {e['checked_date']}")
            continue
        out.append(e)
    for o in card["offers"]:
        k = (o["supplier"], o["term_months"])
        if k not in seen and not any(is_empower(e) and (e["supplier"], e["term_months"]) == k for e in current):
            changes.append(f"added: {o['supplier']} {o['rate_cents_per_kwh']}c/{o['term_months']}mo")
            out.append({
                "availability": "served", "checked_date": today.isoformat(),
                "early_termination_fee_usd": None, "intro_details": None,
                "monthly_fee_usd": None,
                "notes": "Added from the Empower RI rate card; plan name, ETF and "
                         "monthly fee not confirmed unless stated in the card's "
                         "own plan details.",
                "plan_name": None, "rate_cents_per_kwh": o["rate_cents_per_kwh"],
                "rate_type": None, "renewable_pct": o["renewable_pct"],
                "source_name": "Empower RI (RI Public Utilities Commission) rate card",
                "source_url": CARD, "supplier": o["supplier"],
                "term_months": o["term_months"], "verified": True})
    return out, changes, drift

def main() -> int:
    current = json.loads(OFFERS.read_text())
    towns = json.loads(TOWNS.read_text())
    try:
        card = parse_empower_card(requests.get(CARD, timeout=60).text)
        new, changes, drift = apply_card(current, card, TODAY_ET)
    except Exception as e:
        print(f"UNVERIFIED: rate card fetch/parse/apply failed: {e}")
        return 1
    drift += [f"TOWN DRIFT: {p}" for p in town_drift(towns, TODAY_ET)]
    if changes:
        # v3 write order: build the new index FIRST (checked date that
        # never moves backward + the static offers table). If anything
        # here raises, nothing has been written at all.
        current_html = INDEX.read_text()
        newest = max(e["checked_date"] for e in new if is_empower(e))
        bench_rate = next(e["rate_cents_per_kwh"] for e in new if is_benchmark(e))
        bench_entry = next(e for e in new if is_benchmark(e))
        period = benchmark_period_of(bench_entry)
        if period is None:
            raise ValueError("benchmark period unknown — cannot rewrite index prose")
        from datetime import timedelta as _td
        new_html = rewrite_index_multi(current_html, {
            "checked_date": homepage_date(current_html, newest),
            "benchmark_rate": fmt_rate(bench_entry["rate_cents_per_kwh"]),
            "benchmark_period": f"{fmt_long_date(period[0])} through {fmt_long_date(period[1])}",
            "benchmark_next_start": fmt_long_date(period[1] + _td(days=1)),
            "offers_table": build_offers_table(new, bench_rate)})
        # Meta description: a comment marker cannot live inside an
        # attribute value, so the rate there is a checked substitution.
        meta_pat = re.compile(r'(Last Resort rate of )[\d.]+(¢/kWh)')
        assert len(meta_pat.findall(new_html)) == 1, "meta description rate not found exactly once"
        new_html = meta_pat.sub(rf'\g<1>{fmt_rate(bench_entry["rate_cents_per_kwh"])}\g<2>', new_html)
        OFFERS.write_text(json.dumps(new, indent=1) + "\n")
        INDEX.write_text(new_html)
        for c in changes:
            print(f"  {c}")
        print(f"Applied {len(changes)} change(s), checked {TODAY_ET} ET.")
    else:
        print("No offer changes tonight.")
    if drift:
        for d in drift:
            print(f"DRIFT: {d}")
        print("DRIFT: offer changes above were applied and written; this run "
              "fails so the drift gets human review.")
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
