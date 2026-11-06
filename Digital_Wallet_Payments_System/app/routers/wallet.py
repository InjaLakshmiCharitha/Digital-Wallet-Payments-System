from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models import User, Wallet, KYC, WalletAdminAction
from app.schemas.wallet import (
    WalletResponse,
    KYCRequest,
    KYCResponse,
    KYCRejection,
    WalletAction
)
from app.auth.dependencies import get_current_user, require_roles

router = APIRouter(tags=["Wallet and KYC"])


@router.get("/wallet", response_model=WalletResponse)
def get_wallet(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    wallet = db.query(Wallet).filter(
        Wallet.owner_id == current_user.id
    ).first()

    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    return wallet


@router.post("/kyc", response_model=KYCResponse, status_code=201)
def submit_kyc(
    data: KYCRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    existing_pending = db.query(KYC).filter(
        KYC.user_id == current_user.id,
        KYC.status == "Pending"
    ).first()

    if existing_pending:
        raise HTTPException(
            status_code=409,
            detail="You already have a pending KYC application"
        )

    existing_pan = db.query(KYC).filter(
        KYC.pan_number == data.pan_number
    ).first()

    if existing_pan:
        raise HTTPException(
            status_code=409,
            detail="This PAN number is already registered"
        )

    kyc = KYC(
        user_id=current_user.id,
        pan_number=data.pan_number,
        aadhaar_last4=data.aadhaar_last4,
        full_name=data.full_name,
        date_of_birth=data.date_of_birth,
        status="Pending"
    )

    try:
        db.add(kyc)
        db.commit()
        db.refresh(kyc)

        return kyc

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail="This PAN number is already registered"
        )

    except Exception:
        db.rollback()
        raise


@router.get("/kyc", response_model=list[KYCResponse])
def get_kyc(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(KYC).filter(
        KYC.user_id == current_user.id
    ).order_by(KYC.created_at.desc()).all()


@router.get(
    "/admin/kyc/pending",
    response_model=list[KYCResponse]
)
def get_pending_kyc(
    current_user: User = Depends(require_roles("Admin")),
    db: Session = Depends(get_db)
):
    return db.query(KYC).filter(
        KYC.status == "Pending"
    ).order_by(KYC.created_at.asc()).all()


@router.put(
    "/admin/kyc/{kyc_id}/approve",
    response_model=KYCResponse
)
def approve_kyc(
    kyc_id: int,
    current_user: User = Depends(require_roles("Admin")),
    db: Session = Depends(get_db)
):
    kyc = db.query(KYC).filter(KYC.id == kyc_id).first()

    if not kyc:
        raise HTTPException(status_code=404, detail="KYC record not found")

    if kyc.status != "Pending":
        raise HTTPException(
            status_code=409,
            detail="This KYC application has already been reviewed"
        )

    wallet = db.query(Wallet).filter(
        Wallet.owner_id == kyc.user_id
    ).first()

    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    kyc.status = "Approved"
    kyc.rejection_reason = None
    kyc.reviewed_by = current_user.id
    kyc.reviewed_at = datetime.utcnow()

    wallet.kyc_level = "Full"

    db.commit()
    db.refresh(kyc)

    return kyc


@router.put(
    "/admin/kyc/{kyc_id}/reject",
    response_model=KYCResponse
)
def reject_kyc(
    kyc_id: int,
    data: KYCRejection,
    current_user: User = Depends(require_roles("Admin")),
    db: Session = Depends(get_db)
):
    kyc = db.query(KYC).filter(KYC.id == kyc_id).first()

    if not kyc:
        raise HTTPException(status_code=404, detail="KYC record not found")

    if kyc.status != "Pending":
        raise HTTPException(
            status_code=409,
            detail="This KYC application has already been reviewed"
        )

    kyc.status = "Rejected"
    kyc.rejection_reason = data.rejection_reason
    kyc.reviewed_by = current_user.id
    kyc.reviewed_at = datetime.utcnow()

    db.commit()
    db.refresh(kyc)

    return kyc


@router.put(
    "/admin/wallets/{wallet_id}/freeze",
    response_model=WalletResponse
)
def freeze_wallet(
    wallet_id: int,
    data: WalletAction,
    current_user: User = Depends(require_roles("Admin")),
    db: Session = Depends(get_db)
):
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()

    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    if wallet.status == "Frozen":
        raise HTTPException(status_code=409, detail="Wallet is already frozen")

    wallet.status = "Frozen"

    action = WalletAdminAction(
        wallet_id=wallet.id,
        admin_id=current_user.id,
        action="Freeze",
        reason=data.reason
    )

    db.add(action)
    db.commit()
    db.refresh(wallet)

    return wallet


@router.put(
    "/admin/wallets/{wallet_id}/unfreeze",
    response_model=WalletResponse
)
def unfreeze_wallet(
    wallet_id: int,
    data: WalletAction,
    current_user: User = Depends(require_roles("Admin")),
    db: Session = Depends(get_db)
):
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()

    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    if wallet.status != "Frozen":
        raise HTTPException(status_code=409, detail="Wallet is not frozen")

    wallet.status = "Active"

    action = WalletAdminAction(
        wallet_id=wallet.id,
        admin_id=current_user.id,
        action="Unfreeze",
        reason=data.reason
    )

    db.add(action)
    db.commit()
    db.refresh(wallet)

    return wallet
