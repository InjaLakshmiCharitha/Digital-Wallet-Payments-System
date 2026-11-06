import re

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator
)


class UserRegister(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str
    password: str = Field(min_length=8, max_length=128)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value):
        value = value.strip()

        if not value or not re.fullmatch(r"[A-Za-z ]+", value):
            raise ValueError("Name must contain only letters and spaces")

        return value

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value):
        if not re.fullmatch(r"[0-9]{10}", value):
            raise ValueError("Phone number must contain exactly 10 digits")

        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        if not any(char.isalpha() for char in value):
            raise ValueError("Password must contain at least one letter")

        if not any(char.isdigit() for char in value):
            raise ValueError("Password must contain at least one digit")

        return value


class MerchantRegister(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str
    password: str = Field(min_length=8, max_length=128)
    business_name: str = Field(min_length=2, max_length=150)
    business_category: str = Field(min_length=2, max_length=100)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value):
        value = value.strip()

        if not value or not re.fullmatch(r"[A-Za-z ]+", value):
            raise ValueError("Name must contain only letters and spaces")

        return value

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value):
        if not re.fullmatch(r"[0-9]{10}", value):
            raise ValueError("Phone number must contain exactly 10 digits")

        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        if not any(char.isalpha() for char in value):
            raise ValueError("Password must contain at least one letter")

        if not any(char.isdigit() for char in value):
            raise ValueError("Password must contain at least one digit")

        return value

    @field_validator("business_name", "business_category")
    @classmethod
    def validate_business_fields(cls, value):
        value = value.strip()

        if not value:
            raise ValueError("This field cannot be empty")

        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: EmailStr
    phone: str
    role: str
    is_active: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse
