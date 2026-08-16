import { enUS } from "./en-US";
import { jaJP } from "./ja-JP";
import { zhTW } from "./zh-TW";
import type { AppLocale } from "../locales";

type MessageTree = {
  [key: string]: string | MessageTree;
};

export type TranslationValues = Record<string, string | number | null | undefined>;
export type TranslationFunction = (
  key: string,
  values?: TranslationValues
) => string;

export const messages: Record<AppLocale, MessageTree> = {
  "zh-TW": zhTW,
  "en-US": enUS,
  "ja-JP": jaJP,
};

function readMessage(tree: MessageTree, key: string): string | null {
  let current: string | MessageTree = tree;
  const parts = key.split(".");

  for (let index = 0; index < parts.length; index += 1) {
    if (typeof current === "string") return null;

    const nextValue: string | MessageTree | undefined = current[parts[index]];
    if (nextValue !== undefined) {
      current = nextValue;
      continue;
    }

    const dottedLeaf: string | MessageTree | undefined =
      current[parts.slice(index).join(".")];
    return typeof dottedLeaf === "string" ? dottedLeaf : null;
  }

  return typeof current === "string" ? current : null;
}

function interpolate(message: string, values: TranslationValues | undefined) {
  if (!values) return message;

  return message.replace(/\{(\w+)\}/g, (match, key) => {
    const value = values[key];
    return value === null || value === undefined ? match : String(value);
  });
}

export function translate(
  locale: AppLocale,
  key: string,
  values?: TranslationValues
) {
  const localeMessage = readMessage(messages[locale], key);
  const fallbackMessage = readMessage(messages["zh-TW"], key);
  return interpolate(localeMessage ?? fallbackMessage ?? key, values);
}
