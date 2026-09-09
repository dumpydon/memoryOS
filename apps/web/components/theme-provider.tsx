"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
} from "react";

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

type ThemeContextValue = {
  preference: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
};

const STORAGE_KEY = "memoryos-appearance";
const ThemeContext = createContext<ThemeContextValue | null>(null);
const preferenceListeners = new Set<() => void>();
let volatilePreference: ThemePreference | null = null;

function readStoredPreference(): ThemePreference {
  if (volatilePreference) return volatilePreference;
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" || value === "system"
      ? value
      : "system";
  } catch {
    return "system";
  }
}

function getSystemTheme(): ResolvedTheme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function subscribeToPreference(listener: () => void) {
  preferenceListeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) {
      volatilePreference = null;
      listener();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    preferenceListeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

function getPreferenceSnapshot(): ThemePreference {
  return typeof window === "undefined" ? "system" : readStoredPreference();
}

function subscribeToSystemTheme(listener: () => void) {
  const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
  mediaQuery.addEventListener("change", listener);
  return () => mediaQuery.removeEventListener("change", listener);
}

function getSystemThemeSnapshot(): ResolvedTheme {
  return typeof window === "undefined" ? "light" : getSystemTheme();
}

function applyTheme(theme: ResolvedTheme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const preference = useSyncExternalStore(
    subscribeToPreference,
    getPreferenceSnapshot,
    () => "system" as ThemePreference,
  );
  const systemTheme = useSyncExternalStore(
    subscribeToSystemTheme,
    getSystemThemeSnapshot,
    () => "light" as ResolvedTheme,
  );
  const resolvedTheme = preference === "system" ? systemTheme : preference;
  const hasAppliedInitialTheme = useRef(false);

  useEffect(() => {
    if (!hasAppliedInitialTheme.current) {
      hasAppliedInitialTheme.current = true;
      if (document.documentElement.dataset.theme) return;
    }
    applyTheme(resolvedTheme);
  }, [resolvedTheme]);

  const setPreference = useCallback((nextPreference: ThemePreference) => {
    volatilePreference = nextPreference;
    try {
      window.localStorage.setItem(STORAGE_KEY, nextPreference);
    } catch {
      // Private browsing or a restricted storage context should not block theming.
    }
    preferenceListeners.forEach((listener) => listener());
  }, []);

  const value = useMemo(
    () => ({ preference, resolvedTheme, setPreference }),
    [preference, resolvedTheme, setPreference],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside ThemeProvider");
  return value;
}
