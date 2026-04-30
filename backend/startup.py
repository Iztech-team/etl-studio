import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from persistence.db import backfill_pipeline_runs, init_db

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
GUEST_DIR = os.path.join(os.path.dirname(__file__), "data", "guest")


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(GUEST_DIR, exist_ok=True)
    init_db()
    backfill_pipeline_runs()
    yield
