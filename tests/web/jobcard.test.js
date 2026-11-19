import { test } from "node:test";
import assert from "node:assert/strict";
import { fakeDocument, findElement } from "./fake-dom.js";

globalThis.document = fakeDocument;
const { companyLogo } = await import("../../src/jobscout/web/js/jobcard.js");

const img = (el) => findElement(el, (n) => n.tagName === "IMG");
const fire = (el, type) => el.listeners[type].forEach((fn) => fn({ currentTarget: el }));

test("with no logo the square shows the company's initial", () => {
  const el = companyLogo({ company: "acme", company_logo: null });
  assert.equal(el.getAttribute("class"), "js-card__logo");
  assert.equal(el.getAttribute("aria-hidden"), "true");
  assert.equal(el.textContent, "A");
  assert.equal(img(el), null);
});

test("a logo URL adds a decorative image over the initial, shown once it loads", () => {
  const el = companyLogo({ company: "Acme", company_logo: "https://media.licdn.com/logo.png" }, "dt-logo");
  assert.equal(el.getAttribute("class"), "js-card__logo dt-logo");
  const logo = img(el);
  assert.equal(logo.getAttribute("src"), "https://media.licdn.com/logo.png");
  assert.equal(logo.getAttribute("alt"), "");
  assert.equal(logo.getAttribute("referrerpolicy"), "no-referrer");
  assert.equal(logo.getAttribute("loading"), "lazy");
  // The initial stays underneath until the image has loaded.
  assert.equal(el.textContent, "A");
  assert.equal(logo.getAttribute("data-loaded"), null);
  fire(logo, "load");
  assert.equal(logo.getAttribute("data-loaded"), "");
});

test("a logo that fails to load hides itself, leaving the initial", () => {
  const logo = img(companyLogo({ company: "Acme", company_logo: "https://media.licdn.com/gone.png" }));
  fire(logo, "error");
  assert.equal(logo.getAttribute("hidden"), "");
});

test("only https logos are loaded", () => {
  for (const url of ["http://x.example/logo.png", "javascript:alert(1)", "data:image/png;base64,AA", "nope", 12]) {
    assert.equal(img(companyLogo({ company: "Acme", company_logo: url })), null, String(url));
  }
});
