"""
Demo console (view layer).

This module is now a thin HTML view: it renders the console shell and
seeds it with the current user list so the dropdown is in sync with
the database. All execution traffic flows through the JSON API at
POST /api/v1/execute — see app/api/execute.py.

Keeping this file as a pure view makes the platform structure visible
in the directory listing: app/api/execute.py is the API, app/api/demo.py
is one of its clients.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.rbac_models import User

router = APIRouter(tags=["demo"])
templates = Jinja2Templates(directory="app/templates")


def _load_users(db: Session) -> list[dict]:
    """
    Return the current user list from the DB so the console dropdown
    is always in sync with whatever the admin dashboard has created.

    Each entry includes the user's role and the names of every
    permission attached to that role, so the console can render a
    permission-preview chip strip when the operator selects a user
    (makes RBAC denials self-explanatory at a glance).
    """
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


@router.get("/demo", response_class=HTMLResponse)
def demo_page(request: Request, db: Session = Depends(get_db)):
    """Render the secure MCP console."""
    return templates.TemplateResponse(
        "demo.html",
        {
            "request": request,
            "title": "MCP Secure Console",
            "users": _load_users(db),
        },
    )