import { readdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// The folders earlier runs' backends wrote their sessions and projects into; this run's is
// left alone (playwright.config.ts names it in E2E_RUN).
export default function globalSetup(): void {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", ".e2e-data");
  let entries: string[];
  try {
    entries = readdirSync(root);
  } catch {
    return;
  }
  for (const entry of entries) {
    if (entry === process.env.E2E_RUN) continue;
    try {
      rmSync(path.join(root, entry), { recursive: true, force: true });
    } catch {
      // A folder a stopped server still holds open is removed by a later run.
    }
  }
}
