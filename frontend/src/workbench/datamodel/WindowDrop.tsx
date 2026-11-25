import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { loadFiles, useLoadStatus } from "./loading";
import "./datamodel.css";

const carriesFiles = (event: DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes("Files");

/** Files dropped anywhere on the window load into the open campaign, with an overlay naming
 * it while they are over the window, and the outcome of each file below. */
export function WindowDrop({ sessionId, campaignName }: { sessionId: string; campaignName: string }) {
  const client = useQueryClient();
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  const { busy, lines, clear } = useLoadStatus();

  useEffect(() => {
    const enter = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      depth.current += 1;
      setOver(true);
    };
    const leave = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setOver(false);
    };
    const hover = (event: DragEvent) => {
      if (carriesFiles(event)) event.preventDefault();
    };
    const drop = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth.current = 0;
      setOver(false);
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length > 0) void loadFiles(client, sessionId, files);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", hover);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", hover);
      window.removeEventListener("drop", drop);
    };
  }, [client, sessionId]);

  return (
    <>
      {over && (
        <div className="gk-drop-overlay" aria-hidden="true">
          <p>Drop to load into {campaignName}</p>
        </div>
      )}
      <div className="gk-load-status" role="status" aria-live="polite">
        {busy && <p>Loading…</p>}
        {!busy && lines.length > 0 && (
          <>
            <ul>
              {lines.map((line) => (
                <li key={line.file} className={line.ok ? undefined : "gk-load-refused"}>
                  <strong>{line.file}</strong> {line.ok ? "" : "was refused: "}
                  {line.text}
                </li>
              ))}
            </ul>
            <button type="button" onClick={clear}>
              Dismiss
            </button>
          </>
        )}
      </div>
    </>
  );
}
