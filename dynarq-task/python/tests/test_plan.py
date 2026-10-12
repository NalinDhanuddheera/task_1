"""Run from inside python/:  python -m unittest"""

import re
import unittest

from plan import build_plan

TODAY = "2026-10-12"


def inv(id="INV-1", due="2026-10-01", **kw):
    base = {"id": id, "customer": "Acme Ltd", "email": "a@acme.test",
            "amount": 100.0, "currency": "EUR", "due_date": due, "paid_date": None}
    base.update(kw)
    return base


def sent(id, step):
    return {"invoice_id": id, "step": step, "sent_on": "2026-10-01"}


def days_ago(n):
    from datetime import date, timedelta
    return (date.fromisoformat(TODAY) - timedelta(days=n)).isoformat()


class ShapeTest(unittest.TestCase):
    def test_empty_input_gives_empty_plan(self):
        plan = build_plan([], [], TODAY)
        self.assertEqual(plan, {"today": TODAY, "actions": [], "skipped": []})

    def test_invalid_today_raises(self):
        for bad in ["2026-02-30", "12/10/2026", "", "20261012"]:
            with self.assertRaises(ValueError):
                build_plan([], [], bad)


class StepBoundaryTest(unittest.TestCase):
    def step_for(self, n, sent_list=None):
        plan = build_plan([inv(due=days_ago(n))], sent_list or [], TODAY)
        return plan["actions"][0] if plan["actions"] else None

    def test_boundaries(self):
        self.assertIsNone(self.step_for(0))
        self.assertIsNone(self.step_for(2))
        self.assertEqual(self.step_for(3)["step"], "friendly")
        self.assertEqual(self.step_for(9)["step"], "friendly")
        self.assertEqual(self.step_for(10)["step"], "firm")
        self.assertEqual(self.step_for(23)["step"], "firm")
        self.assertEqual(self.step_for(24)["step"], "final")
        self.assertEqual(self.step_for(200)["step"], "final")

    def test_needs_approval(self):
        self.assertFalse(self.step_for(3)["needs_approval"])
        self.assertTrue(self.step_for(10)["needs_approval"])
        self.assertTrue(self.step_for(24)["needs_approval"])

    def test_future_due_date_is_nothing(self):
        plan = build_plan([inv(due="2026-12-01")], [], TODAY)
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["skipped"], [])

    def test_days_overdue_value(self):
        self.assertEqual(self.step_for(12)["days_overdue"], 12)


class SentTest(unittest.TestCase):
    def plan(self, n, sent_list):
        return build_plan([inv(due=days_ago(n))], sent_list, TODAY)["actions"]

    def test_only_highest_step_planned(self):
        a = self.plan(12, [])
        self.assertEqual([x["step"] for x in a], ["firm"])

    def test_same_step_already_sent(self):
        self.assertEqual(self.plan(12, [sent("INV-1", "firm")]), [])

    def test_higher_step_already_sent(self):
        self.assertEqual(self.plan(5, [sent("INV-1", "firm")]), [])

    def test_lower_step_sent_still_plans_higher(self):
        a = self.plan(12, [sent("INV-1", "friendly")])
        self.assertEqual(a[0]["step"], "firm")

    def test_unknown_step_and_unknown_invoice_ignored(self):
        a = self.plan(12, [sent("INV-1", "legal"), sent("INV-999", "final")])
        self.assertEqual(a[0]["step"], "firm")


class BadDataTest(unittest.TestCase):
    def reason(self, invoice):
        plan = build_plan([invoice], [], TODAY)
        self.assertEqual(plan["actions"], [])
        return plan["skipped"][0]["reason"] if plan["skipped"] else None

    def test_duplicate_listed_once(self):
        plan = build_plan([inv("INV-D"), inv("INV-D", amount=5.0), inv("INV-D")], [], TODAY)
        self.assertEqual(plan["skipped"], [{"invoice_id": "INV-D", "reason": "duplicate_id"}])
        self.assertEqual(plan["actions"], [])

    def test_duplicate_wins_over_other_reasons(self):
        plan = build_plan([inv("INV-D", amount=-1), inv("INV-D")], [], TODAY)
        self.assertEqual(plan["skipped"][0]["reason"], "duplicate_id")

    def test_invalid_amount(self):
        for bad in [0, -5, "100", True, None, float("nan")]:
            self.assertEqual(self.reason(inv(amount=bad)), "invalid_amount", bad)
        missing = inv()
        del missing["amount"]
        self.assertEqual(self.reason(missing), "invalid_amount")

    def test_missing_due_date(self):
        self.assertEqual(self.reason(inv(due=None)), "missing_due_date")
        self.assertEqual(self.reason(inv(due="")), "missing_due_date")
        missing = inv()
        del missing["due_date"]
        self.assertEqual(self.reason(missing), "missing_due_date")

    def test_invalid_due_date(self):
        for bad in ["2026-02-30", "30/09/2026", "2026-9-3", "20260930", 20260930, "abc"]:
            self.assertEqual(self.reason(inv(due=bad)), "invalid_due_date", bad)

    def test_invalid_paid_date(self):
        for bad in ["", "2026-13-01", "05/10/2026", "2026-10-13", 5]:
            self.assertEqual(self.reason(inv(paid_date=bad)), "invalid_paid_date", bad)

    def test_first_reason_wins(self):
        self.assertEqual(self.reason(inv(amount=0, due=None)), "invalid_amount")
        self.assertEqual(self.reason(inv(due="bad", paid_date="bad")), "invalid_due_date")


class PaidTest(unittest.TestCase):
    def test_paid_means_nothing(self):
        plan = build_plan([inv(due=days_ago(40), paid_date=days_ago(1))],
                          [sent("INV-1", "friendly")], TODAY)
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["skipped"], [])

    def test_paid_today_is_paid(self):
        plan = build_plan([inv(due=days_ago(40), paid_date=TODAY)], [], TODAY)
        self.assertEqual(plan["actions"], [])


class SortTest(unittest.TestCase):
    def test_plain_text_order(self):
        invoices = [inv("INV-99", due=days_ago(5)), inv("INV-100", due=days_ago(5)),
                    inv("INV-20", amount=0), inv("INV-3", amount=0)]
        plan = build_plan(invoices, [], TODAY)
        self.assertEqual([a["invoice_id"] for a in plan["actions"]], ["INV-100", "INV-99"])
        self.assertEqual([s["invoice_id"] for s in plan["skipped"]], ["INV-20", "INV-3"])


class MessageTest(unittest.TestCase):
    def test_message_has_required_facts_and_no_other_figures(self):
        for n, step in [(5, "friendly"), (12, "firm"), (30, "final")]:
            invoice = inv("INV-1001", due=days_ago(n), amount=1250.0, customer="Alder Ltd")
            a = build_plan([invoice], [], TODAY)["actions"][0]
            self.assertEqual(a["step"], step)
            m = a["message"]
            for needed in ["Alder Ltd", "INV-1001", days_ago(n), "EUR 1250.00", f"{n} days"]:
                self.assertIn(needed, m)
            rest = m.replace("INV-1001", "").replace(days_ago(n), "") \
                    .replace("1250.00", "").replace(str(n), "")
            self.assertIsNone(re.search(r"[0-9]", rest), rest)
            self.assertNotRegex(m.lower(), r"fee|interest|previous|earlier|reminder sent")


class SampleDataTest(unittest.TestCase):
    def test_sample_files(self):
        import json
        invoices = json.load(open("../data/invoices.json", encoding="utf-8"))
        sent_list = json.load(open("../data/sent.json", encoding="utf-8"))
        plan = build_plan(invoices, sent_list, TODAY)
        got = [(a["invoice_id"], a["step"]) for a in plan["actions"]]
        self.assertEqual(got, [("INV-1001", "firm"), ("INV-1002", "friendly"),
                               ("INV-1004", "final"), ("INV-1009", "firm"),
                               ("INV-1011", "firm")])
        self.assertEqual([(s["invoice_id"], s["reason"]) for s in plan["skipped"]],
                         [("INV-1007", "invalid_due_date"), ("INV-1008", "missing_due_date"),
                          ("INV-1010", "duplicate_id")])


if __name__ == "__main__":
    unittest.main()