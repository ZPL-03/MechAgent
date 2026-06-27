import { useContext } from "react";
import { ThemeContext, ThemeContextValue } from "./themeContext";

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) {
    throw new Error("useTheme 必须在 ThemeProvider 内使用。");
  }
  return value;
}
