from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models import User
from app.schemas.notification import (
    NotificationResponse,
    NotificationListResponse,
    NotificationReadResponse
)
from app.services.notification_service import (
    get_notifications,
    mark_notification_as_read,
    mark_all_notifications_as_read
)


router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"]
)


@router.get(
    "",
    response_model=NotificationListResponse
)
def list_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return get_notifications(
        db,
        current_user,
        skip,
        limit,
        unread_only
    )


@router.put(
    "/{notification_id}/read",
    response_model=NotificationResponse
)
def mark_as_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return mark_notification_as_read(
        db,
        current_user.id,
        notification_id
    )


@router.post(
    "/read-all",
    response_model=NotificationReadResponse
)
def mark_all_as_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return mark_all_notifications_as_read(
        db,
        current_user.id
    )