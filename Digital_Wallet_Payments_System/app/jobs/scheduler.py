import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.jobs.cashback_jobs import process_pending_cashbacks
from app.jobs.withdrawal_jobs import process_pending_withdrawals
from app.jobs.scheduled_payment_jobs import process_scheduled_payments
from app.jobs.maintenance_jobs import (
    expire_money_requests,
    cleanup_expired_records
)
from app.jobs.reconciliation_jobs import reconcile_wallet_balances


logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")


def start_scheduler():
    if scheduler.running:
        return

    scheduler.add_job(
        process_pending_cashbacks,
        trigger=IntervalTrigger(hours=1),
        id="process_pending_cashbacks",
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    scheduler.add_job(
        process_pending_withdrawals,
        trigger=IntervalTrigger(minutes=5),
        id="process_pending_withdrawals",
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    scheduler.add_job(
        process_scheduled_payments,
        trigger=IntervalTrigger(minutes=1),
        id="process_scheduled_payments",
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    scheduler.add_job(
        expire_money_requests,
        trigger=IntervalTrigger(hours=1),
        id="expire_money_requests",
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    scheduler.add_job(
        cleanup_expired_records,
        trigger=CronTrigger(hour=0, minute=0),
        id="cleanup_expired_records",
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    scheduler.add_job(
        reconcile_wallet_balances,
        trigger=CronTrigger(hour=1, minute=0),
        id="reconcile_wallet_balances",
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    scheduler.start()

    logger.info("Digital Wallet APScheduler started successfully")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Digital Wallet APScheduler stopped")
