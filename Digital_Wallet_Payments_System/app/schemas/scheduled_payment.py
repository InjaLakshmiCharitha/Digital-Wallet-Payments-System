from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


class ScheduledPaymentCreate(BaseModel):
    recipient_phone: str = Field(pattern=r"^[0-9]{10}$")
    amount: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=2
    )
    note: str | None = Field(default=None, max_length=250)
    frequency: Literal["Daily", "Weekly", "Monthly"] = "Monthly"
    next_run_at: datetime
    pin: str = Field(pattern=r"^[0-9]{4}$")


class ScheduledPaymentResponse(BaseModel):
    id: int
    recipient_phone: str
    amount: Decimal
    note: str | None
    frequency: str
    next_run_at: datetime
    is_active: bool
    last_transaction_id: int | None

    model_config = ConfigDict(from_attributes=True)