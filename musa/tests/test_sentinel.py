import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from musa_sentinel import case as case_mod  # noqa: E402
from musa_sentinel import cli, costs, firewall, graph, leads, matching, outreach, revenue, risk, traps  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")


def sample(name):
    with open(os.path.join(SAMPLES, name), encoding="utf-8") as f:
        return json.load(f)


class RiskTests(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(risk.band(0), "LOW")
        self.assertEqual(risk.band(20), "MODERATE")
        self.assertEqual(risk.band(59), "HIGH")
        self.assertEqual(risk.band(80), "CRITICAL")

    def test_hard_stop_forces_red_even_at_low_score(self):
        d = risk.decide({"country_switch"})
        self.assertEqual(d["colour"], "RED")

    def test_nothing_verified_is_amber_not_green(self):
        self.assertEqual(risk.decide(set())["colour"], "AMBER")

    def test_all_verified_no_signals_is_green_but_human_review(self):
        d = risk.decide(set(), {k: True for k in risk.GREEN_REQUIREMENTS})
        self.assertEqual(d["colour"], "GREEN")
        self.assertIn("HUMAN", d["action"])

    def test_black_only_from_human_markers(self):
        self.assertEqual(risk.decide({"document_fabrication"}, markers={"confirmed_forgery"})["colour"], "BLACK")
        self.assertEqual(risk.decide({"document_fabrication"})["colour"], "RED")


class TrapTests(unittest.TestCase):
    def test_classic_scam_message_is_red(self):
        res = traps.assess_message("Visa 100% guarantee hai. Pay today, send to my personal account. Contract after payment.")
        ids = {h["id"] for h in res["hits"]}
        self.assertTrue({"TRAP-001", "TRAP-003", "TRAP-013", "TRAP-015"} <= ids)
        self.assertEqual(res["decision"]["colour"], "RED")

    def test_roman_urdu_patterns(self):
        ids = {h["id"] for h in traps.scan("Embassy mein apna banda hai, pakka visa. Wahan ja kar permit mil jayega")}
        self.assertTrue({"TRAP-001", "TRAP-006", "TRAP-008"} <= ids)

    def test_clean_message_is_still_not_green(self):
        res = traps.assess_message("Please find attached the employment contract and our OEP licence number.")
        self.assertEqual(res["hits"], [])
        self.assertEqual(res["decision"]["colour"], "AMBER")

    def test_every_trap_signal_is_weighted(self):
        for t in traps.load_traps():
            self.assertIn(t["signal"], risk.RISK_WEIGHTS, t["id"])


class CostTests(unittest.TestCase):
    def test_unknown_never_in_verified_total(self):
        items = [costs.CostItem("Visa fee", 100, "A", "OFFICIAL", source="gov"),
                 costs.CostItem("Appointment", 200, "F", "UNKNOWN")]
        led = costs.ledger(items, quoted_total=500)
        self.assertEqual(led["verified_minimum"], 100)
        self.assertEqual(led["unverified_amount"], 400)  # 200 unknown + 200 unitemised gap
        self.assertEqual(led["unitemised_gap"], 200)

    def test_official_without_source_is_downgraded(self):
        self.assertFalse(costs.CostItem("Visa fee", 100, "A", "OFFICIAL").verified)

    def test_quote_collision(self):
        res = costs.quote_collision({"A": {"government_fee": 1500}, "B": {"government_fee": 700}, "C": {"government_fee": 2000}})
        self.assertTrue(res["collision"])


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.g = graph.ReputationGraph()
        for e in sample("entities.json")["entities"]:
            self.g.add_entity(e["id"], e["name"], e.get("type", "recruiter"), e.get("identifiers"), e.get("outcomes"))

    def test_phone_and_bank_reuse_is_high(self):
        top = self.g.find_reuse()[0]
        self.assertEqual(top["confidence"], "HIGH")
        self.assertEqual(set(top["entities"]), {"ABC Overseas Consultants", "Global European Employment"})
        self.assertEqual(top["finding"], "POTENTIAL ENTITY REUSE")

    def test_free_mail_domains_do_not_link(self):
        pairs = [set(f["entities"]) for f in self.g.find_reuse()]
        self.assertNotIn({"Global European Employment", "Cyprus Jobs Hub"}, pairs)

    def test_bank_numbers_are_hashed(self):
        ids = [v for e in self.g.entities.values() for k, v in e["identifiers"] if k == "bank"]
        self.assertTrue(all(v.startswith("sha256:") for v in ids))

    def test_template_reuse(self):
        res = graph.template_reuse(sample("entities.json")["documents"])
        self.assertEqual(res[0]["documents"], ["contract_A", "contract_B"])


class FirewallTests(unittest.TestCase):
    def test_sample_request_escalates(self):
        g = graph.ReputationGraph()
        for e in sample("entities.json")["entities"]:
            g.add_entity(e["id"], e["name"], e.get("type", "recruiter"), e.get("identifiers"), e.get("outcomes"))
        req = sample("payment_request.json")
        res = firewall.evaluate(req, graph=g, case_evidence=req["case_evidence"])
        self.assertEqual(res["decision"], "ESCALATE")
        self.assertTrue(res["requires_human_approval"])

    def test_clean_request_pays_only_to_human(self):
        req = {"amount": 300, "purpose": "Entry permit fee", "recipient_name": "CRMD", "recipient_type": "company",
               "agreement_ref": "n/a", "has_invoice": True, "has_receipt": True, "recipient_is_legal_entity": True,
               "refund_terms_defined": True, "payment_class": "P1",
               "cost_items": [{"label": "Entry permit fee", "amount": 300, "category": "A", "status": "OFFICIAL", "source": "CRMD"}]}
        ev = {k: True for k in firewall.REQUIRED_CASE_EVIDENCE}
        res = firewall.evaluate(req, case_evidence=ev)
        self.assertEqual(res["decision"], "PAY")
        self.assertTrue(res["requires_human_approval"])


class CaseTests(unittest.TestCase):
    def test_gate_blocks_and_holds(self):
        c = case_mod.Case("CASE-CY-1", "CY")
        c.advance().advance()  # LEAD → IDENTIFIED → INITIAL_SCREEN
        with self.assertRaises(case_mod.GateError):
            c.advance()  # OEP_VERIFIED needs evidence
        self.assertEqual(c.state, "HOLD")
        c.resume("analyst")
        c.verify("oep_verified", "analyst", "BEOE OEP register")
        c.advance()
        self.assertEqual(c.state, "OEP_VERIFIED")

    def test_cannot_skip(self):
        with self.assertRaises(case_mod.GateError):
            case_mod.Case("X", "CY").advance("TRAVEL")

    def test_tier5_cannot_verify(self):
        c = case_mod.Case("X", "CY")
        cl = c.add_claim(case_mod.Claim("Employer authorised OEP", "WhatsApp", source_tier=5, status="VERIFIED"))
        self.assertEqual(cl.status, "PARTIALLY_VERIFIED")

    def test_payment_needs_human_and_green(self):
        c = case_mod.Case("X", "CY")
        for flag in risk.GREEN_REQUIREMENTS:
            c.evidence[flag] = True
        c.state = "DOCUMENT_READY"
        with self.assertRaises(case_mod.GateError):
            c.advance()
        c.advance(approver="Musa")
        self.assertEqual(c.state, "PAYMENT_APPROVED")


class LeadsTests(unittest.TestCase):
    def test_queue_sorted_and_tier5_capped(self):
        q = leads.outreach_queue()
        self.assertEqual(q, sorted(q, key=lambda x: (-x["score"], x["name"])))
        self.assertTrue(all(x["score"] <= 5 for x in q if x["source_tier"] == 5))
        self.assertNotIn("authority", {x["role"] for x in q})


class MatchingTests(unittest.TestCase):
    def test_rank_and_alias(self):
        ranked = matching.rank(sample("candidate.json"), sample("jobs.json"))
        self.assertEqual(ranked[0]["job"], "Construction Mason — Limassol")
        self.assertEqual(ranked[0]["verdict"], "STRONG")

    def test_visa_gate(self):
        cand = dict(sample("candidate.json"), visa_eligible=False)
        self.assertEqual(matching.match(cand, sample("jobs.json")[0])["overall"], 0)


class RevenueTests(unittest.TestCase):
    def test_scenarios_ordered(self):
        totals = [revenue.forecast(12, s)["total_revenue"] for s in ("conservative", "base", "aggressive")]
        self.assertEqual(totals, sorted(totals))

    def test_subscriptions_accumulate_linearly(self):
        pricing = {"products": [{"id": "s", "type": "monthly", "price": 100, "start_month": 1, "start_volume": 1, "add_per_month": 1, "churn": 0}]}
        self.assertEqual([r["mrr"] for r in revenue.forecast(3, "base", pricing)["rows"]], [100, 200, 300])


class OutreachTests(unittest.TestCase):
    def test_render_requires_all_fields(self):
        with self.assertRaises(KeyError):
            outreach.render("partner_oep", contact="Ali")
        text = outreach.render("oep_due_diligence", permission="4349941", sender="Musa", company="MUSA")
        self.assertIn("4349941", text)


class BuildTests(unittest.TestCase):
    def test_build_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            js = cli.build_web(os.path.join(d, "traps.js"))
            yml = cli.build_dashy(os.path.join(d, "musa.yml"))
            with open(js, encoding="utf-8") as f:
                self.assertIn("window.MUSA_RISK", f.read())
            with open(yml, encoding="utf-8") as f:
                self.assertIn("MUSA Command Centre", f.read())


if __name__ == "__main__":
    unittest.main()
