from __future__ import annotations

import logging
import time
import threading

from app.config import load_settings

logger = logging.getLogger(__name__)
from app.ingress.app import create_app
from app.poller import poll_once
from app.queue import Queue
from app.store.db import make_engine, make_session_factory, init_db
from app.worker import process_one


def build_app(settings):
    engine = make_engine(settings.store.url)
    init_db(engine)
    queue = Queue(make_session_factory(engine))
    return create_app(settings, queue), queue


def _worker_loop(queue, settings, stop):
    while not stop.is_set():
        try:
            if not process_one(queue, settings):
                time.sleep(1.0)
        except Exception:
            logger.exception("worker error, continuing")
            time.sleep(1.0)  # never let the loop die on a transient error


def run(config_path: str = "config.yaml") -> None:  # pragma: no cover
    import uvicorn
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.migrate import run_migrations
    from app.config import validate_ui_settings

    settings = load_settings(config_path)
    validate_ui_settings(settings)
    run_migrations(settings.store.url)
    app, queue = build_app(settings)

    stop = threading.Event()
    worker = threading.Thread(target=_worker_loop, args=(queue, settings, stop), daemon=True)
    worker.start()

    scheduler = None
    if settings.poller.enabled:
        scheduler = BackgroundScheduler()
        scheduler.add_job(lambda: poll_once(settings, queue),
                          "interval", seconds=settings.poller.interval_seconds)
        scheduler.start()

    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    finally:
        stop.set()
        if scheduler:
            scheduler.shutdown(wait=False)


if __name__ == "__main__":  # pragma: no cover
    run()
