from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict


class TransactionHistoryResponse(BaseModel):
    transaction_ref: str
    type: str
    amount: Decimal
    other_party_name: str | None = None
    other_party_phone: str | None = None
    status: str
    balance_after: Decimal | None = None
    created_at: datetime


class TransactionDetailResponse(TransactionHistoryResponse):
    description: str | None = None
    is_flagged: bool


class StatementResponse(BaseModel):
    user_name: str
    wallet_number: str
    month: str
    opening_balance: Decimal
    total_credits: Decimal
    total_debits: Decimal
    closing_balance: Decimal
