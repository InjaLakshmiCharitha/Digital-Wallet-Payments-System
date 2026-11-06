import re
from decimal import Decimal
from datetime import datetime

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    field_validator
)


class BankAccountCreate(BaseModel):
    account_holder_name: str = Field(min_length=2, max_length=150)
    account_number: str
    ifsc_code: str
    bank_name: str = Field(min_length=2, max_length=150)
    otp: str

    @field_validator("account_holder_name", "bank_name")
    @classmethod
    def validate_names(cls, value):
        value = value.strip()

        if len(value) < 2:
            raise ValueError("This field must contain at least 2 characters")

        return value

    @field_validator("account_number")
    @classmethod
    def validate_account_number(cls, value):
        value = value.strip()

        if not re.fullmatch(r"[0-9]{9,18}", value):
            raise ValueError(
                "Account number must contain 9 to 18 digits"
            )

        return value

    @field_validator("ifsc_code")
    @classmethod
    def validate_ifsc(cls, value):
        value = value.strip().upper()

        if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", value):
            raise ValueError("Invalid IFSC code format")

        return value

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, value):
        if not re.fullmatch(r"[0-9]{6}", value):
            raise ValueError("OTP must contain exactly 6 digits")

        return value


class BankAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_holder_name: str
    account_number: str
    ifsc_code: str
    bank_name: str
    is_primary: bool


class WithdrawalRequest(BaseModel):
    bank_account_id: int
    amount: Decimal = Field(
        ge=Decimal("100.00"),
        max_digits=12,
        decimal_places=2
    )
    pin: str

    @field_validator("bank_account_id")
    @classmethod
    def validate_bank_account_id(cls, value):
        if value <= 0:
            raise ValueError("Bank account ID must be positive")

        return value

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, value):
        if not re.fullmatch(r"[0-9]{4}", value):
            raise ValueError("PIN must contain exactly 4 digits")

        return value


class WithdrawalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    bank_account_id: int
    amount: Decimal
    status: str
    processed_at: datetime | None = None
    failure_reason: str | None = None


