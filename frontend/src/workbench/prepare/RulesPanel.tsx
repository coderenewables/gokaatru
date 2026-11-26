import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { api, unwrap } from "../api";
import { OperationForm } from "../forms/OperationForm";
import { invalidateCampaign } from "../invalidate";
import { PreviewSummary } from "../inspector/FlagSection";
import { useSensors } from "../sensors";
import { useCampaign } from "../shell/context";
import { formRules, needsDates, ruleFields, ruleInputs, ruleRequest, takesDates, type RuleInfo } from "./rules";
import "./prepare.css";

const path = (sessionId: string) => ({ params: { path: { session_id: sessionId } } });

/** The cleaning rules as forms (decisions/0015.13): choose a rule and the sensor it cleans,
 * fill its parameters, preview what would be set missing, then apply. One application is one
 * log entry and one undo step; Ctrl+Z undoes it like any other change. */
export function RulesPanel() {
  const { sessionId } = useCampaign();
  const client = useQueryClient();
  const sensors = useSensors(sessionId);
  const list = useQuery({
    queryKey: ["cleaning-rules", sessionId],
    queryFn: async () => unwrap(await api.POST("/api/sessions/{session_id}/operations/list_cleaning_rules", { ...path(sessionId), body: {} })),
    retry: false,
  });
  const rules = useMemo<RuleInfo[]>(() => formRules(list.data?.rules ?? []), [list.data]);

  const [ruleName, setRuleName] = useState("");
  const rule = rules.find((item) => item.name === ruleName) ?? rules[0];
  const fields = useMemo(() => (rule ? ruleFields(rule) : []), [rule]);
  const [inputs, setInputs] = useState<Record<string, string | boolean>>({});
  const [sensor, setSensor] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [applied, setApplied] = useState<string | null>(null);

  // Another rule means another set of parameters.
  const ruleKey = rule?.name ?? "";
  useEffect(() => {
    setInputs(ruleInputs(fields));
    setApplied(null);
  }, [ruleKey, fields]);

  const channels = (sensors.data ?? []).map((row) => row.name);
  const { request, errors } = rule
    ? ruleRequest(rule, sensor, fields, inputs, { start, end })
    : { request: null, errors: {} as Record<string, string> };
  const requestKey = JSON.stringify(request);

  const preview = useMutation({
    mutationFn: async () => {
      if (!request) throw new Error("The rule is not complete");
      return unwrap(await api.POST("/api/sessions/{session_id}/operations/apply_cleaning_rule/preview", { ...path(sessionId), body: request }));
    },
  });
  const apply = useMutation({
    mutationFn: async () => {
      if (!request) throw new Error("The rule is not complete");
      return unwrap(await api.POST("/api/sessions/{session_id}/operations/apply_cleaning_rule", { ...path(sessionId), body: request }));
    },
    onSuccess: async (result) => {
      setApplied(`${rule?.name.replace(/_/g, " ")} on ${sensor}: ${result.records_affected} values set missing`);
      preview.reset();
      await invalidateCampaign(client, sessionId);
    },
  });

  // Any edit makes the shown preview stale: it described another request.
  const { reset: resetPreview } = preview;
  const { reset: resetApply } = apply;
  useEffect(() => {
    resetPreview();
    resetApply();
  }, [requestKey, resetPreview, resetApply]);

  if (list.error) return <div className="gk-panel"><p role="alert">{list.error.message}</p></div>;
  if (!rule) return <div className="gk-panel gk-panel-empty"><p>Loading the cleaning rules.</p></div>;

  const refused = preview.error ?? apply.error;
  return (
    <div className="gk-panel gk-rules" tabIndex={0}>
      <section aria-labelledby="gk-rules-heading" className="gk-rules-form">
        <h2 id="gk-rules-heading">Clean with a rule</h2>
        <label className="gk-field">
          <span>Rule</span>
          <select value={rule.name} onChange={(event) => setRuleName(event.target.value)}>
            {rules.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </label>
        <label className="gk-field">
          <span>Sensor</span>
          <select value={sensor} onChange={(event) => setSensor(event.target.value)}>
            <option value="">(choose)</option>
            {channels.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <OperationForm
          fields={fields}
          inputs={inputs}
          onChange={(name, value) => setInputs((current) => ({ ...current, [name]: value }))}
          errors={errors}
          channels={channels}
        />
        {takesDates(rule.name) && (
          <div className="gk-rules-dates">
            <label className="gk-field">
              <span>{needsDates(rule.name) ? "Start date (needed)" : "Start date (optional)"}</span>
              <input type="date" value={start} onChange={(event) => setStart(event.target.value)} />
            </label>
            <label className="gk-field">
              <span>{needsDates(rule.name) ? "End date (needed)" : "End date (optional)"}</span>
              <input type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
            </label>
          </div>
        )}
        <div className="gk-actions">
          <button type="button" className="gk-button" disabled={!request || preview.isPending} onClick={() => preview.mutate()}>
            Preview
          </button>
          <button
            type="button"
            className="gk-button gk-button-primary"
            disabled={!request || !preview.data || apply.isPending}
            title={preview.data ? undefined : "Preview first: it shows what would change"}
            onClick={() => apply.mutate()}
          >
            Apply rule
          </button>
        </div>
        {preview.data && <PreviewSummary preview={preview.data} />}
        {refused && <p role="alert">{refused.message}</p>}
        {applied && <p role="status">{applied}</p>}
        <p className="gk-muted">{list.data?.order_note}</p>
      </section>
    </div>
  );
}
