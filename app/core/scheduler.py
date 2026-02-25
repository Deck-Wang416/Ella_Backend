import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.services.reminder_service import ReminderRunner

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")


def run_due_job():
    try:
        checked, triggered = ReminderRunner().run_due()
        logger.info("run_due_job finished: checked=%s triggered=%s", checked, triggered)
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_due_job failed: %s", exc)


def start_scheduler():
    settings = get_settings()
    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled")
        return

    if scheduler.running:
        return

    scheduler.add_job(
        run_due_job,
        trigger="interval",
        seconds=settings.scheduler_interval_seconds,
        id="run_due_reminders",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: every %s seconds", settings.scheduler_interval_seconds)


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
