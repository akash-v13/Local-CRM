"""Email channel: parsing, importing inboxes into cases, threading, and sending replies.

A fake mail server stands in for IMAP/SMTP (no network), behaving like IMAP:
UIDs only grow, UIDVALIDITY can change, and fetches return messages after a UID.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.mailboxes import get_mail_transport
from app.config import Settings
from app.email.parse import case_number_in, contact_form, parse_email, reply_subject, strip_quoted
from app.email.transport import (
    ConnectionCheck,
    FetchedMessage,
    FetchResult,
    ImapSmtpTransport,
    MailAccount,
    MailError,
    MailServer,
    TransportSettings,
)
from app.main import app
from app.models import Job, Mailbox
from app.services.email import schedule_polls
from app.services.enrichment import EnrichmentService
from app.worker import run_once
from tests.conftest import FakeApis, public_resolver

SUPPORT = "support@northwind.example.com"


def raw_email(
    *,
    sender: str = "Maya Chen <maya@example.com>",
    subject: str = "My order is late",
    body: str = "Hi, order NW-1 is a week late.",
    message_id: str | None = "<m1@example.com>",
    in_reply_to: str | None = None,
    headers: dict[str, str] | None = None,
    html: str | None = None,
    date: datetime | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = SUPPORT
    msg["Subject"] = subject
    msg["Date"] = format_datetime(date or datetime.now(UTC))
    if message_id:
        msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    for name, value in (headers or {}).items():
        msg[name] = value
    if html is not None:
        msg.set_content(html, subtype="html")
    else:
        msg.set_content(body)
    return bytes(msg)


@dataclass
class FakeMailServer:
    """Behaves like an IMAP folder plus an SMTP server."""

    uid_validity: int = 1
    folder: list[FetchedMessage] = field(default_factory=list)
    sent: list[EmailMessage] = field(default_factory=list)
    fail_fetch: str | None = None
    fail_send: str | None = None
    fetches: list[dict[str, Any]] = field(default_factory=list)

    def deliver(self, raw: bytes) -> None:
        uid = (self.folder[-1].uid if self.folder else 100) + 1
        self.folder.append(FetchedMessage(uid=uid, raw=raw))

    def fetch(
        self,
        account: MailAccount,
        *,
        uid_validity: int | None,
        after_uid: int | None,
        since: datetime,
        limit: int,
        mark_as_read: bool,
    ) -> FetchResult:
        self.fetches.append(
            {"after_uid": after_uid, "uid_validity": uid_validity, "password": account.password}
        )
        if self.fail_fetch:
            raise MailError(self.fail_fetch)
        start = after_uid if uid_validity == self.uid_validity and after_uid is not None else 0
        new = [m for m in self.folder if m.uid > start][:limit]
        return FetchResult(
            uid_validity=self.uid_validity, messages=new, folder_count=len(self.folder)
        )

    def send(self, account: MailAccount, message: EmailMessage) -> None:
        if self.fail_send:
            raise MailError(self.fail_send)
        self.sent.append(message)

    def test(self, account: MailAccount) -> ConnectionCheck:
        ok = account.password == "app-password"
        return ConnectionCheck(
            ok, ok, "Signed in" if ok else "IMAP login failed", "ok" if ok else "SMTP login failed"
        )


MAILBOX = {
    "name": "Support inbox",
    "address": SUPPORT,
    "display_name": "Northwind Support",
    "imap_host": "imap.example.com",
    "smtp_host": "smtp.example.com",
    "username": SUPPORT,
    "password": "app-password",
}


@pytest.fixture
def mail(client: TestClient) -> FakeMailServer:
    fake = FakeMailServer()
    app.dependency_overrides[get_mail_transport] = lambda: fake
    return fake


Worker = Callable[[], None]


@pytest.fixture
def work(
    session_factory: sessionmaker[Session], fake_apis: FakeApis, mail: FakeMailServer
) -> Worker:
    """Queue due inbox polls, then run every job (like the worker loop)."""

    def run() -> None:
        with fake_apis.client() as http:
            service = EnrichmentService(
                session_factory, client=http, settings=Settings(), resolve=public_resolver
            )
            schedule_polls(session_factory)
            while run_once(service, None, mail):
                pass

    return run


def link(client: TestClient, tenant_id: str, **overrides: Any) -> dict[str, Any]:
    response = client.post(f"/tenants/{tenant_id}/mailboxes", json={**MAILBOX, **overrides})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def cases(client: TestClient, tenant_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = client.get(f"/tenants/{tenant_id}/cases").json()
    return result


def detail(client: TestClient, tenant_id: str, number: int) -> dict[str, Any]:
    result: dict[str, Any] = client.get(f"/tenants/{tenant_id}/cases/{number}").json()
    return result


def make_due(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        for m in session.scalars(select(Mailbox)):
            m.last_checked_at = None
        session.commit()


# ----- parsing ---------------------------------------------------------------------------------


class TestParse:
    def test_plain_email(self) -> None:
        p = parse_email(raw_email(), fallback_id="x")
        assert (p.from_address, p.from_name, p.subject) == (
            "maya@example.com",
            "Maya Chen",
            "My order is late",
        )
        assert p.text == "Hi, order NW-1 is a week late." and p.message_id == "<m1@example.com>"
        assert p.automatic is None and p.to == [SUPPORT]

    def test_html_only_and_encoded_headers(self) -> None:
        raw = raw_email(
            sender="=?utf-8?q?Jos=C3=A9_P=C3=A9rez?= <jose@example.com>",
            subject="=?utf-8?q?D=C3=A9j=C3=A0_vu?=",
            html="<html><head><style>p{}</style></head><body><p>Hello&nbsp;there</p><p>Second</p></body></html>",
        )
        p = parse_email(raw, fallback_id="x")
        assert p.from_name == "José Pérez" and p.subject == "Déjà vu"
        assert p.text == "Hello there\n\nSecond"

    def test_attachments_are_listed(self) -> None:
        msg = EmailMessage()
        msg["From"], msg["Subject"], msg["Message-ID"] = "a@example.com", "Receipt", "<r@x>"
        msg.set_content("See attached")
        msg.add_attachment(
            b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="receipt.pdf"
        )
        p = parse_email(bytes(msg), fallback_id="x")
        assert [(a.filename, a.size) for a in p.attachments] == [("receipt.pdf", 13)]

    @pytest.mark.parametrize(
        ("headers", "sender", "reason"),
        [
            ({"Auto-Submitted": "auto-replied"}, "maya@example.com", "Auto-Submitted"),
            ({"X-Autoreply": "yes"}, "maya@example.com", "auto-reply"),
            ({"Precedence": "bulk"}, "news@example.com", "Precedence"),
            ({"List-Id": "<list.example.com>"}, "news@example.com", "mailing list"),
            ({}, "MAILER-DAEMON@example.com", "bounce"),
            ({}, "no-reply@example.com", "no-reply"),
        ],
    )
    def test_automatic_messages(self, headers: dict[str, str], sender: str, reason: str) -> None:
        p = parse_email(raw_email(sender=sender, headers=headers), fallback_id="x")
        assert p.automatic is not None and reason in p.automatic

    def test_missing_message_id_gets_a_stable_one(self) -> None:
        raw = raw_email(message_id=None)
        a, b = parse_email(raw, fallback_id="box:1:5"), parse_email(raw, fallback_id="box:1:5")
        assert a.message_id == b.message_id and a.message_id.endswith("@imported.local-crm>")

    def test_strip_quoted(self) -> None:
        gmail = (
            "Thanks, that works!\n\n"
            "On Mon, 6 Oct 2026 at 10:00, Northwind <support@x> wrote:\n> Hi Maya\n> ..."
        )
        assert strip_quoted(gmail) == "Thanks, that works!"
        outlook = "Still waiting.\n\n-----Original Message-----\nFrom: Support\nSent: Monday"
        assert strip_quoted(outlook) == "Still waiting."
        outlook2 = (
            "Any update?\n\nFrom: Northwind Support <support@x>\nSent: 6 October 2026\nTo: me"
        )
        assert strip_quoted(outlook2) == "Any update?"
        assert (
            strip_quoted("From: my phone, the order number is NW-1")
            == "From: my phone, the order number is NW-1"
        )
        assert strip_quoted("> only quoted") == "> only quoted"  # nothing new: keep it

    def test_subjects(self) -> None:
        assert reply_subject("RE: Re: Late order [Case 1791221037860354]", 1791221037860354) == (
            "Re: Late order [Case 1791221037860354]"
        )
        assert case_number_in("Re: x [Case 1791221037860354]") == 1791221037860354
        assert case_number_in("no token") is None


# ----- linking inboxes -----------------------------------------------------------------------


def test_link_inbox_password_is_write_only(
    client: TestClient, tenant_id: str, mail: FakeMailServer
) -> None:
    created = link(client, tenant_id)
    assert "password" not in created and "password_encrypted" not in created
    assert created["password_set"] is True and created["imported_total"] == 0

    url = f"/tenants/{tenant_id}/mailboxes/{created['id']}"
    kept = client.put(url, json={**MAILBOX, "password": None, "name": "Renamed"}).json()
    assert kept["name"] == "Renamed"
    assert (
        client.post(f"/tenants/{tenant_id}/mailboxes", json=MAILBOX).status_code == 409
    )  # same address
    no_password = client.post(
        f"/tenants/{tenant_id}/mailboxes",
        json={**MAILBOX, "address": "x@northwind.example.com", "password": None},
    )
    assert no_password.status_code == 409


def test_test_connection_uses_the_stored_password(
    client: TestClient, tenant_id: str, mail: FakeMailServer
) -> None:
    created = link(client, tenant_id)
    url = f"/tenants/{tenant_id}/mailboxes/test"
    bad = client.post(url, json={"draft": {**MAILBOX, "password": "wrong"}}).json()
    assert (bad["imap_ok"], bad["smtp_ok"]) == (False, False)
    stored = client.post(
        url, json={"draft": {**MAILBOX, "password": None}, "mailbox_id": created["id"]}
    ).json()
    assert stored["imap_ok"] and stored["smtp_ok"]


# ----- importing -------------------------------------------------------------------------------


def test_new_email_becomes_a_case_once(
    client: TestClient,
    tenant_id: str,
    mail: FakeMailServer,
    work: Worker,
    session_factory: sessionmaker[Session],
) -> None:
    box = link(client, tenant_id, default_category={"type": "Complaint", "category": "Delivery"})
    mail.deliver(raw_email())
    work()

    [case] = cases(client, tenant_id)
    assert (case["channel"], case["status"], case["mailbox_id"]) == ("email", "Queued", box["id"])
    assert (
        case["customer"]["email"] == "maya@example.com"
        and case["customer"]["display_name"] == "Maya Chen"
    )
    assert case["attributes"]["subject"] == "My order is late"
    assert case["category"]["effective"]["category"] == "Delivery"
    [message] = detail(client, tenant_id, case["case_number"])["messages"]
    assert (
        message["external_id"] == "<m1@example.com>"
        and message["email"]["subject"] == "My order is late"
    )
    assert mail.fetches[-1]["password"] == "app-password"  # decrypted for the connection only

    # Same email again (e.g. the server renumbered the folder): no duplicate.
    mail.uid_validity = 2
    make_due(session_factory)
    work()
    assert len(cases(client, tenant_id)) == 1
    status = client.get(f"/tenants/{tenant_id}/mailboxes/{box['id']}").json()
    assert (
        status["imported_total"] == 1 and status["last_error"] is None and status["last_success_at"]
    )
    assert mail.fetches[-1]["uid_validity"] == 1  # old position sent; the server's is 2

    recent = client.get(f"/tenants/{tenant_id}/mailboxes/{box['id']}/recent").json()
    assert recent[0]["subject"] == "My order is late"


def test_own_automatic_and_old_emails_are_skipped(
    client: TestClient, tenant_id: str, mail: FakeMailServer, work: Worker
) -> None:
    link(client, tenant_id)
    mail.deliver(raw_email(sender=f"Support <{SUPPORT}>", message_id="<own@x>"))
    mail.deliver(raw_email(headers={"Auto-Submitted": "auto-replied"}, message_id="<ooo@x>"))
    mail.deliver(raw_email(date=datetime.now(UTC) - timedelta(days=30), message_id="<old@x>"))
    work()
    assert cases(client, tenant_id) == []


def test_backfill_imports_older_emails(
    client: TestClient, tenant_id: str, mail: FakeMailServer, work: Worker
) -> None:
    link(client, tenant_id, backfill_days=60)
    mail.deliver(raw_email(date=datetime.now(UTC) - timedelta(days=30)))
    work()
    assert len(cases(client, tenant_id)) == 1


def test_replies_thread_into_the_case_and_reopen_it(
    client: TestClient,
    tenant_id: str,
    mail: FakeMailServer,
    work: Worker,
    session_factory: sessionmaker[Session],
) -> None:
    link(client, tenant_id)
    mail.deliver(raw_email())
    work()
    [case] = cases(client, tenant_id)
    number = case["case_number"]
    client.post(
        f"/tenants/{tenant_id}/cases/{number}/transitions",
        json={"to_status": "AssignedAgent", "actor_type": "human", "actor_id": "a"},
    )
    client.post(
        f"/tenants/{tenant_id}/cases/{number}/messages",
        json={
            "kind": "agent_reply",
            "body": "So sorry, it ships today.",
            "author_id": "a",
            "then_status": "Solved",
        },
    )

    reply = raw_email(
        subject="Re: My order is late",
        message_id="<m2@example.com>",
        in_reply_to="<m1@example.com>",
        body="It still hasn't arrived.\n\nOn Tue, Northwind wrote:\n> So sorry, it ships today.",
    )
    mail.deliver(reply)
    make_due(session_factory)
    work()

    assert len(cases(client, tenant_id)) == 1
    d = detail(client, tenant_id, number)
    assert d["status"] == "Queued"  # reopened by the customer's reply
    assert d["messages"][-1]["body"] == "It still hasn't arrived."  # quoted history removed
    assert d["messages"][-1]["direction"] == "inbound"


def test_subject_token_threads_only_for_the_same_customer(
    client: TestClient,
    tenant_id: str,
    mail: FakeMailServer,
    work: Worker,
    session_factory: sessionmaker[Session],
) -> None:
    link(client, tenant_id)
    mail.deliver(raw_email())
    work()
    number = cases(client, tenant_id)[0]["case_number"]
    token = f"Re: My order is late [Case {number}]"
    mail.deliver(
        raw_email(subject=token, message_id="<m3@example.com>", body="From my phone: any news?")
    )
    mail.deliver(
        raw_email(sender="Eve <eve@example.com>", subject=token, message_id="<e1@example.com>")
    )
    make_due(session_factory)
    work()
    rows = cases(client, tenant_id)
    assert len(rows) == 2  # Eve's email opened its own case
    assert len(detail(client, tenant_id, number)["messages"]) == 2


def test_reply_to_a_closed_case_opens_a_linked_case(
    client: TestClient,
    tenant_id: str,
    mail: FakeMailServer,
    work: Worker,
    session_factory: sessionmaker[Session],
) -> None:
    link(client, tenant_id)
    mail.deliver(raw_email())
    work()
    number = cases(client, tenant_id)[0]["case_number"]
    for status in ("AssignedAgent", "Solved", "Closed"):
        client.post(
            f"/tenants/{tenant_id}/cases/{number}/transitions",
            json={"to_status": status, "actor_type": "human", "actor_id": "a"},
        )
    mail.deliver(
        raw_email(
            message_id="<m4@example.com>", in_reply_to="<m1@example.com>", body="One more thing"
        )
    )
    make_due(session_factory)
    work()
    newest = cases(client, tenant_id)[0]
    assert newest["case_number"] != number and newest["attributes"]["relatedCase"] == number


def test_inbox_errors_are_shown_on_the_inbox(
    client: TestClient, tenant_id: str, mail: FakeMailServer, work: Worker
) -> None:
    box = link(client, tenant_id)
    mail.fail_fetch = "IMAP login failed for support@northwind.example.com: [AUTHENTICATIONFAILED]"
    work()
    status = client.get(f"/tenants/{tenant_id}/mailboxes/{box['id']}").json()
    assert "AUTHENTICATIONFAILED" in status["last_error"]


def test_polls_are_scheduled_once_per_interval(
    client: TestClient, tenant_id: str, session_factory: sessionmaker[Session], mail: FakeMailServer
) -> None:
    box = link(client, tenant_id)
    link(
        client,
        tenant_id,
        address="sales@northwind.example.com",
        username="sales@northwind.example.com",
        is_active=False,
    )
    assert schedule_polls(session_factory) == 1  # only the active inbox
    assert schedule_polls(session_factory) == 0  # already queued
    client.post(f"/tenants/{tenant_id}/mailboxes/{box['id']}/check")  # also no duplicate
    with session_factory() as session:
        assert len(session.scalars(select(Job).where(Job.kind == "poll_mailbox")).all()) == 1


# ----- sending ---------------------------------------------------------------------------------


def test_agent_replies_are_emailed_in_thread(
    client: TestClient,
    tenant_id: str,
    mail: FakeMailServer,
    work: Worker,
    session_factory: sessionmaker[Session],
) -> None:
    link(client, tenant_id)
    mail.deliver(raw_email())
    work()
    number = cases(client, tenant_id)[0]["case_number"]
    reply = client.post(
        f"/tenants/{tenant_id}/cases/{number}/messages",
        json={
            "kind": "agent_reply",
            "body": "So sorry Maya, it ships today.",
            "author_id": "agent.alex",
        },
    ).json()
    assert reply["email"]["delivery"]["status"] == "queued"
    work()

    [sent] = mail.sent
    assert sent["To"] == "maya@example.com"
    assert sent["From"] == f"Northwind Support <{SUPPORT}>"
    assert sent["Subject"] == f"Re: My order is late [Case {number}]"
    assert sent["In-Reply-To"] == "<m1@example.com>" and "<m1@example.com>" in sent["References"]
    assert sent["Message-ID"] == reply["external_id"]
    assert sent.get_content().strip() == "So sorry Maya, it ships today."

    message = detail(client, tenant_id, number)["messages"][-1]
    assert message["email"]["delivery"]["status"] == "sent"
    events = [
        e["event_type"] for e in client.get(f"/tenants/{tenant_id}/cases/{number}/events").json()
    ]
    assert "email.sent" in events

    # The customer's answer to our email threads by our Message-ID.
    mail.deliver(
        raw_email(
            message_id="<m5@example.com>", in_reply_to=reply["external_id"], body="Great, thanks!"
        )
    )
    make_due(session_factory)
    work()
    assert detail(client, tenant_id, number)["messages"][-1]["body"] == "Great, thanks!"


def test_failed_sends_retry_then_show_failed_and_can_be_retried(
    client: TestClient,
    tenant_id: str,
    mail: FakeMailServer,
    work: Worker,
    session_factory: sessionmaker[Session],
) -> None:
    link(client, tenant_id)
    mail.deliver(raw_email())
    work()
    number = cases(client, tenant_id)[0]["case_number"]
    reply = client.post(
        f"/tenants/{tenant_id}/cases/{number}/messages",
        json={"kind": "agent_reply", "body": "Hello", "author_id": "a"},
    ).json()
    mail.fail_send = "SMTP login failed for support@northwind.example.com"

    for _ in range(6):  # each attempt waits for its backoff; skip the waiting
        with session_factory() as session:
            for job in session.scalars(select(Job).where(Job.kind == "send_email")):
                job.run_after = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        work()
    message = detail(client, tenant_id, number)["messages"][-1]
    assert message["email"]["delivery"]["status"] == "failed"
    assert "SMTP login failed" in message["email"]["delivery"]["error"]
    events = client.get(f"/tenants/{tenant_id}/cases/{number}/events").json()
    assert any(e["event_type"] == "email.failed" for e in events)

    mail.fail_send = None
    url = f"/tenants/{tenant_id}/cases/{number}/messages/{reply['id']}/retry-send"
    assert client.post(url).json()["email"]["delivery"]["status"] == "queued"
    work()
    assert len(mail.sent) == 1
    assert client.post(url).status_code == 409  # only failed emails can be retried


def test_webform_cases_are_still_simulated(
    client: TestClient, tenant_id: str, mail: FakeMailServer, work: Worker
) -> None:
    from tests.test_cases_api import CASE_PAYLOAD

    case = client.post(f"/tenants/{tenant_id}/cases", json=CASE_PAYLOAD).json()
    reply = client.post(
        f"/tenants/{tenant_id}/cases/{case['case_number']}/messages",
        json={"kind": "agent_reply", "body": "Hi", "author_id": "a"},
    ).json()
    assert reply["email"] == {}
    work()
    assert mail.sent == []


# ----- transport safety ------------------------------------------------------------------------


def test_transport_refuses_private_hosts_and_plain_connections() -> None:
    account = MailAccount(
        "a@x.com",
        "a@x.com",
        "pw",
        MailServer("10.0.0.5", 993, "ssl"),
        MailServer("smtp.x.com", 465, "ssl"),
    )
    strict = ImapSmtpTransport(
        TransportSettings(
            allowed_hosts=(),
            allow_insecure=False,
            timeout=1,
            resolve=lambda host, port: ["10.0.0.5"],
        )
    )
    with pytest.raises(MailError, match="private or reserved"):
        strict.fetch(
            account,
            uid_validity=None,
            after_uid=None,
            since=datetime.now(UTC),
            limit=1,
            mark_as_read=False,
        )
    plain = MailAccount(
        "a@x.com",
        "a@x.com",
        "pw",
        MailServer("imap.x.com", 143, "none"),
        MailServer("smtp.x.com", 25, "none"),
    )
    with pytest.raises(MailError, match="secure connection"):
        strict.fetch(
            plain,
            uid_validity=None,
            after_uid=None,
            since=datetime.now(UTC),
            limit=1,
            mark_as_read=False,
        )


SHOPIFY_FORM = """You received a new message from your online store's contact form.

Country Code:
US

Name:
Priya Raman

Email:
priya@example.com

Phone Number:
555 0100

Order number:
NW-10211

Comment:
Hi, my order hasn't arrived.

It was a gift."""


def test_contact_form_is_read_from_label_lines() -> None:
    form = contact_form("mailer@shopify.com", None, SHOPIFY_FORM)
    assert form is not None
    assert (form.email, form.name) == ("priya@example.com", "Priya Raman")
    assert form.message == "Hi, my order hasn't arrived.\n\nIt was a gift."
    assert form.fields == {"Phone Number": "555 0100", "Order number": "NW-10211"}
    inline = "New message from your store's contact form\nName: Al\nEmail: al@example.com\nBody: Hi"
    assert contact_form("shop@store.example.com", None, inline) is not None
    # Reply-To wins; ordinary emails aren't forms.
    replied = contact_form("mailer@shopify.com", "real@example.com", SHOPIFY_FORM)
    assert replied is not None and replied.email == "real@example.com"
    assert contact_form("maya@example.com", None, "Name: x\nComment: y") is None


def test_shopify_contact_form_email_becomes_the_customers_case(
    client: TestClient, tenant_id: str, mail: FakeMailServer, work: Worker
) -> None:
    link(client, tenant_id)
    mail.deliver(
        raw_email(
            sender=f"Northwind <{SUPPORT}>",  # Shopify may send it "from" the store itself
            subject="New customer message on October 7, 2026 at 9:14 am",
            body=SHOPIFY_FORM,
            headers={"Reply-To": "Priya Raman <priya@example.com>"},
        )
    )
    work()
    [case] = cases(client, tenant_id)
    assert case["customer"]["email"] == "priya@example.com"
    assert case["customer"]["display_name"] == "Priya Raman"
    assert case["attributes"]["contactForm"] == "shopify"
    [message] = detail(client, tenant_id, case["case_number"])["messages"]
    assert message["body"].startswith("Hi, my order hasn't arrived.")
    assert "Order number: NW-10211" in message["body"]
