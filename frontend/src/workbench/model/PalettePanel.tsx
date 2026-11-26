import { useDraggable } from "@dnd-kit/core";

import type { MethodDrag } from "../dnd";
import { type OperationInfo, STAGE_LABELS, paletteOf, titleOf, useOperations } from "./operations";
import { usePipeline } from "./store";
import "./model.css";

function Method({ operation }: { operation: OperationInfo }) {
  const drag: MethodDrag = { kind: "method", operation: operation.name };
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `method-${operation.name}`, data: drag });
  const add = usePipeline((state) => state.add);
  return (
    <li className="gk-method" data-dragging={isDragging || undefined}>
      <span ref={setNodeRef} className="gk-method-name" title={operation.description.replace(/``/g, "")} {...listeners} {...attributes}>
        {titleOf(operation.name)}
        {operation.effect === "read" && <span className="gk-method-read"> (reads only)</span>}
      </span>
      <button
        type="button"
        className="gk-icon-button"
        aria-label={`Add ${titleOf(operation.name)} to the pipeline`}
        onClick={() => add(operation.name)}
      >
        +
      </button>
    </li>
  );
}

/** The methods a pipeline step can be, by stage (plan §3.3 "Model": drag one onto the
 * pipeline; its button adds it from the keyboard). */
export function PalettePanel() {
  const operations = useOperations();
  if (operations.isError) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>{operations.error.message}</p>
      </div>
    );
  }
  const stages = paletteOf(operations.data ?? []);
  return (
    <div className="gk-panel gk-palette-panel" tabIndex={0}>
      {[...stages].map(([stage, listed]) => (
        <section key={stage} aria-labelledby={`stage-${stage}`}>
          <h2 id={`stage-${stage}`}>{STAGE_LABELS[stage] ?? stage}</h2>
          <ul>
            {listed.map((operation) => (
              <Method key={operation.name} operation={operation} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
