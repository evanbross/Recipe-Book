from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import Base
from app.routes import recipes, tags, capture, search

app = FastAPI(
    title="Recipe Organizer API",
    version="0.1.0",
    description="Capture and organize recipes from web pages, photos, and scans.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recipes.router)
app.include_router(tags.router)
app.include_router(capture.router)
app.include_router(search.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
