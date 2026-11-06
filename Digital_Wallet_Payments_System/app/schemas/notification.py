from datetime import datetime
from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    notification_type: str
    message: str
    is_read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    notifications: list[NotificationResponse]


class NotificationReadResponse(BaseModel):
    message: str
    updated_count: int
