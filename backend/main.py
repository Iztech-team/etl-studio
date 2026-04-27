from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import downloads, extract, pipeline, projects, system, tables
from startup import lifespan

app = FastAPI(title="ETL Legacy", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(extract.router, prefix="/api")
app.include_router(tables.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api")
app.include_router(downloads.router, prefix="/api")
