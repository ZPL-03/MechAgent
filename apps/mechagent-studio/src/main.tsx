import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./theme/tokens.css";
import "./theme/themes.css";
import "./theme/base.css";
import "./styles.css";
import { ThemeProvider } from "./theme/ThemeProvider";
import { App } from "./App";
import { LocaleProvider } from "./i18n/LocaleProvider";

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <ThemeProvider>
      <LocaleProvider>
        <App />
      </LocaleProvider>
    </ThemeProvider>
  </StrictMode>,
);
