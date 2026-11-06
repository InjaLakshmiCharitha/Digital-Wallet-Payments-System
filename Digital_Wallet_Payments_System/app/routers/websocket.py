from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User
from app.auth.security import decode_access_token
from app.utils.websocket_manager import manager

router = APIRouter(tags=["Live Notifications"])


@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket, token: str):
    db: Session = SessionLocal()

    try:
        payload = decode_access_token(token)

        if not payload or not payload.get("sub"):
            await websocket.close(code=1008)
            return

        try:
            user_id = int(payload["sub"])
        except (ValueError, TypeError):
            await websocket.close(code=1008)
            return

        user = db.query(User).filter(
            User.id == user_id,
            User.is_active.is_(True)
        ).first()

        if not user:
            await websocket.close(code=1008)
            return

        await manager.connect(user.id, websocket)

        await websocket.send_json({
            "type": "connection",
            "message": "Connected to live wallet notifications"
        })

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        if "user" in locals() and user:
            manager.disconnect(user.id, websocket)

    except Exception:
        if "user" in locals() and user:
            manager.disconnect(user.id, websocket)

    finally:
        db.close()