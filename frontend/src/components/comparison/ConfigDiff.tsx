import type { WorkflowCompareDiffEntry } from "../../lib/types";

type ConfigDiffProps = {
  configDiff: Record<string, WorkflowCompareDiffEntry[]>;
};

function renderValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value);
}

export function ConfigDiff({ configDiff }: ConfigDiffProps) {
  const pairKeys = Object.keys(configDiff);
  if (pairKeys.length === 0) {
    return <p className="muted-text">No config differences for selected branches.</p>;
  }

  return (
    <div className="workflow-compare-diff-stack">
      {pairKeys.map((pairKey) => {
        const entries = configDiff[pairKey] ?? [];
        return (
          <section key={pairKey} className="workflow-compare-diff-card">
            <h3>{pairKey}</h3>
            {entries.length === 0 ? <p className="muted-text">No differing keys.</p> : null}
            {entries.length > 0 ? (
              <div className="table-wrap">
                <table className="data-table workflow-compare-table">
                  <thead>
                    <tr>
                      <th>Key</th>
                      <th>A</th>
                      <th>B</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((entry) => (
                      <tr key={`${pairKey}-${entry.key}`}>
                        <td>{entry.key}</td>
                        <td>{renderValue(entry.a)}</td>
                        <td>{renderValue(entry.b)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
