"""Background worker: processes jobs from the `jobs` table.

Run:  uv run python -m app.worker          (docker-compose runs it as the "worker" service)

Loop: claim the next due job → run it → repeat; sleep briefly when there's
nothing to do. Several workers can run at once (jobs are claimed with
SELECT ... FOR UPDATE SKIP LOCKED). Stops cleanly on Ctrl+C / SIGTERM after
finishing the current job.

Job kinds:
  enrich_case     run the tenant's connectors on a case, then route it
  template_test   draft replies for a reply-template test run (needs ANTHROPIC_API_KEY)
  poll_mailbox    import new emails from a linked inbox (queued by `schedule_polls`)
  send_email      email an agent reply on an email case (retried with backoff)
  read_case       read a new case's message (fields, category), then continue intake
  issue_payout    issue approved compensation through Stripe or Shopify (retried with backoff)

Between jobs the loop also queues inbox polls that are due (every few seconds).
"""

import logging
import signal
import time
import traceback
import uuid
from collections.abc import Callable

import httpx
from sqlalchemy.orm import Session, sessionmaker

from app.ai.drafter import DraftWriter
from app.ai.readers import Reader, reader_from
from app.ai.setup import draft_writer_from
from app.config import get_settings
from app.db import SessionLocal
from app.email.transport import MailTransport
from app.models import Job
from app.security.ssrf import resolve_host
from app.services.auto_reply import auto_reply_job
from app.services.connectors import run_settings
from app.services.email import poll_mailbox, schedule_polls, send_email_job, transport_from
from app.services.enrichment import EnrichmentService, claim_job
from app.services.payouts import issue_payout_job
from app.services.reading import read_case_job
from app.services.template_tests import execute_test_run

SCHEDULE_EVERY_SECONDS = 5.0

log = logging.getLogger("worker")


def build_handlers(
    service: EnrichmentService,
    writer: DraftWriter | None = None,
    mail: MailTransport | None = None,
    reader: Reader | None = None,
) -> dict[str, Callable[[uuid.UUID], None]]:
    factory = service.session_factory
    handlers: dict[str, Callable[[uuid.UUID], None]] = {
        "enrich_case": service.enrich_case,
        "template_test": lambda job_id: execute_test_run(factory, writer, job_id),
        "read_case": lambda job_id: read_case_job(factory, reader, job_id),
        "auto_reply": lambda job_id: auto_reply_job(factory, writer, job_id),
        "issue_payout": lambda job_id: issue_payout_job(
            factory,
            service.client,
            service.settings.stripe_api_base,
            job_id,
            run_settings(service.settings, service.resolve),
        ),
    }
    if mail is not None:
        handlers["poll_mailbox"] = lambda job_id: _poll(factory, mail, job_id)
        handlers["send_email"] = lambda job_id: send_email_job(factory, mail, job_id)
    return handlers


def _poll(factory: sessionmaker[Session], mail: MailTransport, job_id: uuid.UUID) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        mailbox_id = uuid.UUID(job.payload["mailbox_id"])
    poll_mailbox(factory, mail, mailbox_id)
    with factory() as session:
        job = session.get(Job, job_id)
        if job is not None:
            job.status = "done"
            session.commit()


def run_once(
    service: EnrichmentService,
    writer: DraftWriter | None = None,
    mail: MailTransport | None = None,
    reader: Reader | None = None,
) -> bool:
    """Process one due job. Returns False if there was nothing to do."""
    claimed = claim_job(service.session_factory)
    if claimed is None:
        return False
    job_id, kind = claimed
    handler = build_handlers(service, writer, mail, reader).get(kind)
    try:
        if handler is None:
            raise ValueError(f"Unknown job kind '{kind}'.")
        handler(job_id)
        log.info("job %s (%s) done", job_id, kind)
    except Exception:  # noqa: BLE001 - any failure must be recorded, never crash the loop
        log.exception("job %s (%s) failed", job_id, kind)
        service.job_failed(job_id, traceback.format_exc(limit=3))
    return True


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True
        log.info("stopping after the current job…")

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    with httpx.Client(follow_redirects=False) as client:
        service = EnrichmentService(
            SessionLocal, client=client, settings=settings, resolve=resolve_host
        )
        writer = draft_writer_from(settings)
        mail = transport_from(settings)
        reader = reader_from(settings, client)
        log.info(
            "worker started (AI drafting %s; reading messages with %s)",
            "on" if writer else "off: no ANTHROPIC_API_KEY",
            reader.name if reader else "patterns only",
        )
        last_schedule = 0.0
        while not stopping:
            if time.monotonic() - last_schedule >= SCHEDULE_EVERY_SECONDS:
                try:
                    if added := schedule_polls(SessionLocal):
                        log.info("queued %s inbox poll(s)", added)
                except Exception:  # noqa: BLE001 - scheduling must never stop the worker
                    log.exception("scheduling inbox polls failed")
                last_schedule = time.monotonic()
            if not run_once(service, writer, mail, reader):
                time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
