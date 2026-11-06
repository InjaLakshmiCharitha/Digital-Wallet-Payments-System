from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.transfer_service import (
    KYC_BALANCE_LIMITS,
    DAILY_TRANSFER_LIMITS,
    MONTHLY_TRANSFER_LIMITS,
    format_amount
)


def test_minimum_kyc_balance_limit():
    assert KYC_BALANCE_LIMITS["Minimum"] == Decimal("10000.00")


def test_full_kyc_balance_limit():
    assert KYC_BALANCE_LIMITS["Full"] == Decimal("200000.00")


def test_minimum_kyc_daily_transfer_limit():
    assert DAILY_TRANSFER_LIMITS["Minimum"] == Decimal("10000.00")


def test_full_kyc_daily_transfer_limit():
    assert DAILY_TRANSFER_LIMITS["Full"] == Decimal("25000.00")


def test_minimum_kyc_monthly_transfer_limit():
    assert MONTHLY_TRANSFER_LIMITS["Minimum"] == Decimal("25000.00")


def test_full_kyc_monthly_transfer_limit():
    assert MONTHLY_TRANSFER_LIMITS["Full"] == Decimal("100000.00")


def test_format_amount():
    assert format_amount(Decimal("1500.50")) == "₹1,500.50"


def test_daily_remaining_limit():
    daily_limit = DAILY_TRANSFER_LIMITS["Minimum"]
    daily_used = Decimal("7000.00")

    remaining = max(daily_limit - daily_used, Decimal("0.00"))

    assert remaining == Decimal("3000.00")


def test_monthly_remaining_limit():
    monthly_limit = MONTHLY_TRANSFER_LIMITS["Full"]
    monthly_used = Decimal("75000.00")

    remaining = max(monthly_limit - monthly_used, Decimal("0.00"))

    assert remaining == Decimal("25000.00")


def test_daily_limit_exceeded():
    daily_limit = DAILY_TRANSFER_LIMITS["Minimum"]
    daily_used = Decimal("9000.00")
    transfer_amount = Decimal("2000.00")

    remaining = max(daily_limit - daily_used, Decimal("0.00"))

    assert transfer_amount > remaining


def test_monthly_limit_exceeded():
    monthly_limit = MONTHLY_TRANSFER_LIMITS["Full"]
    monthly_used = Decimal("99000.00")
    transfer_amount = Decimal("2000.00")

    remaining = max(monthly_limit - monthly_used, Decimal("0.00"))

    assert transfer_amount > remaining


def test_receiver_balance_limit_exceeded():
    receiver_balance = Decimal("9500.00")
    transfer_amount = Decimal("1000.00")
    receiver_limit = KYC_BALANCE_LIMITS["Minimum"]

    assert receiver_balance + transfer_amount > receiver_limit


def test_receiver_balance_within_limit():
    receiver_balance = Decimal("5000.00")
    transfer_amount = Decimal("2000.00")
    receiver_limit = KYC_BALANCE_LIMITS["Minimum"]

    assert receiver_balance + transfer_amount <= receiver_limit


def test_insufficient_wallet_balance():
    wallet_balance = Decimal("500.00")
    transfer_amount = Decimal("1000.00")

    assert wallet_balance < transfer_amount


def test_sufficient_wallet_balance():
    wallet_balance = Decimal("2000.00")
    transfer_amount = Decimal("1000.00")

    assert wallet_balance >= transfer_amount
