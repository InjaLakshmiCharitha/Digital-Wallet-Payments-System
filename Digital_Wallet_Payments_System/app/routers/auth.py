import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Merchant, Wallet, Account
from app.schemas.auth import (
    UserRegister,
    MerchantRegister,
    LoginRequest,
    UserResponse,
    TokenResponse
)
from app.auth.security import hash_password, verify_password, create_access_token
from app.auth.dependencies import get_current_user
from app.services.email_service import send_login_alert

router = APIRouter(prefix="/auth", tags=["Authentication"])


def generate_wallet_number(db: Session) -> str:
    while True:
        wallet_number = "DW" + secrets.token_hex(6).upper()
        existing = db.query(Wallet).filter(
            Wallet.wallet_number == wallet_number
        ).first()
        if not existing:
            return wallet_number


def generate_merchant_code(db: Session) -> str:
    while True:
        merchant_code = "MER" + secrets.token_hex(4).upper()
        existing = db.query(Merchant).filter(
            Merchant.merchant_code == merchant_code
        ).first()
        if not existing:
            return merchant_code


def create_user_wallet(db: Session, user: User, merchant: Merchant = None):
    wallet = Wallet(
        owner_id=user.id,
        merchant_id=merchant.id if merchant else None,
        wallet_number=generate_wallet_number(db),
        balance=0,
        kyc_level="Minimum",
        status="Active"
    )

    db.add(wallet)
    db.flush()

    account_type = "Merchant Wallet" if merchant else "User Wallet"

    account = Account(
        account_code=f"WALLET-{wallet.wallet_number}",
        account_type=account_type,
        wallet_id=wallet.id,
        balance=0,
        is_system_account=False
    )

    db.add(account)
    return wallet


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(
    data: UserRegister,
    db: Session = Depends(get_db)
):
    existing_user = db.query(User).filter(
        (User.email == data.email) | (User.phone == data.phone)
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or phone number is already registered"
        )

    user = User(
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
        password_hash=hash_password(data.password),
        role="User",
        is_active=True
    )

    try:
        db.add(user)
        db.flush()

        create_user_wallet(db, user)

        db.commit()
        db.refresh(user)

        return user

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or phone number is already registered"
        )

    except Exception:
        db.rollback()
        raise


@router.post(
    "/register/merchant",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
def register_merchant(
    data: MerchantRegister,
    db: Session = Depends(get_db)
):
    existing_user = db.query(User).filter(
        (User.email == data.email) | (User.phone == data.phone)
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or phone number is already registered"
        )

    user = User(
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
        password_hash=hash_password(data.password),
        role="Merchant",
        is_active=True
    )

    try:
        db.add(user)
        db.flush()

        merchant = Merchant(
            user_id=user.id,
            business_name=data.business_name,
            business_category=data.business_category,
            merchant_code=generate_merchant_code(db),
            is_approved=False
        )

        db.add(merchant)
        db.flush()

        create_user_wallet(db, user, merchant)

        db.commit()
        db.refresh(user)

        return user

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email, phone number or merchant code already exists"
        )

    except Exception:
        db.rollback()
        raise


@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == data.email).first()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is inactive"
        )

    access_token = create_access_token({
        "sub": str(user.id),
        "role": user.role
    })

    background_tasks.add_task(
        send_login_alert,
        user.email,
        user.full_name
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }


@router.get("/me", response_model=UserResponse)
def get_my_profile(current_user: User = Depends(get_current_user)):
    return current_user