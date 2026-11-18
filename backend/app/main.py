import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.api.deps import csrf_guard
from app.api.routes import analysis, auth, conversations, datasets, insights, metrics, public, reports, workspaces
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()



@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="ClearMetric API", version="2.0.0", description="AI business analyst: evidence-backed analytics API.",
              docs_url="/api/docs", openapi_url="/api/openapi.json", dependencies=[Depends(csrf_guard)], lifespan=lifespan)
install_error_handlers(app)

for r in (public.router, auth.router, workspaces.router, workspaces.invite_router, workspaces.account_router,
          datasets.router, datasets.rel_router, metrics.router, analysis.router, conversations.router,
          insights.router, reports.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
