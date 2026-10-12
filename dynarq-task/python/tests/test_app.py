"""Run from inside python/:  python -m unittest"""

import os
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import app

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "data")


class AppTest(unittest.TestCase):
    def setUp(self):
        self.old = (app.DATA_DIR, app.TODAY)
        app.DATA_DIR, app.TODAY = DATA, "2026-10-12"
        app.DECISIONS.clear()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        app.DATA_DIR, app.TODAY = self.old

    def get(self):
        with urllib.request.urlopen(self.base + "/") as r:
            return r.read().decode("utf-8")

    def post(self, **fields):
        data = urllib.parse.urlencode(fields).encode()
        return urllib.request.urlopen(self.base + "/decision", data=data)

    def test_page_shows_plan_and_skipped(self):
        html = self.get()
        self.assertIn("Alder Fabrication Ltd", html)
        self.assertIn("USD 845.25", html)
        self.assertIn("The due date is not a real date", html)
        self.assertNotIn("invalid_due_date", html)

    def test_approve_is_remembered(self):
        self.post(invoice_id="INV-1001", step="firm", decision="approve")
        self.assertIn("Your decision: Approved", self.get())
        self.post(invoice_id="INV-1001", step="firm", decision="reject")
        self.assertIn("Your decision: Rejected", self.get())

    def test_bad_decisions_rejected(self):
        for fields in [
            dict(invoice_id="INV-9999", step="firm", decision="approve"),
            dict(invoice_id="INV-1002", step="friendly", decision="approve"),  # no approval needed
            dict(invoice_id="INV-1001", step="firm", decision="maybe"),
        ]:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.post(**fields)
            self.assertEqual(cm.exception.code, 400)

    def test_nothing_to_do(self):
        app.TODAY = "2026-08-01"
        self.assertIn("Nothing to send today", self.get())

    def test_unreadable_data_shows_message(self):
        app.DATA_DIR = "/no/such/folder"
        self.assertIn("could not be read", self.get())

    def test_invalid_today_shows_message(self):
        app.TODAY = "not-a-date"
        self.assertIn("could not be read", self.get())


if __name__ == "__main__":
    unittest.main()