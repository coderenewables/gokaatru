// Per-viewer conveniences only (the layout, the theme): browser storage can be missing or
// refuse a write, so every access is guarded and a failure means "use the default".

export function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // A refused write keeps the current view; nothing depends on it surviving.
  }
}
