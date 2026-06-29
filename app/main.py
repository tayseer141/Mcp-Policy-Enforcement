from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db.base import Base
from app.db.seed import seed_data
from app.db.session import SessionLocal, engine

# --- Routers --------------------------------------------------------
# View layer (HTML pages)
from app.api.admin import router as admin_router
from app.api.console import router as console_router

# Data plane / control plane (JSON API)
from app.api.admin_api import router as admin_api_router
from app.api.policy_api import router as policy_api_router
from app.api.execute import router as execute_router

# Other surfaces
from app.api.employees import router as employees_router
from app.api.mcp import router as mcp_router

# Side-effect imports so SQLAlchemy sees every model on Base.metadata
# before create_all runs.
import app.models.customer_model  # noqa: F401
import app.models.rbac_models  # noqa: F401
import app.models.policy_model  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up: Initializing DB and seeding data...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        seed_data(db)
    finally:
        db.close()

    print("MCP Tools are managed by the dedicated MCP Server.")
    print("Application is ready!")

    yield

    print("Shutting down Application...")


app = FastAPI(
    title="MCP Policy Enforcement Platform",
    description=(
        "Secure, policy-enforced access to enterprise data via the Model "
        "Context Protocol. Exposes a JSON API (POST /api/v1/execute, "
        "/api/v1/admin/*) consumed by the bundled HTML console and admin "
        "dashboard."
    ),
    lifespan=lifespan,
)

# --- Static assets (console CSS/JS module) ---
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# --- View layer (HTML) ---
app.include_router(console_router)  # GET /console
app.include_router(admin_router)    # /admin/login, /admin, /admin/users, ...

# --- JSON API ---
app.include_router(execute_router)      # POST /api/v1/execute
app.include_router(admin_api_router)    # /api/v1/admin/users, /roles, /permissions
app.include_router(policy_api_router)   # /api/v1/admin/policies, /policy-types

# --- Other surfaces ---
app.include_router(employees_router)
app.include_router(mcp_router)


templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "MCP Policy Enforcement Platform",
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.exception_handler(HTTPException)
async def _admin_auth_redirect(request: Request, exc: HTTPException):
    """
    UX nicety: when an admin session has expired and the user navigates
    to an HTML admin page, bounce them to the login form instead of
    showing a raw 401 page.

    Important scope: this only fires for HTML routes under /admin. JSON
    requests to /api/v1/admin/* deliberately get the standard 401 JSON
    response so fetch() callers can handle session expiry themselves
    (the admin templates show the message in the notice area).
    """
    if (
        request.url.path.startswith("/admin")
        and exc.status_code in (401, 403)
        and exc.detail in ("admin_login_required", "admin_role_required")
    ):
        return RedirectResponse(url="/admin/login", status_code=303)

    # Fall back to FastAPI's default behavior for everything else.
    from fastapi.exception_handlers import http_exception_handler
    return await http_exception_handler(request, exc)