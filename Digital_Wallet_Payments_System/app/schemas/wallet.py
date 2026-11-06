import re
from datetime import date, datetime
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator
)


class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    wallet_number: str
    balance: Decimal
    kyc_level: str
    status: str


class KYCRequest(BaseModel):
    pan_number: str
    aadhaar_last4: str
    full_name: str = Field(min_length=2, max_length=150)
    date_of_birth: date

    @field_validator("pan_number")
    @classmethod
    def validate_pan(cls, value):
        value = value.strip().upper()

        if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", value):
            raise ValueError("Invalid PAN format. Expected ABCDE1234F")

        return value

    @field_validator("aadhaar_last4")
    @classmethod
    def validate_aadhaar_last4(cls, value):
        if not re.fullmatch(r"[0-9]{4}", value):
            raise ValueError(
                "Aadhaar last four digits must contain exactly 4 numbers"
            )

        return value

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value):
        value = value.strip()

        if len(value) < 2:
            raise ValueError("Full name must contain at least 2 characters")

        return value

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value):
        if value >= date.today():
            raise ValueError("Date of birth must be in the past")

        return value


class KYCResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    pan_number: str
    aadhaar_last4: str
    full_name: str
    date_of_birth: date
    status: str
    rejection_reason: str | None = None
    reviewed_at: datetime | None = None


class KYCRejection(BaseModel):
    rejection_reason: str = Field(min_length=3, max_length=300)


class WalletAction(BaseModel):
    reason: str = Field(min_length=3, max_length=300)
