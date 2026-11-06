from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    JSON,
    UniqueConstraint,
    CheckConstraint,
    Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from decimal import Decimal

from app.models.base import BaseModel


class User(BaseModel):
    __tablename__ = "users"

    full_name = Column(String(150), nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=False)
    phone = Column(String(10), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)

    role = Column(String(20), nullable=False, default="User")
    is_active = Column(Boolean, default=True, nullable=False)

    transaction_pin_hash = Column(String(255), nullable=True)
    pin_failed_attempts = Column(Integer, default=0, nullable=False)
    pin_locked_until = Column(DateTime, nullable=True)

    wallet = relationship(
        "Wallet",
        back_populates="owner",
        uselist=False,
        foreign_keys="Wallet.owner_id"
    )

    merchant = relationship(
        "Merchant",
        back_populates="user",
        uselist=False
    )

    bank_accounts = relationship(
        "BankAccount",
        back_populates="user"
    )

    kyc_records = relationship(
        "KYC",
        back_populates="user",
        foreign_keys="KYC.user_id"
    )

    sent_money_requests = relationship(
        "MoneyRequest",
        foreign_keys="MoneyRequest.requester_id",
        back_populates="requester"
    )

    received_money_requests = relationship(
        "MoneyRequest",
        foreign_keys="MoneyRequest.payer_id",
        back_populates="payer"
    )

    transactions = relationship(
        "Transaction",
        back_populates="initiator",
        foreign_keys="Transaction.initiated_by"
    )

    otp_records = relationship(
        "OTP",
        back_populates="user"
    )

    notifications = relationship(
        "Notification",
        back_populates="user"
    )


class Merchant(BaseModel):
    __tablename__ = "merchants"

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        unique=True,
        nullable=False
    )

    business_name = Column(String(150), nullable=False)
    business_category = Column(String(100), nullable=False)

    merchant_code = Column(
        String(30),
        unique=True,
        index=True,
        nullable=False
    )

    is_approved = Column(Boolean, default=False, nullable=False)

    user = relationship(
        "User",
        back_populates="merchant"
    )

    wallet = relationship(
        "Wallet",
        back_populates="merchant",
        uselist=False,
        foreign_keys="Wallet.merchant_id"
    )

    payments = relationship(
        "MerchantPayment",
        back_populates="merchant"
    )


class Wallet(BaseModel):
    __tablename__ = "wallets"

    owner_id = Column(
        Integer,
        ForeignKey("users.id"),
        unique=True,
        nullable=False
    )

    merchant_id = Column(
        Integer,
        ForeignKey("merchants.id"),
        unique=True,
        nullable=True
    )

    wallet_number = Column(
        String(30),
        unique=True,
        index=True,
        nullable=False
    )

    balance = Column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00"
    )

    kyc_level = Column(
        String(20),
        nullable=False,
        default="Minimum"
    )

    status = Column(
        String(20),
        nullable=False,
        default="Active"
    )

    owner = relationship(
        "User",
        back_populates="wallet",
        foreign_keys=[owner_id]
    )

    merchant = relationship(
        "Merchant",
        back_populates="wallet",
        foreign_keys=[merchant_id]
    )

    account = relationship(
        "Account",
        back_populates="wallet",
        uselist=False
    )

    __table_args__ = (
        CheckConstraint("balance >= 0", name="check_wallet_balance"),
    )


class KYC(BaseModel):
    __tablename__ = "kyc_records"

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    pan_number = Column(
        String(10),
        unique=True,
        nullable=False
    )

    aadhaar_last4 = Column(String(4), nullable=False)

    full_name = Column(String(150), nullable=False)
    date_of_birth = Column(Date, nullable=False)

    status = Column(
        String(20),
        default="Pending",
        nullable=False
    )

    rejection_reason = Column(Text, nullable=True)

    reviewed_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True
    )

    reviewed_at = Column(DateTime, nullable=True)

    user = relationship(
        "User",
        back_populates="kyc_records",
        foreign_keys=[user_id]
    )

    reviewer = relationship(
        "User",
        foreign_keys=[reviewed_by]
    )


class Account(BaseModel):
    __tablename__ = "accounts"

    account_code = Column(
        String(50),
        unique=True,
        nullable=False
    )

    account_type = Column(
        String(40),
        nullable=False
    )

    wallet_id = Column(
        Integer,
        ForeignKey("wallets.id"),
        unique=True,
        nullable=True
    )

    balance = Column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00"
    )

    is_system_account = Column(
        Boolean,
        default=False,
        nullable=False
    )

    wallet = relationship(
        "Wallet",
        back_populates="account"
    )

    ledger_entries = relationship(
        "LedgerEntry",
        back_populates="account"
    )


class Transaction(BaseModel):
    __tablename__ = "transactions"

    transaction_ref = Column(
        String(40),
        unique=True,
        index=True,
        nullable=False
    )

    type = Column(String(40), nullable=False)

    amount = Column(
        Numeric(12, 2),
        nullable=False
    )

    status = Column(
        String(20),
        default="Pending",
        nullable=False
    )

    initiated_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True
    )

    description = Column(Text, nullable=True)

    is_flagged = Column(
        Boolean,
        default=False,
        nullable=False
    )

    initiator = relationship(
        "User",
        back_populates="transactions",
        foreign_keys=[initiated_by]
    )

    ledger_entries = relationship(
        "LedgerEntry",
        back_populates="transaction"
    )

    merchant_payment = relationship(
        "MerchantPayment",
        back_populates="transaction",
        uselist=False
    )

    withdrawal = relationship(
        "Withdrawal",
        back_populates="transaction",
        uselist=False
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="check_transaction_amount"),
        Index("ix_transactions_created_type", "created_at", "type"),
    )


class LedgerEntry(BaseModel):
    __tablename__ = "ledger_entries"

    transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        nullable=False
    )

    account_id = Column(
        Integer,
        ForeignKey("accounts.id"),
        nullable=False
    )

    entry_type = Column(
        String(10),
        nullable=False
    )

    amount = Column(
        Numeric(12, 2),
        nullable=False
    )

    balance_after = Column(
        Numeric(12, 2),
        nullable=False
    )

    transaction = relationship(
        "Transaction",
        back_populates="ledger_entries"
    )

    account = relationship(
        "Account",
        back_populates="ledger_entries"
    )

    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('Debit', 'Credit')",
            name="check_ledger_entry_type"
        ),
        CheckConstraint(
            "amount > 0",
            name="check_ledger_amount"
        ),
        Index("ix_ledger_account_created", "account_id", "created_at"),
    )


class OTP(BaseModel):
    __tablename__ = "otps"

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    purpose = Column(
        String(40),
        nullable=False
    )

    otp_hash = Column(String(255), nullable=False)

    expires_at = Column(DateTime, nullable=False)

    attempts = Column(Integer, default=0, nullable=False)

    is_used = Column(Boolean, default=False, nullable=False)

    user = relationship(
        "User",
        back_populates="otp_records"
    )


class IdempotencyKey(BaseModel):
    __tablename__ = "idempotency_keys"

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    key = Column(String(128), nullable=False)

    endpoint = Column(String(150), nullable=False)

    request_hash = Column(String(64), nullable=False)

    response_data = Column(JSON, nullable=True)

    status = Column(
        String(20),
        default="Processing",
        nullable=False
    )

    expires_at = Column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "endpoint",
            "key",
            name="uq_idempotency_user_endpoint_key"
        ),
    )


class BankAccount(BaseModel):
    __tablename__ = "bank_accounts"

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    account_holder_name = Column(String(150), nullable=False)

    account_number = Column(String(18), nullable=False)

    ifsc_code = Column(String(11), nullable=False)

    bank_name = Column(String(100), nullable=False)

    is_primary = Column(Boolean, default=False, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)

    user = relationship(
        "User",
        back_populates="bank_accounts"
    )

    withdrawals = relationship(
        "Withdrawal",
        back_populates="bank_account"
    )


class MoneyRequest(BaseModel):
    __tablename__ = "money_requests"

    requester_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    payer_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    amount = Column(
        Numeric(12, 2),
        nullable=False
    )

    note = Column(Text, nullable=True)

    status = Column(
        String(20),
        default="Pending",
        nullable=False
    )

    expires_at = Column(DateTime, nullable=False)

    paid_transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        nullable=True
    )

    requester = relationship(
        "User",
        foreign_keys=[requester_id],
        back_populates="sent_money_requests"
    )

    payer = relationship(
        "User",
        foreign_keys=[payer_id],
        back_populates="received_money_requests"
    )

    paid_transaction = relationship("Transaction")

    __table_args__ = (
        CheckConstraint("amount > 0", name="check_request_amount"),
        Index("ix_money_request_expiry", "status", "expires_at"),
    )


class MerchantPayment(BaseModel):
    __tablename__ = "merchant_payments"

    transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        unique=True,
        nullable=False
    )

    merchant_id = Column(
        Integer,
        ForeignKey("merchants.id"),
        nullable=False
    )

    customer_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    amount = Column(
        Numeric(12, 2),
        nullable=False
    )

    platform_fee = Column(
        Numeric(12, 2),
        nullable=False
    )

    net_amount = Column(
        Numeric(12, 2),
        nullable=False
    )

    transaction = relationship(
        "Transaction",
        back_populates="merchant_payment"
    )

    merchant = relationship(
        "Merchant",
        back_populates="payments"
    )

    customer = relationship("User")

    refunds = relationship(
        "Refund",
        back_populates="merchant_payment"
    )

    cashbacks = relationship(
        "Cashback",
        back_populates="merchant_payment"
    )


class Refund(BaseModel):
    __tablename__ = "refunds"

    merchant_payment_id = Column(
        Integer,
        ForeignKey("merchant_payments.id"),
        nullable=False
    )

    transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        unique=True,
        nullable=False
    )

    initiated_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    amount = Column(
        Numeric(12, 2),
        nullable=False
    )

    reason = Column(Text, nullable=True)

    status = Column(
        String(20),
        default="Success",
        nullable=False
    )

    merchant_payment = relationship(
        "MerchantPayment",
        back_populates="refunds"
    )

    transaction = relationship("Transaction")

    initiator = relationship(
        "User",
        foreign_keys=[initiated_by]
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="check_refund_amount"),
    )


class Cashback(BaseModel):
    __tablename__ = "cashbacks"

    merchant_payment_id = Column(
        Integer,
        ForeignKey("merchant_payments.id"),
        nullable=False
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    amount = Column(
        Numeric(12, 2),
        nullable=False
    )

    status = Column(
        String(20),
        default="Pending",
        nullable=False
    )

    eligible_at = Column(DateTime, nullable=False)

    credited_at = Column(DateTime, nullable=True)

    transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        nullable=True,
        unique=True
    )

    merchant_payment = relationship(
        "MerchantPayment",
        back_populates="cashbacks"
    )

    user = relationship("User")

    transaction = relationship("Transaction")

    __table_args__ = (
        CheckConstraint("amount > 0", name="check_cashback_amount"),
        Index("ix_cashback_status_eligible", "status", "eligible_at"),
    )


class Withdrawal(BaseModel):
    __tablename__ = "withdrawals"

    transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        unique=True,
        nullable=False
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    bank_account_id = Column(
        Integer,
        ForeignKey("bank_accounts.id"),
        nullable=False
    )

    amount = Column(
        Numeric(12, 2),
        nullable=False
    )

    status = Column(
        String(20),
        default="Pending",
        nullable=False
    )

    processed_at = Column(DateTime, nullable=True)

    failure_reason = Column(Text, nullable=True)

    transaction = relationship(
        "Transaction",
        back_populates="withdrawal"
    )

    user = relationship("User")

    bank_account = relationship(
        "BankAccount",
        back_populates="withdrawals"
    )

    __table_args__ = (
        CheckConstraint("amount >= 100", name="check_withdrawal_amount"),
        Index("ix_withdrawal_status_created", "status", "created_at"),
    )


class AdminDecision(BaseModel):
    __tablename__ = "admin_decisions"

    transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        nullable=False
    )

    admin_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    decision = Column(
        String(20),
        nullable=False
    )

    reason = Column(Text, nullable=False)

    decided_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )

    transaction = relationship("Transaction")

    admin = relationship(
        "User",
        foreign_keys=[admin_id]
    )


class ScheduledPayment(BaseModel):
    __tablename__ = "scheduled_payments"

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    recipient_phone = Column(String(10), nullable=False)

    amount = Column(
        Numeric(12, 2),
        nullable=False
    )

    note = Column(Text, nullable=True)

    frequency = Column(
        String(20),
        default="Monthly",
        nullable=False
    )

    next_run_at = Column(DateTime, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)

    last_transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        nullable=True
    )

    user = relationship("User")

    last_transaction = relationship("Transaction")


class BillPayment(BaseModel):
    __tablename__ = "bill_payments"

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        unique=True,
        nullable=False
    )

    bill_type = Column(
        String(50),
        nullable=False
    )

    provider_name = Column(String(100), nullable=False)

    consumer_number = Column(String(100), nullable=False)

    amount = Column(
        Numeric(12, 2),
        nullable=False
    )

    status = Column(
        String(20),
        default="Pending",
        nullable=False
    )

    user = relationship("User")

    transaction = relationship("Transaction")


class Notification(BaseModel):
    __tablename__ = "notifications"

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    notification_type = Column(
        String(50),
        nullable=False
    )

    message = Column(Text, nullable=False)

    is_read = Column(Boolean, default=False, nullable=False)

    user = relationship(
        "User",
        back_populates="notifications"
    )

    __table_args__ = (
        Index("ix_notification_user_read", "user_id", "is_read"),
    )


class WalletAdminAction(BaseModel):
    __tablename__ = "wallet_admin_actions"

    wallet_id = Column(
        Integer,
        ForeignKey("wallets.id"),
        nullable=False
    )

    admin_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    action = Column(
        String(20),
        nullable=False
    )

    reason = Column(Text, nullable=False)

    wallet = relationship("Wallet")

    admin = relationship(
        "User",
        foreign_keys=[admin_id]
    )


class RazorpayPayment(BaseModel):
    __tablename__ = "razorpay_payments"

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        unique=True,
        nullable=True
    )

    razorpay_order_id = Column(
        String(100),
        unique=True,
        nullable=False
    )

    razorpay_payment_id = Column(
        String(100),
        unique=True,
        nullable=True
    )

    amount = Column(
        Numeric(12, 2),
        nullable=False
    )

    status = Column(
        String(20),
        default="Created",
        nullable=False
    )

    user = relationship("User")

    transaction = relationship("Transaction")

