from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Notification, User


def create_notification(
    db: Session,
    user_id: int,
    notification_type: str,
    message: str
):
    notification = Notification(
        user_id=user_id,
        notification_type=notification_type,
        message=message,
        is_read=False
    )

    db.add(notification)
    db.flush()

    return notification


def get_notifications(
    db: Session,
    user: User,
    skip: int = 0,
    limit: int = 20,
    unread_only: bool = False
):
    query = db.query(Notification).filter(
        Notification.user_id == user.id
    )

    if unread_only:
        query = query.filter(Notification.is_read.is_(False))

    total = query.count()

    notifications = query.order_by(
        Notification.created_at.desc()
    ).offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "notifications": notifications
    }


def mark_notification_as_read(
    db: Session,
    user_id: int,
    notification_id: int
):
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user_id
    ).first()

    if not notification:
        raise HTTPException(
            status_code=404,
            detail="Notification not found"
        )

    notification.is_read = True

    db.commit()
    db.refresh(notification)

    return notification


def mark_all_notifications_as_read(
    db: Session,
    user_id: int
):
    updated_count = db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.is_read.is_(False)
    ).update(
        {"is_read": True},
        synchronize_session=False
    )

    db.commit()

    return {
        "message": "All notifications marked as read",
        "updated_count": updated_count
    }
