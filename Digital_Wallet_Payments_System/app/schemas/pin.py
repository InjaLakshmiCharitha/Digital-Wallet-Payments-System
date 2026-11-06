from typing import Literal
from pydantic import BaseModel, Field


class PINRequest(BaseModel):
    pin: str = Field(pattern=r"^[0-9]{4}$")


class PINChangeRequest(BaseModel):
    current_pin: str = Field(pattern=r"^[0-9]{4}$")
    new_pin: str = Field(pattern=r"^[0-9]{4}$")


class PINResetRequest(BaseModel):
    otp: str = Field(pattern=r"^[0-9]{6}$")
    new_pin: str = Field(pattern=r"^[0-9]{4}$")


class OTPRequest(BaseModel):
    purpose: Literal[
        "High Value Transfer",
        "Add Bank Account",
        "PIN Reset"
    ]


class OTPVerifyRequest(BaseModel):
    purpose: Literal[
        "High Value Transfer",
        "Add Bank Account",
        "PIN Reset"
    ]
    otp: str = Field(pattern=r"^[0-9]{6}$")

