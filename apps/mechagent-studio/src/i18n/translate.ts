import { english } from "./catalog";

export type Locale = "zh" | "en";
export const LOCALE_STORAGE_KEY = "mechagent.studio.locale";

const patterns = Object.entries(english)
  .filter(([key]) => /\{\d+\}/.test(key))
  .sort(
    ([a], [b]) =>
      b.replace(/\{\d+\}/g, "").length - a.replace(/\{\d+\}/g, "").length,
  )
  .map(([key, value]) => {
    const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const regex = new RegExp(`^${escaped.replace(/\\\{\d+\\\}/g, "(.+?)")}$`);
    return { regex, value };
  });

export function translate(
  locale: Locale,
  text: string,
  ...args: Array<string | number>
): string {
  let message = text;
  let values = args;
  if (locale === "en") {
    message = Object.hasOwn(english, text) ? english[text] : text;
    if (message === text && args.length === 0) {
      for (const pattern of patterns) {
        const match = text.match(pattern.regex);
        if (match) {
          message = pattern.value;
          values = match.slice(1);
          break;
        }
      }
    }
  }
  return message.replace(/\{(\d+)\}/g, (placeholder, index: string) => {
    const value = values[Number(index)];
    return value === undefined
      ? placeholder
      : typeof value === "string"
        ? translate(locale, value)
        : String(value);
  });
}
