"""projects — a project holds the campaigns measured at one site (decisions/0014.11).

A project is a folder beside the session workspaces: ``project.json`` (its name, its site
name and its campaigns) and one reanalysis node cache that every campaign reads and writes,
so a node downloaded for the mast is a cache hit for the lidar. Each campaign stays one
session with its own data, data model, coordinate, timezone, flags, log, selections and
results, so the current interface opens it by its session id as before.

Projects are workspace management, like sessions: they are served by HTTP routes, not
declared as operations, because an operation acts on one session and a project is above
them. Nothing here is cached in memory; every call reads the folder, so a restart loses
nothing.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from server.state.manager import SessionManager
from server.state.project import ProjectStore
from server.state.session import SessionState

#: What a campaign measured with (owner, 2026-11-17: masts, ground lidar, floating lidar;
#: no sodar).
CAMPAIGN_KINDS: tuple[str, ...] = ("mast", "lidar", "floating_lidar")
PROJECT_FILE = "project.json"
CACHE_DIR = "reanalysis_cache"
_PROJECT_ID = re.compile(r"^[0-9a-f]{32}$")


class ProjectError(ValueError):
    """A project request that cannot be carried out as written."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _name(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectError(f"A {what} needs a name")
    return value.strip()


class ProjectRegistry:
    """The projects on disk, next to the session workspaces of ``sessions``."""

    def __init__(self, sessions: SessionManager) -> None:
        self.sessions = sessions
        self.base_dir = Path(sessions.base_dir).parent / "projects"

    def _dir(self, project_id: str) -> Path:
        if not _PROJECT_ID.match(project_id):
            raise ProjectError(f"Unknown project '{project_id}'")
        return self.base_dir / project_id

    def _read(self, project_id: str) -> dict[str, Any]:
        path = self._dir(project_id) / PROJECT_FILE
        if not path.exists():
            raise ProjectError(f"Unknown project '{project_id}'")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, project: dict[str, Any]) -> None:
        folder = self._dir(project["id"])
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / f"{PROJECT_FILE}.{uuid4().hex}.tmp"
        temporary.write_text(json.dumps(project, indent=2), encoding="utf-8")
        os.replace(temporary, folder / PROJECT_FILE)

    def cache_dir(self, project_id: str) -> Path:
        return self._dir(project_id) / CACHE_DIR

    def create(self, name: str, site_name: str = "") -> dict[str, Any]:
        project = {
            "id": uuid4().hex,
            "name": _name(name, "project"),
            "site_name": site_name.strip() if isinstance(site_name, str) else "",
            "created_at": _now(),
            "updated_at": _now(),
            "campaigns": [],
        }
        self._write(project)
        self.cache_dir(project["id"]).mkdir(parents=True, exist_ok=True)
        return project

    def list(self) -> list[dict[str, Any]]:
        if not self.base_dir.exists():
            return []
        projects = []
        for folder in sorted(self.base_dir.iterdir()):
            if folder.is_dir() and (folder / PROJECT_FILE).exists() and _PROJECT_ID.match(folder.name):
                projects.append(self._read(folder.name))
        return sorted(projects, key=lambda project: project["updated_at"], reverse=True)

    def get(self, project_id: str) -> dict[str, Any]:
        """The project with each campaign's site as its own data model declares it, and
        whether their declared timezones differ (shown, never reconciled)."""
        project = self._read(project_id)
        campaigns = [{**campaign, **self._campaign_site(campaign["session_id"])} for campaign in project["campaigns"]]
        zones = {campaign["timezone"] for campaign in campaigns if campaign["timezone"] is not None}
        return {**project, "campaigns": campaigns, "timezones_differ": len(zones) > 1}

    def _campaign_config(self, session_id: str) -> dict[str, Any]:
        """The campaign's run configuration without loading its data: the open session's own,
        else the one its saved project holds (saved after every change), else runconfig.json,
        which only some routes write through."""
        loaded = self.sessions.loaded(session_id)
        if loaded is not None:
            return loaded.runconfig
        saved = ProjectStore(self.sessions.base_dir / session_id).saved_field("runconfig")
        if isinstance(saved, dict):
            return saved
        path = self.sessions.base_dir / session_id / "runconfig.json"
        if path.exists():
            try:
                config = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
            return config if isinstance(config, dict) else {}
        return {}

    def _campaign_site(self, session_id: str) -> dict[str, Any]:
        """The campaign's coordinate and timezone as its own configuration declares them."""
        config = self._campaign_config(session_id)
        location = config.get("location") if isinstance(config.get("location"), dict) else {}
        site = config.get("site") if isinstance(config.get("site"), dict) else {}
        return {
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "elevation_m": location.get("elevation_m"),
            "timezone": site.get("timezone"),
        }

    def update(self, project_id: str, name: str | None = None, site_name: str | None = None) -> dict[str, Any]:
        project = self._read(project_id)
        if name is not None:
            project["name"] = _name(name, "project")
        if site_name is not None:
            project["site_name"] = site_name.strip()
        project["updated_at"] = _now()
        self._write(project)
        return project

    def add_campaign(self, project_id: str, name: str, kind: str) -> tuple[dict[str, Any], SessionState]:
        """A new campaign: a new session, recorded in the project and pointed at its cache."""
        project = self._read(project_id)
        if kind not in CAMPAIGN_KINDS:
            raise ProjectError(f"A campaign's kind must be one of {', '.join(CAMPAIGN_KINDS)}, got {kind!r}")
        campaign_name = _name(name, "campaign")
        if any(campaign["name"] == campaign_name for campaign in project["campaigns"]):
            raise ProjectError(f"The project already has a campaign named '{campaign_name}'")
        state = self.sessions.create_session()
        state.project = {"id": project_id, "cache_dir": str(self.cache_dir(project_id).resolve())}
        # Saved now, so the campaign reopens after a restart still pointed at its project.
        ProjectStore(state.workspace_dir).save(state)
        campaign = {"session_id": state.session_id, "name": campaign_name, "kind": kind, "added_at": _now()}
        project["campaigns"].append(campaign)
        project["updated_at"] = _now()
        self._write(project)
        return campaign, state

    def rename_campaign(self, project_id: str, session_id: str, name: str) -> dict[str, Any]:
        project = self._read(project_id)
        campaign_name = _name(name, "campaign")
        matches = [campaign for campaign in project["campaigns"] if campaign["session_id"] == session_id]
        if not matches:
            raise ProjectError(f"The project has no campaign '{session_id}'")
        if any(c["name"] == campaign_name and c["session_id"] != session_id for c in project["campaigns"]):
            raise ProjectError(f"The project already has a campaign named '{campaign_name}'")
        matches[0]["name"] = campaign_name
        project["updated_at"] = _now()
        self._write(project)
        return project
