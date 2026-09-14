// Build a minimal IEA Task 43 data model for a campaign that arrived as a bare CSV.
//
// Without a data model nothing populates the sensor mapping or the campaign timezone, so
// the pipeline is gated off entirely. The draft below is read off the column headers and
// is a proposal, not an answer: a column whose height could not be read blocks the build
// until it is declared, because a height guessed wrongly is undetectable downstream.
import { useEffect, useMemo, useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { RunButton } from "../common/RunButton";
import type {
  DataModelDraftColumn,
  DataModelPointSpec,
  DataModelStatisticSpec,
} from "../../types/analysis";

const MEASUREMENT_TYPES: { value: string; label: string }[] = [
  { value: "wind_speed", label: "Wind speed" },
  { value: "wind_direction", label: "Wind direction" },
  { value: "temperature", label: "Temperature" },
  { value: "pressure", label: "Pressure" },
  { value: "relative_humidity", label: "Relative humidity" },
];

interface RowState {
  name: string;
  include: boolean;
  measurementTypeId: string;
  height: string;
  boomOrientation: string;
  isPrimary: boolean;
  sdColumn: string | null;
  inferredType: string | null;
  inferredHeight: number | null;
  reason: string | null;
}

function toRows(columns: DataModelDraftColumn[]): RowState[] {
  const sdByParent = new Map<string, string>();
  for (const column of columns) {
    if (column.role === "statistic" && column.statistic_type_id === "sd" && column.parent) {
      sdByParent.set(column.parent, column.name);
    }
  }
  return columns
    .filter((column) => column.role === "measurement")
    .map((column) => ({
      name: column.name,
      include: true,
      measurementTypeId: column.measurement_type_id ?? "",
      height: column.height_m === null ? "" : String(column.height_m),
      boomOrientation: "",
      isPrimary: false,
      sdColumn: sdByParent.get(column.name) ?? null,
      inferredType: column.measurement_type_id,
      inferredHeight: column.height_m,
      reason: column.reason,
    }));
}

export function DataModelBuilder() {
  const draft = useWorkspaceStore((state) => state.dataModelDraft);
  const loadDataModelDraft = useWorkspaceStore((state) => state.loadDataModelDraft);
  const buildDataModel = useWorkspaceStore((state) => state.buildDataModel);
  const config = useWorkspaceStore((state) => state.config);
  const summary = useWorkspaceStore((state) => state.summary);

  const [rows, setRows] = useState<RowState[]>(() => toRows(draft?.columns ?? []));
  const [utcOffset, setUtcOffset] = useState("0");
  const [ianaZone, setIanaZone] = useState("");

  useEffect(() => {
    setRows(toRows(draft?.columns ?? []));
  }, [draft]);

  const patch = (name: string, changes: Partial<RowState>) => {
    setRows((previous) =>
      previous.map((row) => (row.name === name ? { ...row, ...changes } : row)),
    );
  };

  const included = rows.filter((row) => row.include);
  const incomplete = included.filter(
    (row) => row.height.trim() === "" || Number.isNaN(Number(row.height)) || !row.measurementTypeId,
  );
  const offsetIsNumeric = utcOffset.trim() !== "" && !Number.isNaN(Number(utcOffset));
  const canBuild =
    included.length > 0 && incomplete.length === 0 && (offsetIsNumeric || ianaZone.trim() !== "");

  const ignored = useMemo(
    () => (draft?.columns ?? []).filter((column) => column.role !== "measurement"),
    [draft],
  );

  if (!summary?.timeseries_loaded) {
    return (
      <section className="path-panel">
        <h3>Build data model</h3>
        <p className="muted">
          Upload a timeseries first — the builder describes the columns it actually has.
        </p>
      </section>
    );
  }

  if (!draft) {
    return (
      <section className="path-panel">
        <h3>Build data model</h3>
        <p className="muted">
          No IEA Task 43 JSON? Read the sensors straight off the CSV column headers and
          declare the few things the pipeline cannot work without.
        </p>
        <RunButton label="Read columns" onClick={() => void loadDataModelDraft()} />
      </section>
    );
  }

  const submit = () => {
    const points: DataModelPointSpec[] = included.map((row) => {
      const statistics: DataModelStatisticSpec[] = row.sdColumn
        ? [{ column_name: row.sdColumn, statistic_type_id: "sd" }]
        : [];
      const point: DataModelPointSpec = {
        name: row.name,
        measurement_type_id: row.measurementTypeId,
        height_m: Number(row.height),
      };
      if (row.boomOrientation.trim() !== "" && !Number.isNaN(Number(row.boomOrientation))) {
        point.boom_orientation_deg = Number(row.boomOrientation);
      }
      if (row.isPrimary) point.is_primary = true;
      if (statistics.length > 0) point.statistics = statistics;
      return point;
    });

    void buildDataModel({
      location: {
        name: config.project.name || "Unnamed site",
        latitude_ddeg: config.site.latitude,
        longitude_ddeg: config.site.longitude,
        elevation_m: config.site.elevationM,
        measurement_station_type_id: config.project.measurementType,
        ...(ianaZone.trim() !== "" ? { timezone: ianaZone.trim() } : {}),
        ...(offsetIsNumeric ? { offset_from_utc_hrs: Number(utcOffset) } : {}),
      },
      points,
    });
  };

  return (
    <section className="path-panel">
      <h3>Build data model</h3>
      <p className="muted">{draft.note}</p>

      <div className="form-grid">
        <label className="form-field">
          <span>Logger UTC offset (hours)</span>
          <input
            type="number"
            step="0.25"
            aria-label="UTC offset in hours"
            value={utcOffset}
            onChange={(e) => setUtcOffset(e.target.value)}
          />
        </label>
        <label className="form-field">
          <span>IANA timezone (optional)</span>
          <input
            type="text"
            aria-label="IANA timezone"
            placeholder="Europe/Copenhagen"
            value={ianaZone}
            onChange={(e) => setIanaZone(e.target.value)}
          />
        </label>
      </div>
      <p className="muted">
        A logger clock normally runs on a fixed offset. Declare an IANA zone only if this
        campaign really followed daylight saving — it takes precedence over the offset.
      </p>

      <table className="data-table sensor-table" aria-label="Declared sensors">
        <thead>
          <tr>
            <th></th>
            <th>Column</th>
            <th>Measurement type</th>
            <th>Height (m)</th>
            <th>Boom (°)</th>
            <th>Primary</th>
            <th>Turbulence column</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.name} className={row.include ? "row-selected" : ""}>
              <td>
                <input
                  type="checkbox"
                  aria-label={`Include ${row.name}`}
                  checked={row.include}
                  onChange={() => patch(row.name, { include: !row.include })}
                />
              </td>
              <td>
                {row.name}
                {row.reason ? <div className="muted">{row.reason}</div> : null}
              </td>
              <td>
                <select
                  aria-label={`Measurement type for ${row.name}`}
                  value={row.measurementTypeId}
                  onChange={(e) => patch(row.name, { measurementTypeId: e.target.value })}
                >
                  <option value="">Declare…</option>
                  {MEASUREMENT_TYPES.map((type) => (
                    <option key={type.value} value={type.value}>
                      {type.label}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <input
                  type="number"
                  step="0.1"
                  aria-label={`Height for ${row.name}`}
                  value={row.height}
                  onChange={(e) => patch(row.name, { height: e.target.value })}
                />
              </td>
              <td>
                <input
                  type="number"
                  step="1"
                  aria-label={`Boom orientation for ${row.name}`}
                  value={row.boomOrientation}
                  onChange={(e) => patch(row.name, { boomOrientation: e.target.value })}
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  aria-label={`Primary sensor ${row.name}`}
                  checked={row.isPrimary}
                  onChange={() => patch(row.name, { isPrimary: !row.isPrimary })}
                />
              </td>
              <td>{row.sdColumn ?? <span className="muted">none</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {ignored.length > 0 ? (
        <details className="preview-details">
          <summary>Columns not read as sensors ({ignored.length})</summary>
          <table className="data-table" aria-label="Columns not read as sensors">
            <thead>
              <tr>
                <th>Column</th>
                <th>Read as</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {ignored.map((column) => (
                <tr key={column.name}>
                  <td>{column.name}</td>
                  <td>
                    {column.role === "statistic"
                      ? `${column.statistic_type_id ?? "statistic"} of ${column.parent ?? "—"}`
                      : "ignored"}
                  </td>
                  <td className="muted">{column.reason ?? "Attached to its parent sensor."}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ) : null}

      {incomplete.length > 0 ? (
        <p className="status-error">
          Declare a measurement type and height for: {incomplete.map((row) => row.name).join(", ")} —
          or exclude them. Nothing is defaulted, because a wrong height is not detectable
          downstream.
        </p>
      ) : null}

      <RunButton
        label="Build data model"
        onClick={submit}
        disabled={!canBuild}
      />
    </section>
  );
}
