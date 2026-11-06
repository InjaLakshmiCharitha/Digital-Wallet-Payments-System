import re
from decimal import Decimal

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    field_validator
)


class TransferRequest(BaseModel):
    receiver_phone: str
    amount: Decimal = Field(
        gt=Decimal("0.00"),
        max_digits=12,
        decimal_places=2
    )
    note: str | None = Field(default=None, max_length=250)
    pin: str
    otp: str | None = None

    @field_validator("receiver_phone")
    @classmethod
    def validate_receiver_phone(cls, value):
        if not re.fullmatch(r"[0-9]{10}", value):
            raise ValueError(
                "Receiver phone number must contain exactly 10 digits"
            )

        return value

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

    @field_validator("note")
    @classmethod
    def validate_note(cls, value):
        if value is not None:
            value = value.strip()

            if not value:
                return None

        return value


class TransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message: str
    transaction_ref: str
    sender_id: int
    receiver_id: int
    amount: Decimal
    status: str
    sender_balance: Decimal

