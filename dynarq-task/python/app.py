"""The owner's page (part 2). Standard library only, no install needed.

Run from inside python/:

    python app.py

Environment variables:
    PORT      port to listen on, default 8000
    DATA_DIR  folder with invoices.json and sent.json, default ../data
    TODAY     date as YYYY-MM-DD, default the real date
"""

import os
import threading
from datetime import date
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

from messages import format_amount
from plan import build_plan, read_json

PORT = int(os.environ.get("PORT", "8000"))
DATA_DIR = os.environ.get("DATA_DIR", "../data")
TODAY = os.environ.get("TODAY") or date.today().isoformat()

# Owner decisions, kept while the app runs: "INV-1001|firm" -> "approve" | "reject"
DECISIONS = {}
LOCK = threading.Lock()

STEP_TEXT = {
    "friendly": "Friendly reminder",
    "firm": "Firm reminder",
    "final": "Final reminder",
}

REASON_TEXT = {
    "duplicate_id": "The same invoice number appears more than once in the file, so none of them can be trusted.",
    "invalid_amount": "The amount is missing, is not a number, or is zero or less.",
    "missing_due_date": "The invoice has no due date.",
    "invalid_due_date": "The due date is not a real date in the form YYYY-MM-DD.",
    "invalid_paid_date": "The paid date is not a real date in the form YYYY-MM-DD, or it is in the future.",
}

CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; line-height: 1.5; margin: 0 auto; padding: 1rem; max-width: 52rem; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2 { font-size: 1.2rem; margin: 2rem 0 .5rem; }
h3 { font-size: 1.05rem; margin: 0 0 .5rem; overflow-wrap: anywhere; }
.card { border: 1px solid #8886; border-radius: .5rem; padding: .75rem 1rem; margin: 0 0 1rem; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: .15rem 1rem; margin: 0 0 .75rem; }
dt { font-weight: 600; }
dd { margin: 0; overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; background: #8881; padding: .75rem; border-radius: .4rem; margin: 0 0 .75rem; }
.actions { display: flex; flex-wrap: wrap; gap: .5rem; }
button { font: inherit; min-height: 44px; padding: 0 1rem; border: 2px solid currentColor; border-radius: .4rem; background: transparent; color: inherit; cursor: pointer; }
button:hover { background: #8882; }
:focus-visible { outline: 3px solid #1a73e8; outline-offset: 2px; }
.banner { border: 2px solid currentColor; border-radius: .5rem; padding: .75rem 1rem; }
.muted { opacity: .8; }
ul.skipped { padding-left: 1.2rem; }
ul.skipped li { margin-bottom: .6rem; overflow-wrap: anywhere; }
@media (max-width: 480px) { dl { grid-template-columns: 1fr; } dt { margin-top: .3rem; } }
"""


def page(body):
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Payment reminders</title>"
        f"<style>{CSS}</style></head><body><main>"
        f"<h1>Payment reminders</h1>{body}</main></body></html>"
    )


def load_plan():
    """Read the data files and build today's plan with the rules engine."""
    invoices = read_json(os.path.join(DATA_DIR, "invoices.json"))
    sent = read_json(os.path.join(DATA_DIR, "sent.json"))
    if not isinstance(invoices, list) or not isinstance(sent, list):
        raise ValueError("invoices.json and sent.json must each contain a list")
    plan = build_plan(invoices, sent, TODAY)
    by_id = {}
    for inv in invoices:
        if isinstance(inv, dict) and isinstance(inv.get("id"), str):
            by_id.setdefault(inv["id"], inv)
    return plan, by_id


def decision_html(action, decision):
    if not action["needs_approval"]:
        return '<p class="muted">No approval needed for this reminder.</p>'
    inv_id = escape(action["invoice_id"])
    step = escape(action["step"])
    label = {"approve": "Approved", "reject": "Rejected"}.get(decision)
    if label:
        status = f'<p><strong>Your decision: {label}</strong></p>'
    else:
        status = "<p>Waiting for your decision.</p>"
    buttons = "".join(
        f'<button type="submit" name="decision" value="{value}" '
        f'aria-label="{text} reminder for {inv_id}">{text}</button>'
        for value, text in (("approve", "Approve"), ("reject", "Reject"))
    )
    return (
        f"{status}"
        '<form method="post" action="/decision" class="actions">'
        f'<input type="hidden" name="invoice_id" value="{inv_id}">'
        f'<input type="hidden" name="step" value="{step}">'
        f"{buttons}</form>"
    )


def action_html(action, inv, decisions):
    inv_id = escape(action["invoice_id"])
    decision = decisions.get(f"{action['invoice_id']}|{action['step']}")
    amount = escape(format_amount(inv["amount"], inv["currency"]))
    return (
        f'<article class="card" id="inv-{inv_id}">'
        f'<h3>{escape(str(inv["customer"]))} &middot; {inv_id}</h3>'
        "<dl>"
        f"<dt>Amount</dt><dd>{amount}</dd>"
        f'<dt>Due date</dt><dd>{escape(inv["due_date"])}</dd>'
        f'<dt>Days overdue</dt><dd>{action["days_overdue"]}</dd>'
        f'<dt>Step</dt><dd>{STEP_TEXT[action["step"]]}</dd>'
        "</dl>"
        "<p><strong>Message to the customer</strong></p>"
        f'<pre>{escape(action["message"])}</pre>'
        f"{decision_html(action, decision)}"
        "</article>"
    )


def skipped_html(item, by_id):
    inv = by_id.get(item["invoice_id"], {})
    customer = escape(str(inv.get("customer", "Unknown customer")))
    reason = REASON_TEXT.get(item["reason"], "The invoice data could not be checked.")
    return f"<li><strong>{escape(item['invoice_id'])}</strong> ({customer}): {escape(reason)}</li>"


def dashboard(plan, by_id):
    actions, skipped = plan["actions"], plan["skipped"]
    waiting = sum(1 for a in actions if a["needs_approval"])
    with LOCK:
        decisions = dict(DECISIONS)

    parts = [f'<p>Today is <strong>{escape(plan["today"])}</strong>.</p>']
    parts.append("<h2>Reminders for today</h2>")
    if actions:
        parts.append(
            f"<p>{len(actions)} reminder(s) planned, {waiting} need your approval. "
            "Nothing is sent from this page; it only records your decision.</p>"
        )
        parts.extend(action_html(a, by_id[a["invoice_id"]], decisions) for a in actions)
    else:
        parts.append(
            '<p class="banner">Nothing to send today. No invoice needs a reminder right now.</p>'
        )

    parts.append("<h2>Invoices that could not be checked</h2>")
    if skipped:
        parts.append("<p>Please fix the data for these invoices.</p>")
        parts.append('<ul class="skipped">' + "".join(skipped_html(s, by_id) for s in skipped) + "</ul>")
    else:
        parts.append("<p>All invoices could be checked.</p>")
    return page("".join(parts))


def error_page(message):
    return page(
        '<div class="banner" role="alert"><p><strong>The plan could not be shown.</strong></p>'
        f"<p>The data could not be read: {escape(message)}</p>"
        f"<p>Check the data folder ({escape(DATA_DIR)}) and the date ({escape(TODAY)}), "
        "then reload this page.</p></div>"
    )


class Handler(BaseHTTPRequestHandler):
    def send_html(self, body, status=200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlsplit(self.path).path != "/":
            self.send_error(404)
            return
        try:
            plan, by_id = load_plan()
        except (OSError, ValueError) as e:
            self.send_html(error_page(str(e)))
            return
        self.send_html(dashboard(plan, by_id))

    def do_POST(self):
        if urlsplit(self.path).path != "/decision":
            self.send_error(404)
            return
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 10_000)
        except ValueError:
            length = 0
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        inv_id = form.get("invoice_id", [""])[0]
        step = form.get("step", [""])[0]
        decision = form.get("decision", [""])[0]

        try:
            plan, _ = load_plan()
        except (OSError, ValueError):
            self.send_error(400, "Data could not be read")
            return
        known = any(
            a["invoice_id"] == inv_id and a["step"] == step and a["needs_approval"]
            for a in plan["actions"]
        )
        if not known or decision not in ("approve", "reject"):
            self.send_error(400, "Unknown reminder or decision")
            return

        with LOCK:
            DECISIONS[f"{inv_id}|{step}"] = decision
        self.send_response(303)
        self.send_header("Location", "/#inv-" + quote(inv_id))
        self.send_header("Content-Length", "0")
        self.end_headers()


def main():
    server = ThreadingHTTPServer(("", PORT), Handler)
    print(f"Serving on http://localhost:{PORT}/")
    server.serve_forever()


if __name__ == "__main__":
    main()