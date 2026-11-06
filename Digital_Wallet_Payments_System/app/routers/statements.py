from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from io import BytesIO, StringIO

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models import User
from statements.statement_service import (
    generate_csv_statement,
    generate_pdf_statement
)

router = APIRouter(
    prefix="/statements",
    tags=["Wallet Statements"]
)


@router.get("/csv")
def download_csv_statement(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    csv_content = generate_csv_statement(
        db,
        current_user,
        month
    )

    return StreamingResponse(
        StringIO(csv_content),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="wallet_statement_{month}.csv"'
        }
    )


@router.get("/pdf")
def download_pdf_statement(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    pdf_content = generate_pdf_statement(
        db,
        current_user,
        month
    )

    return StreamingResponse(
        BytesIO(pdf_content.getvalue()),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="wallet_statement_{month}.pdf"'
        }
    )
