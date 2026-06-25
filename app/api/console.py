from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.rbac_models import User

router = APIRouter(tags=["console"])
templates = Jinja2Templates(directory="app/templates")


def _load_users(db: Session) -> list[dict]:
    rows = db.query(User).order_by(User.username.asc()).all()
    return [
        {
            "username": u.username,
            "role": u.role.name if u.role else None,
            "permissions": (
                [p.name for p in u.role.permissions] if u.role else []
            ),
        }
        for u in rows
    ]


@router.get("/console", response_class=HTMLResponse)
def console_page(request: Request, db: Session = Depends(get_db)):
    """Render the secure MCP console."""
    return templates.TemplateResponse(
        "console.html",
        {
            "request": request,
            "title": "MCP Secure Console",
            "users": _load_users(db),
        },
    )