export type LooseJsonResult =
  | { ok: true; value: unknown; recovered: boolean }
  | { ok: false; error: string };

const VALID_SIMPLE_ESCAPE_NEXT = new Set(["\"", "\\", "/", "b", "f", "n", "r", "t"]);

function isHexDigit(char: string | undefined): boolean {
  return char !== undefined && /[0-9a-f]/i.test(char);
}

function isValidEscapeSequence(input: string, index: number): boolean {
  const next = input[index + 1];
  if (next === undefined) {
    return false;
  }
  if (VALID_SIMPLE_ESCAPE_NEXT.has(next)) {
    return true;
  }
  if (next !== "u") {
    return false;
  }
  return [input[index + 2], input[index + 3], input[index + 4], input[index + 5]].every(isHexDigit);
}

function escapeWindowsPaths(input: string): string {
  let out = "";
  let inString = false;
  for (let i = 0; i < input.length; i += 1) {
    const ch = input[i];
    if (ch === "\"" && (i === 0 || input[i - 1] !== "\\")) {
      inString = !inString;
      out += ch;
      continue;
    }
    if (inString && ch === "\\") {
      if (!isValidEscapeSequence(input, i)) {
        out += "\\\\";
        continue;
      }
    }
    out += ch;
  }
  return out;
}

export function parseLooseJson(input: string): LooseJsonResult {
  const trimmed = input.trim();
  if (trimmed === "") {
    return { ok: true, value: {}, recovered: false };
  }
  try {
    return { ok: true, value: JSON.parse(trimmed), recovered: false };
  } catch (firstError) {
    try {
      const repaired = escapeWindowsPaths(trimmed);
      if (repaired !== trimmed) {
        return { ok: true, value: JSON.parse(repaired), recovered: true };
      }
    } catch {
      // fall through to the original error
    }
    const message = firstError instanceof Error ? firstError.message : String(firstError);
    return { ok: false, error: message };
  }
}
