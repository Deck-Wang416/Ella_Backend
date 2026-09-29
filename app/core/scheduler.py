import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.services.reminder_service import ReminderRunner
from app.services.recording_merge_service import MergeAlreadyRunning, RecordingMergeService

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")


def run_due_job():
    try:
        checked, triggered = ReminderRunner().run_due()
        logger.info("run_due_job finished: checked=%s triggered=%s", checked, triggered)
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_due_job failed: %s", exc)


def retry_pending_recording_merges():
    try:
        service = RecordingMergeService()
        for session_id in service.retryable_ids(limit=2):
            try:
                service.merge_session(session_id)
            except MergeAlreadyRunning:
                continue
            except Exception:
                logger.exception("Recording merge retry failed for %s", session_id)
    except Exception:
        logger.exception("Could not scan pending recording merges")


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
    scheduler.add_job(
        retry_pending_recording_merges,
        trigger="interval",
        minutes=5,
        id="retry_pending_recording_merges",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: every %s seconds", settings.scheduler_interval_seconds)


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
