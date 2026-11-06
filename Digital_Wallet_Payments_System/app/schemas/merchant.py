import re
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class MerchantPaymentRequest(BaseModel):
    merchant_code: str = Field(min_length=5, max_length=30)
    amount: Decimal = Field(
        gt=Decimal("0.00"),
        max_digits=12,
        decimal_places=2
    )
    pin: str

    @field_validator("merchant_code")
    @classmethod
    def validate_merchant_code(cls, value):
        value = value.strip().upper()

        if not re.fullmatch(r"[A-Z0-9_-]{5,30}", value):
            raise ValueError("Invalid merchant code format")

        return value

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, value):
        if not re.fullmatch(r"[0-9]{4}", value):
            raise ValueError("PIN must contain exactly 4 digits")

        return value


class RefundRequest(BaseModel):
    amount: Decimal = Field(
        gt=Decimal("0.00"),
        max_digits=12,
        decimal_places=2
    )
    reason: str | None = Field(
        default=None,
        max_length=300
    )
    pin: str

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, value):
        if not re.fullmatch(r"[0-9]{4}", value):
            raise ValueError("PIN must contain exactly 4 digits")

        return value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value):
        if value is not None:
            value = value.strip()

            if not value:
                return None

        return value

