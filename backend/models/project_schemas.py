from pydantic import BaseModel
from typing import Optional


class CreateProjectRequest(BaseModel):
    name: str
    username: str


class RenameProjectRequest(BaseModel):
    name: str


class ProjectResponse(BaseModel):
    id: str
    name: str
    username: str
    phase: str
    created_at: str
    updated_at: str


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]


class ResumeProjectResponse(BaseModel):
    session_id: str
    project: ProjectResponse
    phase: str
    files: list[dict]
    preview: dict
    inferred_schema: dict
    stats: dict
    ddl_schema: dict
    config: Optional[dict] = None
    validation: Optional[dict] = None
    transform: Optional[dict] = None
    load_result: Optional[dict] = None
