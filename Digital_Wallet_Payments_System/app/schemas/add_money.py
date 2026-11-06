from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AddMoneyRequest(BaseModel):
    amount: Decimal = Field(
        ge=Decimal("10.00"),
        le=Decimal("50000.00"),
        max_digits=12,
        decimal_places=2
    )
    source: Literal["UPI", "Card", "Net Banking"]
    simulate_status: Literal["Success", "Failed"]

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value):
        if value <= Decimal("0.00"):
            raise ValueError("Amount must be greater than zero")

        if value < Decimal("10.00"):
            raise ValueError("Minimum add money amount is ₹10")

        if value > Decimal("50000.00"):
            raise ValueError("Maximum add money amount is ₹50,000")

        return value
