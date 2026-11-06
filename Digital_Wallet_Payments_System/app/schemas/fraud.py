from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict


class FraudDecisionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class FlaggedTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_ref: str
    type: str
    amount: Decimal
    status: str
    initiated_by: int | None
    is_flagged: bool
    description: str | None
    created_at: datetime
