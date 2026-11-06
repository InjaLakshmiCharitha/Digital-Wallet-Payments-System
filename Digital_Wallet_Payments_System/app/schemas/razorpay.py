from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RazorpayOrderCreate(BaseModel):
    amount: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=2
    )


class RazorpayOrderResponse(BaseModel):
    razorpay_order_id: str
    amount: Decimal
    currency: str
    status: str
    key_id: str


class RazorpayPaymentVerify(BaseModel):
    razorpay_order_id: str = Field(min_length=5, max_length=100)
    razorpay_payment_id: str = Field(min_length=5, max_length=100)
    razorpay_signature: str = Field(min_length=10, max_length=255)
    pin: str = Field(pattern=r"^[0-9]{4}$")


class RazorpayPaymentResponse(BaseModel):
    id: int
    razorpay_order_id: str
    razorpay_payment_id: str | None
    amount: Decimal
    status: str
    transaction_id: int | None

    model_config = ConfigDict(from_attributes=True)
