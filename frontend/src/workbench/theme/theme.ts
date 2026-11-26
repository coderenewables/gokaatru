import { useCallback, useEffect, useState } from "react";
import { readStored, writeStored } from "../storage";

export type Theme = "light" | "dark";
const KEY = "gk-workbench-theme";

export function storedTheme(): Theme {
  return readStored(KEY) === "dark" ? "dark" : "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

/** Light first (owner, 2026-11-17); the choice is remembered per viewer. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  useEffect(() => {
    applyTheme(theme);
    writeStored(KEY, theme);
  }, [theme]);
  const toggle = useCallback(() => setTheme((current) => (current === "light" ? "dark" : "light")), []);
  return [theme, toggle];
}

/** The theme the page shows now, followed as the header switches it: for a library that takes
 * the theme as a prop (React Flow) rather than from the tokens. */
export function useAppliedTheme(): Theme {
  const read = (): Theme => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  const [theme, setTheme] = useState<Theme>(read);
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(read()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return theme;
}
