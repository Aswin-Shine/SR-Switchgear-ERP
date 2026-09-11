import { useEffect, useState } from "react";
import { useMediaQuery } from "./useMediaQuery";

export type Theme = "light" | "dark";

const STORAGE_KEY = "sr-erp-theme";

function readStoredTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

/**
 * Resolved light/dark theme plus a toggle. The flash-free first paint comes from
 * index.html's inline script (same storage key, same data-theme attribute) — this hook
 * keeps React state in sync with it, and tracks the OS preference live for as long as
 * no explicit choice has been stored. Once toggled, the explicit choice wins for good.
 */
export function useTheme(): [Theme, () => void] {
  const systemPrefersDark = useMediaQuery("(prefers-color-scheme: dark)");
  const [stored, setStored] = useState<Theme | null>(readStoredTheme);

  const theme: Theme = stored ?? (systemPrefersDark ? "dark" : "light");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage disabled (private mode / IT policy) — theme still applies for this tab.
    }
    setStored(next);
  };

  return [theme, toggle];
}
