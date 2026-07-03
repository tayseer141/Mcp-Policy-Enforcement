"""
Authentication API.

POST /api/v1/auth/login exchanges username + password for a signed,
expiring bearer token. When DEMO_MODE=false, /api/v1/execute requires
this token in the Authorization header; the token's identity must match
the username in the request body, so a caller can no longer act as an
arbitrary user.

The admin dashboard has its own cookie-based session (app/api/admin.py)
built on the same signing primitives in app.core.security.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_session_token, verify_password
from app.db.deps import get_db
from app.models.rbac_models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

TOKEN_TTL_SECONDS = settings.ADMIN_SESSION_TTL_HOURS * 3600


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    token: str = Field(..., description="Bearer token for /api/v1/execute.")
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Token lifetime in seconds.")


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.username == payload.username).first()

    # Single 401 for unknown user AND wrong password (no enumeration).
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    return LoginResponse(
        token=create_session_token(user.username, TOKEN_TTL_SECONDS),
        expires_in=TOKEN_TTL_SECONDS,
    )