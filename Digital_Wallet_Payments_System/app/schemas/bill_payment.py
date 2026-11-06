from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BillPaymentCreate(BaseModel):
    bill_type: Literal["Mobile Recharge", "Electricity"]
    provider_name: str = Field(min_length=2, max_length=100)
    consumer_number: str = Field(min_length=5, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    pin: str = Field(pattern=r"^[0-9]{4}$")

    @field_validator("provider_name", "consumer_number")
    @classmethod
    def clean_text(cls, value):
        value = value.strip()

        if not value:
            raise ValueError("This field cannot be empty")

        return value


class BillPaymentResponse(BaseModel):
    id: int
    transaction_id: int
    bill_type: str
    provider_name: str
    consumer_number: str
    amount: Decimal
    status: str

    model_config = ConfigDict(from_attributes=True)
