"""projects — the projects on disk and their campaigns (P2-8, decisions/0014.11).

A campaign is a session: adding one creates it, and every session route then serves it by
its id. Projects are workspace management above the sessions, like ``POST /sessions``, so
they are routes here and not operations (``server/state/projects.py``).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from server.api.deps import get_session_manager
from server.schemas.results._base import ErrorDetail, Number, Result
from server.state.manager import SessionManager
from server.state.projects import ProjectError, ProjectRegistry

router = APIRouter(prefix="/projects", tags=["projects"])
_ERRORS = {400: {"model": ErrorDetail}, 404: {"model": ErrorDetail}}


def get_project_registry(manager: Annotated[SessionManager, Depends(get_session_manager)]) -> ProjectRegistry:
    # Built per request beside the session manager's folder, so a test's manager moves both.
    return ProjectRegistry(manager)


Registry = Annotated[ProjectRegistry, Depends(get_project_registry)]


class Campaign(Result):
    session_id: str
    name: str
    #: ``mast``, ``lidar`` or ``floating_lidar``.
    kind: str
    added_at: str


class CampaignSite(Campaign):
    """A campaign with its site as its own data model and configuration declare it."""

    latitude: Number = None
    longitude: Number = None
    elevation_m: Number = None
    timezone: str | None = None


class Project(Result):
    id: str
    name: str
    site_name: str
    created_at: str
    updated_at: str
    campaigns: list[Campaign]


class ProjectDetail(Project):
    campaigns: list[CampaignSite]  # type: ignore[assignment]
    #: Whether the campaigns declare different timezones; shown, never reconciled.
    timezones_differ: bool


class ProjectList(Result):
    projects: list[Project]


class CreateProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    site_name: str = ""


class UpdateProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    site_name: str | None = None


class AddCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    kind: str


class RenameCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


def _refused(exc: ProjectError) -> HTTPException:
    status = 404 if str(exc).startswith(("Unknown project", "The project has no campaign")) else 400
    return HTTPException(status_code=status, detail=str(exc))


@router.get("", response_model=ProjectList)
def list_projects(registry: Registry) -> dict:
    """Every project, most recently changed first."""
    return {"projects": registry.list()}


@router.post("", response_model=Project, responses=_ERRORS)
def create_project(body: CreateProject, registry: Registry) -> dict:
    """A new project with no campaigns yet."""
    try:
        return registry.create(body.name, body.site_name)
    except ProjectError as exc:
        raise _refused(exc) from exc


@router.get("/{project_id}", response_model=ProjectDetail, responses=_ERRORS)
def get_project(project_id: str, registry: Registry) -> dict:
    """The project, each campaign with its own coordinate and timezone."""
    try:
        return registry.get(project_id)
    except ProjectError as exc:
        raise _refused(exc) from exc


@router.patch("/{project_id}", response_model=Project, responses=_ERRORS)
def update_project(project_id: str, body: UpdateProject, registry: Registry) -> dict:
    """Rename the project or its site."""
    try:
        return registry.update(project_id, body.name, body.site_name)
    except ProjectError as exc:
        raise _refused(exc) from exc


@router.post("/{project_id}/campaigns", response_model=Campaign, responses=_ERRORS)
def add_campaign(project_id: str, body: AddCampaign, registry: Registry) -> dict:
    """A new campaign in the project: a new session, sharing the project's reanalysis cache."""
    try:
        campaign, _ = registry.add_campaign(project_id, body.name, body.kind)
    except ProjectError as exc:
        raise _refused(exc) from exc
    return campaign


@router.patch("/{project_id}/campaigns/{session_id}", response_model=Project, responses=_ERRORS)
def rename_campaign(project_id: str, session_id: str, body: RenameCampaign, registry: Registry) -> dict:
    """Rename one of the project's campaigns."""
    try:
        return registry.rename_campaign(project_id, session_id, body.name)
    except ProjectError as exc:
        raise _refused(exc) from exc
