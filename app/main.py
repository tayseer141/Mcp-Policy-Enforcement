from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db.session import engine, SessionLocal
from app.db.base import Base
from app.db.seed import seed_data
from app.api.employees import router as employees_router
from app.api.demo import router as demo_router
from app.api.mcp import router as mcp_router
from app.api.rbac_admin import router as rbac_admin_router

import app.models.rbac_models
import app.models.employee_model

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
    # The official MCP server handles its own tool registration
    
    print("Application is ready!")
    
    yield  
    
    print("Shutting down Application...")


app = FastAPI(
    title="MCP Policy Enforcement Prototype",
    lifespan=lifespan
)

app.include_router(employees_router)
app.include_router(demo_router)
app.include_router(mcp_router)
app.include_router(rbac_admin_router)

templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "MCP Policy Enforcement Prototype"
        }
    )

@app.get("/health")
async def health():
    return {"status": "ok"}