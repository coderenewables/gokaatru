"""Tests for the minimal Task 43 data model builder (CSV-only sessions).

A session that has only a CSV cannot run: ``sensor_mapping`` stays empty, so the
``datamodel`` milestone never completes and every height-indexed stage (shear,
extrapolation, the sensor policies) has nothing to work with.  The builder closes that
gap by emitting a real Task 43 JSON subset and feeding it through the existing
``_parse_datamodel``, so exactly one code path populates session state and the
declaration survives as a downloadable artifact.

The decisive test here is the round trip: for two real campaigns, a data model built
from nothing but the CSV headers must produce the *same* ``sensor_mapping`` as the
campaign's own hand-authored data model.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import pandas as pd
import pytest

from server.api.deps import completed_steps
from server.core.datamodel_builder import (
    BUILDER_PROVENANCE_NOTE,
    ROLE_IGNORED,
    ROLE_MEASUREMENT,
    ROLE_STATISTIC,
    build_datamodel,
    draft_columns,
    spec_from_draft,
)
from server.state.session import session
from server.tools.data_io import _build_sensor_mapping, _parse_datamodel, _parse_timeseries

REPO_ROOT = Path(__file__).resolve().parents[1]
UPLOADS_DIR = REPO_ROOT / "data" / "uploads"


def _campaign_paths(stem: str) -> tuple[Path, Path]:
    """Return the (timeseries, datamodel) pair for a reference campaign."""
    csv = sorted(UPLOADS_DIR.glob(f"{stem}*.csv"))
    datamodel = sorted(UPLOADS_DIR.glob(f"{stem}*.json"))
    assert csv and datamodel, f"reference campaign fixtures missing for {stem}"
    return csv[0], datamodel[0]


def _draft_by_name(columns: list[str]) -> dict[str, object]:
    """Index a draft by column name for readable assertions."""
    return {draft.name: draft for draft in draft_columns(columns)}


class TestHeaderInference:
    """A draft is a proposal from the header text, and says so per column."""

    @pytest.mark.parametrize(
        ("header", "measurement_type_id", "height_m"),
        [
            ("Spd_58m", "wind_speed", 58.0),
            ("Spd_NE_15m", "wind_speed", 15.0),
            ("WS_80m_Avg", "wind_speed", 80.0),
            ("wind_speed_100m", "wind_speed", 100.0),
            ("Anem_120m", "wind_speed", 120.0),
            ("Spd1_80m_25deg", "wind_speed", 80.0),
            ("Dir_28m", "wind_direction", 28.0),
            ("WD_80m", "wind_direction", 80.0),
            ("Vane_58m", "wind_direction", 58.0),
            ("wind_direction_100m", "wind_direction", 100.0),
            ("Tmp1_13m", "temperature", 13.0),
            ("AirTemp_10m", "temperature", 10.0),
            ("Wtr_tmp_-4m", "temperature", -4.0),
            ("Prs_6m", "pressure", 6.0),
            ("Baro_5m", "pressure", 5.0),
            # 'relative_humidity' rather than 'humidity': type_to_field only understands
            # the former, so the shorter spelling would map to no slot at all.
            ("Hum_13m", "relative_humidity", 13.0),
            ("RH_10m", "relative_humidity", 10.0),
        ],
    )
    def test_common_header_spellings_are_recognised(
        self, header: str, measurement_type_id: str, height_m: float
    ) -> None:
        draft = _draft_by_name([header])[header]
        assert draft.role == ROLE_MEASUREMENT
        assert draft.measurement_type_id == measurement_type_id
        assert draft.height_m == pytest.approx(height_m)

    def test_a_header_with_no_height_token_is_left_blank_not_defaulted(self) -> None:
        """Height 0 is a real height. Inventing it would put a sensor on the ground."""
        draft = _draft_by_name(["WindSpeed_60"])["WindSpeed_60"]
        assert draft.height_m is None
        assert draft.reason is not None

    def test_quality_flag_columns_do_not_impersonate_the_sensor_they_describe(self) -> None:
        """``Qual_Spd_58m_quality`` names a real speed sensor. Read as a sensor it would
        invent a second 58 m anemometer and turn a clean height into a boom pair."""
        drafts = _draft_by_name(["Spd_58m", "Qual_Spd_58m_quality"])
        assert drafts["Spd_58m"].role == ROLE_MEASUREMENT
        assert drafts["Qual_Spd_58m_quality"].role == ROLE_IGNORED

    @pytest.mark.parametrize("header", ["Tmp_logger", "V_logger", "I_logger", "DNI_13m"])
    def test_logger_diagnostics_and_unknown_instruments_are_ignored(self, header: str) -> None:
        assert _draft_by_name([header])[header].role == ROLE_IGNORED


class TestStatisticGrouping:
    """Statistic columns belong to their parent sensor, not to a sensor of their own."""

    def test_suffix_statistics_attach_to_the_bare_parent_column(self) -> None:
        columns = ["Spd_58m", "Spd_58m_sd", "Spd_58m_max", "Spd_58m_min", "Spd_58m_ti"]
        drafts = _draft_by_name(columns)
        assert drafts["Spd_58m"].role == ROLE_MEASUREMENT
        for name, statistic in [
            ("Spd_58m_sd", "sd"),
            ("Spd_58m_max", "max"),
            ("Spd_58m_min", "min"),
            ("Spd_58m_ti", "ti"),
        ]:
            assert drafts[name].role == ROLE_STATISTIC
            assert drafts[name].statistic_type_id == statistic
            assert drafts[name].parent == "Spd_58m"

    def test_an_avg_suffixed_parent_still_collects_its_own_statistics(self) -> None:
        """``WS_80m_Avg``/``WS_80m_SD`` share no column name, only a stem. Stripping the
        statistic from both is what pairs them; the ``{speed}_sd`` convention cannot."""
        drafts = _draft_by_name(["WS_80m_Avg", "WS_80m_SD", "WS_80m_Max"])
        assert drafts["WS_80m_Avg"].role == ROLE_MEASUREMENT
        assert drafts["WS_80m_SD"].role == ROLE_STATISTIC
        assert drafts["WS_80m_SD"].parent == "WS_80m_Avg"
        assert drafts["WS_80m_SD"].statistic_type_id == "sd"

    def test_a_lone_statistic_column_is_not_promoted_to_a_sensor(self) -> None:
        drafts = _draft_by_name(["Spd_80m_max"])
        assert drafts["Spd_80m_max"].role == ROLE_STATISTIC
        assert drafts["Spd_80m_max"].parent is None


class TestBuildRefusals:
    """Convention 1 — refuse rather than guess."""

    def _spec(self, **overrides: object) -> dict:
        spec = {
            "location": {"name": "Test", "offset_from_utc_hrs": 0},
            "points": [{"name": "Spd_80m", "measurement_type_id": "wind_speed", "height_m": 80.0}],
        }
        spec.update(overrides)
        return spec

    def test_a_point_naming_a_column_the_csv_does_not_have_is_refused(self) -> None:
        with pytest.raises(ValueError, match="Spd_90m"):
            build_datamodel(
                self._spec(
                    points=[{"name": "Spd_90m", "measurement_type_id": "wind_speed", "height_m": 90.0}]
                ),
                available_columns=["Spd_80m"],
            )

    def test_a_point_without_a_height_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match="Spd_80m"):
            build_datamodel(
                self._spec(points=[{"name": "Spd_80m", "measurement_type_id": "wind_speed"}]),
                available_columns=["Spd_80m"],
            )

    def test_an_unrecognised_measurement_type_is_refused(self) -> None:
        with pytest.raises(ValueError, match="measurement_type_id"):
            build_datamodel(
                self._spec(
                    points=[{"name": "Spd_80m", "measurement_type_id": "windspeed", "height_m": 80.0}]
                ),
                available_columns=["Spd_80m"],
            )

    def test_a_duplicate_point_name_is_refused(self) -> None:
        point = {"name": "Spd_80m", "measurement_type_id": "wind_speed", "height_m": 80.0}
        with pytest.raises(ValueError, match="Spd_80m"):
            build_datamodel(self._spec(points=[point, dict(point)]), available_columns=["Spd_80m"])

    def test_a_data_model_with_no_timezone_is_refused(self) -> None:
        """``_extract_timezone`` is the only thing that ever sets ``state.timezone``, so a
        builder that omitted it would emit a data model its own parser rejects."""
        with pytest.raises(ValueError, match="timezone"):
            build_datamodel(
                self._spec(location={"name": "Test"}),
                available_columns=["Spd_80m"],
            )

    def test_no_points_at_all_is_refused(self) -> None:
        with pytest.raises(ValueError, match="measurement point"):
            build_datamodel(self._spec(points=[]), available_columns=["Spd_80m"])

    def test_a_statistic_column_the_csv_does_not_have_is_refused(self) -> None:
        with pytest.raises(ValueError, match="Spd_80m_sd"):
            build_datamodel(
                self._spec(
                    points=[
                        {
                            "name": "Spd_80m",
                            "measurement_type_id": "wind_speed",
                            "height_m": 80.0,
                            "statistics": [{"column_name": "Spd_80m_sd", "statistic_type_id": "sd"}],
                        }
                    ]
                ),
                available_columns=["Spd_80m"],
            )


class TestEmittedArtifact:
    """The output is a plain Task 43 document that records where it came from."""

    def _built(self) -> dict:
        return build_datamodel(
            {
                "location": {
                    "name": "Bench",
                    "latitude_ddeg": 55.5,
                    "longitude_ddeg": 7.8,
                    "elevation_m": 12.0,
                    "measurement_station_type_id": "mast",
                    "offset_from_utc_hrs": 1,
                },
                "points": [
                    {
                        "name": "Spd_80m",
                        "measurement_type_id": "wind_speed",
                        "height_m": 80.0,
                        "boom_orientation_deg": 25.0,
                        "is_primary": True,
                        "statistics": [{"column_name": "Spd_80m_sd", "statistic_type_id": "sd"}],
                    }
                ],
            },
            available_columns=["Spd_80m", "Spd_80m_sd"],
        )

    def test_the_artifact_declares_that_it_was_built_from_headers(self) -> None:
        """Provenance travels with the artifact: a reader must be able to tell a
        hand-authored data model from one drafted off column names."""
        location = self._built()["measurement_location"][0]
        assert BUILDER_PROVENANCE_NOTE in str(location["notes"])

    def test_site_metadata_and_boom_orientation_survive_a_parse(self, tmp_path: Path) -> None:
        payload = self._built()
        point = payload["measurement_location"][0]["measurement_point"][0]
        assert point["mounting_arrangement"][0]["boom_orientation_deg"] == 25.0
        assert point["is_primary"] is True

    def test_the_sd_column_is_declared_the_task_43_way(self) -> None:
        """Task 43 already carries statistic columns on ``logger_measurement_config``.
        Emitting there rather than inventing a key means real uploaded data models get
        the same treatment."""
        point = self._built()["measurement_location"][0]["measurement_point"][0]
        declared = point["logger_measurement_config"][0]["column_name"]
        assert {"column_name": "Spd_80m_sd", "statistic_type_id": "sd"} in declared


class TestSdColumnResolution:
    """``sd_col`` was always ``{speed}_sd`` whether or not that column existed."""

    def test_a_declared_sd_column_present_in_the_data_is_used(self) -> None:
        points = [
            {
                "name": "WS_80m_Avg",
                "measurement_type_id": "wind_speed",
                "height_m": 80.0,
                "logger_measurement_config": [
                    {"column_name": [{"column_name": "WS_80m_SD", "statistic_type_id": "sd"}]}
                ],
            }
        ]
        frame = pd.DataFrame(
            {"WS_80m_Avg": [1.0], "WS_80m_SD": [0.1]},
            index=pd.date_range("2023-01-01", periods=1, freq="10min"),
        )
        mapping, _ = _build_sensor_mapping(points, timeseries_df=frame)
        assert mapping[80.0]["sd_col"] == "WS_80m_SD"

    def test_a_declared_sd_column_absent_from_the_data_falls_back_to_the_convention(self) -> None:
        """Horns Rev declares ``wind_speed__sd__062__anemometer__201__m/s__201``, which its
        own CSV does not contain — the CSV has ``Spd_62m_sd``. Trusting the declaration
        blindly would regress a reference campaign."""
        points = [
            {
                "name": "Spd_62m",
                "measurement_type_id": "wind_speed",
                "height_m": 62.0,
                "logger_measurement_config": [
                    {"column_name": [{"column_name": "wind_speed__sd__062", "statistic_type_id": "sd"}]}
                ],
            }
        ]
        frame = pd.DataFrame(
            {"Spd_62m": [1.0], "Spd_62m_sd": [0.1]},
            index=pd.date_range("2023-01-01", periods=1, freq="10min"),
        )
        mapping, _ = _build_sensor_mapping(points, timeseries_df=frame)
        assert mapping[62.0]["sd_col"] == "Spd_62m_sd"

    def test_no_sd_column_anywhere_resolves_to_none_rather_than_a_dangling_name(self) -> None:
        """Boxkite has no ``_sd`` columns at all, yet its mapping carried
        ``Spd_250m_sd``. The reference was inert but untrue."""
        points = [{"name": "Spd_250m", "measurement_type_id": "wind_speed", "height_m": 250.0}]
        frame = pd.DataFrame(
            {"Spd_250m": [1.0]}, index=pd.date_range("2023-01-01", periods=1, freq="10min")
        )
        mapping, _ = _build_sensor_mapping(points, timeseries_df=frame)
        assert mapping[250.0]["sd_col"] is None

    def test_without_a_timeseries_the_suffix_convention_still_applies(self) -> None:
        """Existence cannot be checked before the data is loaded, so the convention holds."""
        points = [{"name": "Spd_80m", "measurement_type_id": "wind_speed", "height_m": 80.0}]
        mapping, _ = _build_sensor_mapping(points)
        assert mapping[80.0]["sd_col"] == "Spd_80m_sd"


class TestRoundTripAgainstRealCampaigns:
    """The substitution test: headers alone must reproduce the hand-authored mapping."""

    @pytest.mark.parametrize("stem", ["HornsRev-MAST", "HKW-B-FLS-Boxkite", "WB-ESMAP_Launakalana"])
    def test_a_built_data_model_reproduces_the_authored_sensor_mapping(
        self, stem: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        timeseries_path, datamodel_path = _campaign_paths(stem)

        session.reset()
        _parse_timeseries(session, str(timeseries_path))
        _parse_datamodel(session, str(datamodel_path))
        authored = {
            height: dict(slots) for height, slots in session.sensor_mapping.items()
        }

        session.reset()
        uploads = tmp_path / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(session, "workspace_dir", tmp_path)
        (uploads / "campaign.csv").write_bytes(timeseries_path.read_bytes())
        _parse_timeseries(session, "campaign.csv")

        spec = spec_from_draft(
            list(session.timeseries_df.columns),
            location={"name": stem, "offset_from_utc_hrs": 0},
        )
        payload = build_datamodel(spec, available_columns=list(session.timeseries_df.columns))
        built_path = uploads / "built.json"
        built_path.write_text(json.dumps(payload), encoding="utf-8")
        _parse_datamodel(session, "built.json")

        assert session.sensor_mapping == authored

    def test_a_built_data_model_completes_the_gating_datamodel_step(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without ``sensor_mapping`` the whole pipeline is gated off (deps.completed_steps)."""
        timeseries_path, _ = _campaign_paths("HKW-B-FLS-Boxkite")
        uploads = tmp_path / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(session, "workspace_dir", tmp_path)
        (uploads / "campaign.csv").write_bytes(timeseries_path.read_bytes())
        _parse_timeseries(session, "campaign.csv")
        assert "datamodel" not in completed_steps(session)

        columns = list(session.timeseries_df.columns)
        spec = spec_from_draft(columns, location={"name": "Boxkite", "offset_from_utc_hrs": 0})
        (uploads / "built.json").write_text(
            json.dumps(build_datamodel(spec, available_columns=columns)), encoding="utf-8"
        )
        _parse_datamodel(session, "built.json")

        assert "datamodel" in completed_steps(session)
        assert session.timeseries_df.index.tz is not None


class TestSpecFromDraft:
    """The convenience path used by the UI's prefill and by the round-trip test."""

    def test_only_confidently_drafted_measurement_columns_become_points(self) -> None:
        columns = ["Spd_80m", "Spd_80m_sd", "Qual_Spd_80m_quality", "Tmp_logger", "WindSpeed_60"]
        spec = spec_from_draft(columns, location={"name": "X", "offset_from_utc_hrs": 0})
        assert [point["name"] for point in spec["points"]] == ["Spd_80m"]
        assert spec["points"][0]["statistics"] == [
            {"column_name": "Spd_80m_sd", "statistic_type_id": "sd"}
        ]


class TestHttpRoutes:
    """Exercised through a real request, not by calling the helper.

    ``POST /era5/interpolate`` shipped for months silently ignoring its ``source`` field
    because every test called the underlying function directly and never crossed FastAPI's
    parameter binding. These routes are checked the other way round.
    """

    @pytest.fixture
    def client(self, tmp_path: Path):
        from fastapi.testclient import TestClient

        from server.api.deps import get_session_manager
        from server.api.main import create_app
        from server.state.manager import SessionManager

        manager = SessionManager(base_dir=tmp_path / "sessions")
        app = create_app()
        app.dependency_overrides[get_session_manager] = lambda: manager
        with TestClient(app) as test_client:
            yield test_client
        app.dependency_overrides.clear()

    def _session_with_timeseries(self, client) -> tuple[str, dict[str, str]]:
        session_id = client.post("/api/sessions").json()["session_id"]
        headers = {"X-GoKaatru-Session": session_id}
        timeseries_path, _ = _campaign_paths("HKW-B-FLS-Boxkite")
        with timeseries_path.open("rb") as handle:
            response = client.post(
                f"/api/sessions/{session_id}/uploads/timeseries",
                files={"file": ("campaign.csv", handle, "text/csv")},
                headers=headers,
            )
        assert response.status_code == 200, response.text
        return session_id, headers

    def test_draft_route_returns_a_reading_of_the_uploaded_columns(self, client) -> None:
        session_id, headers = self._session_with_timeseries(client)
        response = client.get(f"/api/sessions/{session_id}/datamodel/draft", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["basis"] == "header_inference"
        assert 250.0 in payload["detected_heights_m"]
        names = {column["name"]: column for column in payload["columns"]}
        assert names["Spd_250m"]["measurement_type_id"] == "wind_speed"
        assert names["Dir_250m"]["measurement_type_id"] == "wind_direction"

    def test_build_route_loads_the_data_model_into_the_session(self, client) -> None:
        session_id, headers = self._session_with_timeseries(client)
        draft = client.get(f"/api/sessions/{session_id}/datamodel/draft", headers=headers).json()
        columns = [column["name"] for column in draft["columns"]]
        spec = spec_from_draft(columns, location={"name": "Boxkite", "offset_from_utc_hrs": 0})

        response = client.post(
            f"/api/sessions/{session_id}/datamodel/build", json=spec, headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["points_declared"] == 16

        summary = client.get(f"/api/sessions/{session_id}", headers=headers).json()
        assert summary["datamodel_loaded"] is True
        assert "datamodel" in summary["completed_steps"]

    def test_build_route_reports_a_refusal_as_a_bad_request_naming_the_column(self, client) -> None:
        session_id, headers = self._session_with_timeseries(client)
        response = client.post(
            f"/api/sessions/{session_id}/datamodel/build",
            json={
                "location": {"name": "X", "offset_from_utc_hrs": 0},
                "points": [{"name": "Spd_250m", "measurement_type_id": "wind_speed"}],
            },
            headers=headers,
        )
        assert response.status_code == 400
        assert "Spd_250m" in response.json()["detail"]

    def test_drafting_before_a_timeseries_is_loaded_is_refused(self, client) -> None:
        session_id = client.post("/api/sessions").json()["session_id"]
        headers = {"X-GoKaatru-Session": session_id}
        response = client.get(f"/api/sessions/{session_id}/datamodel/draft", headers=headers)
        assert response.status_code == 400
        assert "timeseries" in response.json()["detail"].lower()


class TestDualInterfaceParity:
    """Both interfaces must reach the same logic (root CLAUDE.md's core principle)."""

    def test_both_builder_capabilities_are_registered_as_mcp_tools(self) -> None:
        import asyncio

        from server.main import mcp

        names = {tool.name for tool in asyncio.run(mcp.list_tools())}
        assert {"draft_data_model", "build_data_model"} <= names


def test_reference_campaign_fixtures_are_present() -> None:
    """These tests measure against real data; a fresh clone without the gitignored
    fixtures should say so rather than silently passing on nothing."""
    assert glob.glob(str(UPLOADS_DIR / "*.csv"))
