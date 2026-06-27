import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ResolvedTheme,
  THEME_STORAGE_KEY,
  ThemeContext,
  ThemePreference
} from "./themeContext";

const PREFERENCE_ORDER: ThemePreference[] = ["light", "dark", "system"];

function readStoredPreference(): ThemePreference {
  if (typeof window === "undefined") {
    return "system";
  }
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") {
    return stored;
  }
  return "system";
}

function systemTheme(): ResolvedTheme {
  if (typeof window === "undefined" || !window.matchMedia) {
    return "light";
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function resolveTheme(preference: ThemePreference, system: ResolvedTheme): ResolvedTheme {
  return preference === "system" ? system : preference;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(() => readStoredPreference());
  const [system, setSystem] = useState<ResolvedTheme>(() => systemTheme());

  // 跟随系统配色变化。
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return undefined;
    }
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (event: MediaQueryListEvent) => {
      setSystem(event.matches ? "dark" : "light");
    };
    media.addEventListener("change", handler);
    return () => media.removeEventListener("change", handler);
  }, []);

  const resolvedTheme = resolveTheme(preference, system);

  // 写入 <html data-theme>，并标记是否跟随系统供其它脚本读取。
  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    const root = document.documentElement;
    root.setAttribute("data-theme", resolvedTheme);
    root.dataset.themePreference = preference;
  }, [preference, resolvedTheme]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, next);
      } catch {
        // 本地存储不可用时忽略持久化。
      }
    }
  }, []);

  const cyclePreference = useCallback(() => {
    setPreferenceState((current) => {
      const index = PREFERENCE_ORDER.indexOf(current);
      const next = PREFERENCE_ORDER[(index + 1) % PREFERENCE_ORDER.length];
      if (typeof window !== "undefined") {
        try {
          window.localStorage.setItem(THEME_STORAGE_KEY, next);
        } catch {
          // 忽略。
        }
      }
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({ preference, resolvedTheme, setPreference, cyclePreference }),
    [preference, resolvedTheme, setPreference, cyclePreference]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
