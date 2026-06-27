import { createContext } from "react";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export interface ThemeContextValue {
  /** 用户选择：明 / 暗 / 跟随系统。 */
  preference: ThemePreference;
  /** 实际生效主题。 */
  resolvedTheme: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
  /** 在 明 -> 暗 -> 跟随系统 之间循环。 */
  cyclePreference: () => void;
}

export const THEME_STORAGE_KEY = "mechagent.studio.theme";

export const ThemeContext = createContext<ThemeContextValue | null>(null);
