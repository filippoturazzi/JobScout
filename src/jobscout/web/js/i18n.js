// Copy lives in locales/<code>.json. Plural-free by design ("{n} jobs").

let messages = {};
let locale = "en";
const warned = new Set();

export async function loadLocale(code) {
  const res = await fetch(`/static/locales/${code}.json`);
  if (!res.ok) throw new Error(`Could not load locale ${code}`);
  messages = await res.json();
  locale = code;
  warned.clear();
}

export function currentLocale() {
  return locale;
}

export function t(key, params) {
  const text = messages[key];
  if (typeof text !== "string") {
    if (!warned.has(key)) {
      warned.add(key);
      console.warn(`Missing translation: ${key}`);
    }
    return key;
  }
  return text.replace(/\{(\w+)\}/g, (whole, name) =>
    params && name in params ? String(params[name]) : whole,
  );
}
