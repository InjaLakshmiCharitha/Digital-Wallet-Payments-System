from fastapi import FastAPI

from app.database import SessionLocal
from app.services.ledger_service import create_system_accounts
from app.jobs.scheduler import start_scheduler, stop_scheduler

from app.routers.auth import router as auth_router
from app.routers.wallet import router as wallet_router
from app.routers.pin import router as pin_router
from app.routers.add_money import router as add_money_router
from app.routers.transfer import router as transfer_router
from app.routers.merchant_payments import router as merchant_payments_router
from app.routers.money_requests import router as money_requests_router
from app.routers.bank import router as bank_router
from app.routers.fraud import router as fraud_router
from app.routers.transactions import router as transactions_router
from app.routers.statements import router as statements_router
from app.routers.notifications import router as notifications_router
from app.routers.reports import router as reports_router
from app.routers.websocket import router as websocket_router
from app.routers.scheduled_payments import router as scheduled_payments_router
from app.routers.bill_payments import router as bill_payments_router

app = FastAPI(
    title="Digital Wallet and Payments System",
    description="Secure Digital Wallet and Payments Management API",
    version="1.0.0"
)


app.include_router(auth_router)
app.include_router(wallet_router)
app.include_router(pin_router)
app.include_router(add_money_router)
app.include_router(transfer_router)
app.include_router(merchant_payments_router)
app.include_router(money_requests_router)
app.include_router(bank_router)
app.include_router(fraud_router)
app.include_router(transactions_router)
app.include_router(statements_router)
app.include_router(notifications_router)
app.include_router(reports_router)
app.include_router(websocket_router)
app.include_router(scheduled_payments_router)
app.include_router(bill_payments_router)

@app.on_event("startup")
def startup_event():
    db = SessionLocal()

    try:
        create_system_accounts(db)
    finally:
        db.close()

    start_scheduler()


@app.on_event("shutdown")
def shutdown_event():
    stop_scheduler()


@app.get("/")
def home():
    return {"message": "Digital Wallet and Payments System API"}


@app.get("/health")
def health():
    return {"status": "healthy"}


