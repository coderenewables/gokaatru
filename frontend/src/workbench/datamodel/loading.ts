import type { QueryClient } from "@tanstack/react-query";
import { create } from "zustand";

import { SESSION_HEADER } from "../../api/client";
import { refusal } from "../api";
import { invalidateCampaign } from "../invalidate";

// Loading a campaign's files (plan §3.3 "Data loading"): a table is the timeseries, a JSON
// document the data model. What the server refuses is shown in its own words.

export type FileKind = "timeseries" | "datamodel";

export function classify(name: string): FileKind | null {
  const extension = name.toLowerCase().match(/\.([a-z0-9]+)$/)?.[1];
  if (extension === "csv" || extension === "txt" || extension === "xlsx") return "timeseries";
  if (extension === "json") return "datamodel";
  return null;
}

/** The order the files are sent in: the records first, so a data model dropped with them
 * finds its columns. */
export function inLoadOrder(files: File[]): File[] {
  const rank = (file: File) => (classify(file.name) === "timeseries" ? 0 : 1);
  return [...files].sort((a, b) => rank(a) - rank(b));
}

interface LoadStatus {
  busy: boolean;
  /** One line per file: loaded or refused, in the server's words. */
  lines: Array<{ file: string; ok: boolean; text: string }>;
  clear: () => void;
}

export const useLoadStatus = create<LoadStatus>((set) => ({
  busy: false,
  lines: [],
  clear: () => set({ lines: [] }),
}));

async function send(sessionId: string, kind: FileKind, file: File): Promise<string> {
  const body = new FormData();
  body.append("file", file, file.name);
  const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/uploads/${kind}`, {
    method: "POST",
    headers: { [SESSION_HEADER]: sessionId },
    body,
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(refusal(payload));
  return kind === "timeseries" ? "Loaded as the timeseries." : "Loaded as the data model.";
}

export async function loadFiles(client: QueryClient, sessionId: string, files: File[]): Promise<void> {
  const status = useLoadStatus.setState;
  status({ busy: true, lines: [] });
  const lines: LoadStatus["lines"] = [];
  for (const file of inLoadOrder(files)) {
    const kind = classify(file.name);
    if (kind === null) {
      lines.push({ file: file.name, ok: false, text: "Not a table (.csv, .txt, .xlsx) or a data model (.json)." });
      continue;
    }
    try {
      lines.push({ file: file.name, ok: true, text: await send(sessionId, kind, file) });
    } catch (error) {
      lines.push({ file: file.name, ok: false, text: error instanceof Error ? error.message : String(error) });
    }
    await invalidateCampaign(client, sessionId);
  }
  status({ busy: false, lines });
}
