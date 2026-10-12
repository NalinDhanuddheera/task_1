
"""Payment reminder rules engine (part 1).

Run from inside python/:

    python plan.py --invoices ../data/invoices.json --sent ../data/sent.json --today 2026-10-12 --out ../actions.json
"""

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import date

from messages import build_message

# (name, minimum days overdue, needs approval), lowest to highest
STEPS = [("friendly", 3, False), ("firm", 10, True), ("final", 24, True)]
RANK = {name: i for i, (name, _, _) in enumerate(STEPS)}
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse_date(value):
    """Return a date for a real YYYY-MM-DD string, otherwise None."""
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def is_valid_amount(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and value > 0


def bad_data_reason(inv, today, duplicate_ids):
    """First bad-data reason that applies, or None."""
    if inv["id"] in duplicate_ids:
        return "duplicate_id"
    if not is_valid_amount(inv.get("amount")):
        return "invalid_amount"
    due = inv.get("due_date")
    if due is None or due == "":
        return "missing_due_date"
    if parse_date(due) is None:
        return "invalid_due_date"
    paid = inv.get("paid_date")
    if paid is not None:
        paid_date = parse_date(paid)
        if paid_date is None or paid_date > today:
            return "invalid_paid_date"
    return None


def highest_sent_ranks(sent):
    """invoice id -> highest step rank already sent. Unknown steps are ignored."""
    ranks = {}
    for entry in sent:
        if not isinstance(entry, dict):
            continue
        step = entry.get("step")
        inv_id = entry.get("invoice_id")
        if step in RANK and isinstance(inv_id, str):
            ranks[inv_id] = max(ranks.get(inv_id, -1), RANK[step])
    return ranks


def build_plan(invoices, sent, today):
    """Return {"today", "actions", "skipped"} for `today` (YYYY-MM-DD)."""
    today_date = parse_date(today)
    if today_date is None:
        raise ValueError(f"today must be a real date as YYYY-MM-DD, got {today!r}")

    invoices = [i for i in invoices if isinstance(i, dict) and isinstance(i.get("id"), str)]
    counts = Counter(i["id"] for i in invoices)
    duplicate_ids = {k for k, n in counts.items() if n > 1}
    sent_ranks = highest_sent_ranks(sent)

    actions = []
    skipped = []
    reported_duplicates = set()

    for inv in invoices:
        reason = bad_data_reason(inv, today_date, duplicate_ids)
        if reason:
            if reason == "duplicate_id":
                if inv["id"] in reported_duplicates:
                    continue
                reported_duplicates.add(inv["id"])
            skipped.append({"invoice_id": inv["id"], "reason": reason})
            continue

        if inv.get("paid_date") is not None:
            continue  # paid

        due = parse_date(inv["due_date"])
        days_overdue = (today_date - due).days

        reached = None
        for name, min_days, needs_approval in STEPS:
            if days_overdue >= min_days:
                reached = (name, needs_approval)
        if reached is None:
            continue  # not yet

        step, needs_approval = reached
        if sent_ranks.get(inv["id"], -1) >= RANK[step]:
            continue  # this step or a higher one was already sent

        actions.append({
            "invoice_id": inv["id"],
            "step": step,
            "needs_approval": needs_approval,
            "days_overdue": days_overdue,
            "message": build_message(step, inv, inv["due_date"], days_overdue),
        })

    actions.sort(key=lambda a: a["invoice_id"])
    skipped.sort(key=lambda s: s["invoice_id"])
    return {"today": today, "actions": actions, "skipped": skipped}


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Plan today's payment reminders.")
    parser.add_argument("--invoices", required=True, help="path to invoices.json")
    parser.add_argument("--sent", required=True, help="path to sent.json")
    parser.add_argument("--today", required=True, help="date as YYYY-MM-DD")
    parser.add_argument("--out", required=True, help="path to write the plan JSON")
    args = parser.parse_args()

    try:
        invoices = read_json(args.invoices)
        sent = read_json(args.sent)
        if not isinstance(invoices, list) or not isinstance(sent, list):
            raise ValueError("invoices and sent files must each contain a JSON list")
        plan = build_plan(invoices, sent, args.today)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2)
            f.write("\n")
    except (OSError, ValueError) as e:  # JSONDecodeError is a ValueError
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()