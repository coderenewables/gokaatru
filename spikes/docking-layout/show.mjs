import { readFileSync } from "node:fs";
const j = JSON.parse(readFileSync(process.argv[2], "utf8"));
const drop = new Set(["after", "before", "trail", "deltas", "jsonPreview"]);
console.log(JSON.stringify(j.results, (k, v) => (drop.has(k) && process.argv[3] !== "all" ? undefined : v)));
