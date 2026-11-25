import { useEffect, useMemo, useState } from "react";

import { OperationForm } from "../forms/OperationForm";
import { bodyOf, fieldsOf, inputsOf } from "../forms/schema";
import { useSensors } from "../sensors";
import { useCampaign } from "../shell/context";
import { STATUS_LABELS } from "./graph";
import { type OperationInfo, titleOf, useOperations } from "./operations";
import { useOrder, useRunSteps } from "./order";
import { type Step, type StepRun, usePipeline } from "./store";
import "./model.css";

const SOURCES = ["era5", "merra2"];

function shown(value: unknown): string {
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toPrecision(6).replace(/\.?0+$/, "");
  if (value === null || value === undefined) return "—";
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

/** A step's result: its disclosure fields first (decisions/0004: every default or fallback that
 * moved a number is said), then its other top-level figures, the rest folded away. */
function Result({ run, operation }: { run: StepRun; operation: OperationInfo }) {
  if (run.error) {
    return (
      <p role="alert" className="gk-warning">
        Refused: {run.error}
      </p>
    );
  }
  const result = (run.result ?? {}) as Record<string, unknown>;
  const disclosed = operation.disclosure.filter((field) => field.split(".")[0] in result);
  const scalars = Object.entries(result).filter(
    ([key, value]) => !disclosed.includes(key) && (value === null || typeof value !== "object"),
  );
  const nested = Object.entries(result).filter(([key, value]) => !disclosed.includes(key) && value !== null && typeof value === "object");
  return (
    <div className="gk-result">
      {disclosed.length > 0 && (
        <dl className="gk-facts gk-disclosed" aria-label="Disclosed">
          {disclosed.map((field) => (
            <div key={field}>
              <dt>{field.replace(/_/g, " ")}</dt>
              <dd>
                {(() => {
                  const value = result[field.split(".")[0]];
                  return value !== null && typeof value === "object" ? <pre tabIndex={0}>{JSON.stringify(value, null, 2)}</pre> : shown(value);
                })()}
              </dd>
            </div>
          ))}
        </dl>
      )}
      <dl className="gk-facts">
        {scalars.map(([key, value]) => (
          <div key={key}>
            <dt>{key.replace(/_/g, " ")}</dt>
            <dd>{shown(value)}</dd>
          </div>
        ))}
      </dl>
      {nested.map(([key, value]) => (
        <details key={key}>
          <summary>{key.replace(/_/g, " ")}</summary>
          <pre tabIndex={0}>{JSON.stringify(value, null, 2)}</pre>
        </details>
      ))}
    </div>
  );
}

function StepForm({ step, operation, serverErrors }: { step: Step; operation: OperationInfo; serverErrors: string[] }) {
  const { sessionId } = useCampaign();
  const sensors = useSensors(sessionId);
  const setParameters = usePipeline((state) => state.setParameters);
  const fields = useMemo(() => fieldsOf(operation.parameters), [operation]);
  const [inputs, setInputs] = useState(() => inputsOf(fields, step.parameters));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const change = (name: string, value: string | boolean) => {
    const next = { ...inputs, [name]: value };
    setInputs(next);
    const { body, errors: found } = bodyOf(fields, next);
    setErrors(found);
    if (Object.keys(found).length === 0) setParameters(step.id, body);
  };
  return (
    <>
      <OperationForm
        fields={fields}
        inputs={inputs}
        onChange={change}
        errors={errors}
        channels={(sensors.data ?? []).map((row) => row.name)}
        sources={SOURCES}
      />
      {serverErrors.length > 0 && (
        <ul className="gk-field-error" aria-label="The server refuses these parameters">
          {serverErrors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}
    </>
  );
}

/** The selected step (plan §3.3 "Model": edits parameters in a generated form): what it is,
 * whether its result is current and why not, its parameters, and its last result. */
export function StepPanel() {
  const { sessionId } = useCampaign();
  const { steps, selected, runs, remove, open } = usePipeline();
  useEffect(() => open(sessionId), [open, sessionId]);
  const operations = useOperations();
  const order = useOrder(sessionId, steps);
  const { run, running } = useRunSteps(sessionId);
  const step = steps.find((candidate) => candidate.id === selected);
  const operation = operations.data?.find((candidate) => candidate.name === step?.operation);
  if (!step || !operation) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>Select a step on the pipeline to set its parameters and see its result.</p>
      </div>
    );
  }
  const report = order.data?.steps[step.id];
  const last = runs[step.id];
  return (
    <div className="gk-panel gk-step-panel">
      <h2>{titleOf(step.operation)}</h2>
      <p className="gk-muted">{operation.description.replace(/``/g, "")}</p>
      {report && (
        <p>
          <span className="gk-step-badge" data-status={report.status}>
            {STATUS_LABELS[report.status] ?? report.status}
          </span>{" "}
          {report.reason}
          {report.waiting_on?.length ? ` Waits on ${report.waiting_on.join(", ")}.` : ""}
        </p>
      )}
      {operation.standards.length > 0 && <p className="gk-muted">{operation.standards.join(" ")}</p>}
      <StepForm key={step.id} step={step} operation={operation} serverErrors={report?.errors ?? []} />
      <div className="gk-actions">
        <button type="button" className="gk-button gk-button-primary" disabled={running !== null} onClick={() => run([step.id])}>
          {running === step.id ? "Running…" : "Run this step"}
        </button>
        <button type="button" className="gk-button" onClick={() => remove(step.id)}>
          Remove from the pipeline
        </button>
      </div>
      {last && <Result run={last} operation={operation} />}
    </div>
  );
}
