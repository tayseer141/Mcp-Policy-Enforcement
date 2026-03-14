from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db.session import engine, SessionLocal
from app.db.base import Base
from app.db.seed import seed_data
from app.api.employees import router as employees_router
from app.api.demo import router as demo_router



import app.models.rbac_models
import app.models.employee_model

app = FastAPI(title="MCP Policy Enforcement Prototype")
app.include_router(employees_router)
app.include_router(demo_router)



templates = Jinja2Templates(directory="app/templates")

Base.metadata.create_all(bind=engine)

db = SessionLocal()
seed_data(db)
db.close()


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
