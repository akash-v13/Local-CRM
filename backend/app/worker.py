"""Background worker: processes jobs from the `jobs` table.

Run:  uv run python -m app.worker          (docker-compose runs it as the "worker" service)

Loop: claim the next due job → run it → repeat; sleep briefly when there's
nothing to do. Several workers can run at once (jobs are claimed with
SELECT ... FOR UPDATE SKIP LOCKED). Stops cleanly on Ctrl+C / SIGTERM after
finishing the current job.

Job kinds:
  enrich_case     run the tenant's connectors on a case, then route it
  template_test   draft replies for a reply-template test run (needs ANTHROPIC_API_KEY)
"""

import logging
import signal
import time
import traceback
import uuid
from collections.abc import Callable

import httpx

from app.ai.drafter import DraftWriter
from app.ai.setup import draft_writer_from
from app.config import get_settings
from app.db import SessionLocal
from app.security.ssrf import resolve_host
from app.services.enrichment import EnrichmentService, claim_job
from app.services.template_tests import execute_test_run

log = logging.getLogger("worker")


def build_handlers(
    service: EnrichmentService, writer: DraftWriter | None = None
) -> dict[str, Callable[[uuid.UUID], None]]:
    return {
        "enrich_case": service.enrich_case,
        "template_test": lambda job_id: execute_test_run(service.session_factory, writer, job_id),
    }


def run_once(service: EnrichmentService, writer: DraftWriter | None = None) -> bool:
    """Process one due job. Returns False if there was nothing to do."""
    claimed = claim_job(service.session_factory)
    if claimed is None:
        return False
    job_id, kind = claimed
    handler = build_handlers(service, writer).get(kind)
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
        log.info("worker started (AI drafting %s)", "on" if writer else "off: no ANTHROPIC_API_KEY")
        while not stopping:
            if not run_once(service, writer):
                time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
