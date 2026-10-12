"""Reminder message templates (part 3). No AI key needed.

Only the invoice's own data is used: customer, id, due date, amount, days overdue.
No fees, interest, deadlines or mention of earlier reminders.
"""


def format_amount(amount, currency):
    return f"{currency} {amount:.2f}"


def build_message(step, invoice, due_date, days_overdue):
    customer = invoice["customer"]
    inv_id = invoice["id"]
    amount = format_amount(invoice["amount"], invoice["currency"])
    facts = (
        f"invoice {inv_id} for {amount}, due on {due_date}, "
        f"is now {days_overdue} days overdue"
    )

    if step == "friendly":
        return (
            f"Subject: Payment reminder for invoice {inv_id}\n\n"
            f"Hello {customer},\n\n"
            f"A friendly reminder that {facts}. "
            "If you have already paid, thank you, and please ignore this message. "
            "Otherwise, we would appreciate it if you could arrange payment soon.\n\n"
            "Kind regards"
        )
    if step == "firm":
        return (
            f"Subject: Overdue payment for invoice {inv_id}\n\n"
            f"Dear {customer},\n\n"
            f"We have not received payment and {facts}. "
            "Please arrange payment as soon as possible. "
            "If there is a problem with the invoice, reply to this email "
            "so that we can resolve it together.\n\n"
            "Regards"
        )
    if step == "final":
        return (
            f"Subject: Urgent: invoice {inv_id} remains unpaid\n\n"
            f"Dear {customer},\n\n"
            f"Urgent: {facts} and remains unpaid. "
            "Please pay immediately. "
            "If there is a reason for the delay, contact us without delay.\n\n"
            "Regards"
        )
    raise ValueError(f"unknown step: {step}")