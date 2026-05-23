"""
routes/session_routes.py — Quản lý phiên chat của người dùng:
  GET    /sessions          → Danh sách phiên
  POST   /sessions          → Tạo phiên mới
  DELETE /sessions/{id}     → Xóa phiên
  PATCH  /sessions/{id}     → Đổi tên phiên
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from auth import require_auth
from database import (
    get_user_sessions,
    create_session,
    delete_session,
    rename_session,
    session_belongs_to_user,
)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class NewSessionRequest(BaseModel):
    title: str = "Cuộc trò chuyện mới"


class RenameSessionRequest(BaseModel):
    title: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("", summary="Danh sách phiên chat của user")
async def list_sessions(current_user: dict = Depends(require_auth)):
    sessions = get_user_sessions(current_user["id"])
    return {"sessions": sessions}


@router.post("", summary="Tạo phiên chat mới")
async def new_session(req: NewSessionRequest, current_user: dict = Depends(require_auth)):
    return create_session(current_user["id"], req.title)


@router.delete("/{session_id}", summary="Xóa phiên chat")
async def remove_session(session_id: str, current_user: dict = Depends(require_auth)):
    try:
        delete_session(session_id, current_user["id"])
        return {"status": "deleted"}
    except PermissionError as e:
        raise HTTPException(403, str(e))


@router.patch("/{session_id}", summary="Đổi tên phiên chat")
async def update_session_title(
    session_id: str,
    req: RenameSessionRequest,
    current_user: dict = Depends(require_auth),
):
    if not session_belongs_to_user(session_id, current_user["id"]):
        raise HTTPException(403, "Không có quyền chỉnh sửa phiên này.")
    rename_session(session_id, current_user["id"], req.title)
    return {"status": "updated"}
