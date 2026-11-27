#!/usr/bin/env python3
"""Unit tests for scripts/update_rates.py — run: python3 -m unittest discover tests
Fixture is the Empower RI rate card snapshot saved Nov 26, 2026.
Known-good card (Nov 24-26, 2026, verified by hand three nights running):
benchmark 17.029c for 10/01/2026-03/31/2027 and exactly 8 competitive offers.
"""
import json, sys, unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
FIX = Path(__file__).resolve().parent / "fixtures"
import update_rates as u

KNOWN_OFFERS = {("Major Energy", 12): 15.29, ("Archer Energy", 19): 15.319,
                ("Direct Energy", 11): 15.49, ("Major Energy", 24): 15.49,
                ("Direct Energy", 12): 15.69, ("Archer Energy", 12): 15.999,
                ("Town Square Energy", 24): 16.97, ("Think Energy", 12): 17.1}

def live_dataset():
    """The live 21-entry dataset shape as of Nov 24, 2026 (trimmed fields)."""
    base = {"availability": "served", "plan_name": None, "renewable_pct": 0,
            "source_name": "Empower RI (RI Public Utilities Commission) rate card",
            "verified": True}
    ds = [{"supplier": "Rhode Island Energy", "plan_name": "Last Resort Service (default supply)",
           "rate_cents_per_kwh": 17.029, "term_months": 6, "checked_date": "2026-11-21",
           "period_start": "10/01/2026", "period_end": "03/31/2027",
           "notes": "BENCHMARK default rate, Oct 1 2026 - Mar 31 2027.",
           "source_name": "Providence announcement; confirmed on Empower RI", "renewable_pct": 0}]
    for (s, t), r in KNOWN_OFFERS.items():
        ds.append({**base, "supplier": s, "term_months": t, "rate_cents_per_kwh": r,
                   "checked_date": "2026-11-24" if s == "Major Energy" else "2026-11-21",
                   "renewable_pct": 100 if s == "Think Energy" else 0})
    for i in range(12):  # advertised-only entries, checked Oct 17
        ds.append({"supplier": f"Advertised {i}", "plan_name": None, "rate_cents_per_kwh": 20.0,
                   "term_months": 12, "checked_date": "2026-10-17", "renewable_pct": 0,
                   "source_name": "supplier's own site", "availability": "not_served"})
    return ds

class TestCardParser(unittest.TestCase):
    def setUp(self):
        self.card = u.parse_empower_card((FIX / "empower_rate_card.html").read_text())
    def test_benchmark(self):
        b = self.card["benchmark"]
        self.assertEqual(b["supplier"], "Rhode Island Energy")
        self.assertAlmostEqual(b["rate_cents_per_kwh"], 17.029, places=3)
        self.assertEqual((b["period_start"], b["period_end"]), ("10/01/2026", "03/31/2027"))
    def test_offers_exact(self):
        got = {(o["supplier"], o["term_months"]): o["rate_cents_per_kwh"]
               for o in self.card["offers"]}
        self.assertEqual(got, KNOWN_OFFERS)
    def test_renewable(self):
        think = next(o for o in self.card["offers"] if o["supplier"] == "Think Energy")
        self.assertEqual(think["renewable_pct"], 100)

class TestApply(unittest.TestCase):
    def setUp(self):
        self.card = u.parse_empower_card((FIX / "empower_rate_card.html").read_text())
    def test_no_changes_against_live(self):
        new, changes, drift = u.apply_card(live_dataset(), self.card, date(2026, 11, 26))
        self.assertEqual(changes, [])
        self.assertEqual(drift, [])
        self.assertEqual(len(new), 21)
    def test_benchmark_in_sanity_range_auto_applies(self):
        ds = live_dataset()
        ds[0] = {**ds[0], "rate_cents_per_kwh": 16.5}  # small stale diff, same period
        new, changes, drift = u.apply_card(ds, self.card, date(2026, 11, 26))
        self.assertEqual(drift, [])
        self.assertTrue(any("BENCHMARK APPLIED" in c for c in changes))
        bench = next(e for e in new if u.is_benchmark(e))
        self.assertAlmostEqual(bench["rate_cents_per_kwh"], 17.029, places=3)
        self.assertEqual(bench["period_end"], "03/31/2027")
    def test_seasonal_reset_applies_despite_big_move(self):
        # Summer 11.092 -> winter 17.029 is +54%: the dropped 25% limit
        # rejected exactly this. Contiguous period rollover must apply.
        ds = live_dataset()
        ds[0] = {**ds[0], "rate_cents_per_kwh": 11.092,
                 "period_start": "04/01/2026", "period_end": "09/30/2026"}
        new, changes, drift = u.apply_card(ds, self.card, date(2026, 11, 26))
        self.assertEqual(drift, [])
        bench = next(e for e in new if u.is_benchmark(e))
        self.assertAlmostEqual(bench["rate_cents_per_kwh"], 17.029, places=3)
    def test_benchmark_gap_in_period_drifts(self):
        ds = live_dataset()
        ds[0] = {**ds[0], "period_start": "04/01/2026", "period_end": "09/29/2026"}
        new, changes, drift = u.apply_card(ds, self.card, date(2026, 11, 26))
        self.assertTrue(any("BENCHMARK FAILED SANITY" in d for d in drift))
        bench = next(e for e in new if u.is_benchmark(e))
        self.assertEqual(bench.get("period_end"), "09/29/2026")  # NOT applied
    def test_benchmark_future_period_drifts(self):
        ds = live_dataset()  # old period ends 03/31/2027 per its notes
        card = json.loads(json.dumps(self.card))
        card["benchmark"] = {"rate_cents_per_kwh": 12.0,
                             "period_start": "04/01/2027", "period_end": "09/30/2027"}
        new, changes, drift = u.apply_card(ds, card, date(2026, 11, 26))
        self.assertTrue(any("BENCHMARK FAILED SANITY" in d for d in drift))
    def test_benchmark_out_of_band_drifts(self):
        ds = live_dataset()
        card = json.loads(json.dumps(self.card))
        card["benchmark"] = {"rate_cents_per_kwh": 45.0,
                             "period_start": "10/01/2026", "period_end": "03/31/2027"}
        new, changes, drift = u.apply_card(ds, card, date(2026, 11, 26))
        self.assertTrue(any("BENCHMARK FAILED SANITY" in d for d in drift))

class TestHomepageDateAndTable(unittest.TestCase):
    def test_homepage_date_never_moves_backward(self):
        html = "x <!--AUTO:checked_date-->2026-11-26<!--/AUTO--> y"
        self.assertEqual(u.homepage_date(html, "2026-11-24"), "2026-11-26")
        self.assertEqual(u.homepage_date(html, "2026-11-27"), "2026-11-27")
    def test_offers_table_v4_status_flagged_ranked(self):
        ds = live_dataset()
        ds.append({"supplier": "XOOM Energy", "plan_name": "SureLock 24",
                   "rate_cents_per_kwh": 17.79, "term_months": 24,
                   "checked_date": "2026-11-26", "renewable_pct": 0,
                   "source_name": "XOOM own site", "availability": "served",
                   "rate_type": "fixed", "verified": True,
                   "notes": "Caution flag: customers paid an average +$1,057 premium."})
        ds.append({"supplier": "Ambit Energy", "plan_name": "Ocean State Select Variable",
                   "rate_cents_per_kwh": 16.0, "term_months": None,
                   "checked_date": "2026-11-26", "renewable_pct": 0,
                   "source_name": "Ambit disclosure", "availability": "served",
                   "rate_type": "variable", "verified": True,
                   "notes": "Caution flag: +$995 average premium."})
        html = u.build_offers_table(ds, 17.029)
        self.assertIn("<th>Status</th>", html)
        ranked = html.split('class="offers-static ranked"')[1].split("</table>")[0]
        self.assertIn("Major Energy", ranked)          # verified Empower offer, ranked
        self.assertNotIn("XOOM", ranked)               # flagged -> apart
        self.assertNotIn("Ambit", ranked)              # flagged variable -> apart
        flagged = html.split('class="offers-static flagged"')[1].split("</table>")[0]
        self.assertIn("XOOM", flagged)                 # +$1,057 premium = caution-flagged
        self.assertIn("Ambit", flagged)                # +$995 premium = caution-flagged too
        self.assertIn("Flagged", flagged)
    def test_benchmark_period_parsed_from_notes(self):
        bench = {"notes": "BENCHMARK default rate, Oct 1 2026 - Mar 31 2027, PUC-approved."}
        self.assertEqual(u.benchmark_period_of(bench),
                         (date(2026, 10, 1), date(2027, 3, 31)))
    def test_offers_table_variable_apart(self):
        ds = live_dataset()
        ds.append({"supplier": "Var Co", "plan_name": "Flex", "rate_cents_per_kwh": 9.0,
                   "term_months": None, "checked_date": "2026-11-26", "renewable_pct": 0,
                   "source_name": "own site", "availability": "served",
                   "rate_type": "variable"})
        html = u.build_offers_table(ds, 17.029)
        self.assertIn("Variable-rate offers", html)
        var_section = html.split("Variable-rate offers")[1]
        self.assertIn("Var Co", var_section)
        self.assertNotIn("Vs default", var_section.split("</table>")[0])
        self.assertNotIn("Var Co", html.split("Variable-rate offers")[0])

class TestRewriteIndex(unittest.TestCase):
    def test_marker(self):
        out = u.rewrite_index("a <!--AUTO:checked_date-->2026-11-21<!--/AUTO--> b",
                              "checked_date", "2026-11-26")
        self.assertIn("<!--AUTO:checked_date-->2026-11-26<!--/AUTO-->", out)
    def test_missing_marker_refuses(self):
        with self.assertRaises(ValueError):
            u.rewrite_index("<html></html>", "checked_date", "2026-11-26")

if __name__ == "__main__":
    unittest.main()
