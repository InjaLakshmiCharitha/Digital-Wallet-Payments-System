import re
from decimal import Decimal
from datetime import datetime

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    field_validator
)


class MoneyRequestCreate(BaseModel):
    payer_phone: str
    amount: Decimal = Field(
        gt=Decimal("0.00"),
        max_digits=12,
        decimal_places=2
    )
    note: str | None = Field(default=None, max_length=250)

    @field_validator("payer_phone")
    @classmethod
    def validate_payer_phone(cls, value):
        if not re.fullmatch(r"[0-9]{10}", value):
            raise ValueError(
                "Payer phone number must contain exactly 10 digits"
            )

        return value

    @field_validator("note")
    @classmethod
    def validate_note(cls, value):
        if value is not None:
            value = value.strip()

            if not value:
                return None

        return value


class MoneyRequestPay(BaseModel):
    pin: str
    otp: str | None = None

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, value):
        if not re.fullmatch(r"[0-9]{4}", value):
            raise ValueError("PIN must contain exactly 4 digits")

        return value

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, value):
        if value is not None and not re.fullmatch(r"[0-9]{6}", value):
            raise ValueError("OTP must contain exactly 6 digits")

        return value


class MoneyRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requester_id: int
    payer_id: int
    amount: Decimal
    note: str | None = None
    status: str
    expires_at: datetime
    created_at: datetime

