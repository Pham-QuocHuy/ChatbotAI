"""
auth.py — Xác thực người dùng:
  - Tạo / giải mã JWT token
  - FastAPI dependency: get_current_user (tuỳ chọn) và require_auth (bắt buộc)
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from database import get_user_by_id

# ---------------------------------------------------------------------------
# Bearer scheme (auto_error=False → trả None thay vì 403 khi thiếu token)
# ---------------------------------------------------------------------------
security = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------
def create_access_token(data: dict) -> str:
    """Tạo JWT token với thời hạn cấu hình sẵn."""
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Giải mã JWT. Trả về None nếu token không hợp lệ hoặc hết hạn."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# FastAPI Dependencies
# ---------------------------------------------------------------------------
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Optional[dict]:
    """
    Dependency tuỳ chọn:
      - Trả về user dict nếu token hợp lệ
      - Trả về None nếu không có token (Guest mode)
    """
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return get_user_by_id(int(user_id))


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Dependency bắt buộc:
      - Trả về user dict nếu token hợp lệ
      - Raise 401 nếu không đăng nhập hoặc token sai
    """
    user = await get_current_user(credentials)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Chưa đăng nhập hoặc token không hợp lệ."
        )
    return user
