import { test } from "node:test";
import assert from "node:assert/strict";

const { editKind, answerFor, initialSelection } = await import("../../src/jobscout/web/js/editmodal.js");

const sel = (over = {}) => ({ option: null, picked: [], any: false, text: "", ...over });
const role = { id: "role", multi: false, typed: true, options: [] };
const modes = { id: "work_modes", multi: true, options: [{ choice: "remote" }, { choice: "hybrid" }, { choice: "onsite" }, { choice: "any" }] };
const level = { id: "level", multi: false, options: [{ choice: "intern" }, { choice: "junior" }, { choice: "mid" }, { choice: "senior" }] };
const location = { id: "location", multi: false, options: [{ choice: "country", value: "Brazil" }, { choice: "anywhere" }, { choice: "abroad", value: "Brazil" }, { choice: "other" }] };
const city = { id: "city", multi: false, options: [{ choice: "anywhere", value: "Brazil" }, { choice: "other" }] };

const skills = { id: "skills", multi: true, options: [{ choice: "skill", value: "python" }] };

test("role and skills are typed, work mode is multi, the rest single", () => {
  assert.equal(editKind(role), "text");
  assert.equal(editKind(skills), "text");
  assert.equal(editKind(modes), "multi");
  assert.equal(editKind(level), "single");
  assert.equal(editKind(city), "single");
});

test("a typed role sends one value, trimmed; blank sends nothing", () => {
  assert.deepEqual(answerFor(role, sel({ text: "  data engineer " })), { choice: "role", values: ["data engineer"] });
  assert.equal(answerFor(role, sel({ text: "  " })), null);
  assert.equal(answerFor(role, sel({ text: " , ," })), null);
});

test("multi sends pick, or any, or nothing when empty", () => {
  assert.deepEqual(answerFor(modes, sel({ picked: ["remote", "hybrid"] })), { choice: "pick", values: ["remote", "hybrid"] });
  assert.deepEqual(answerFor(modes, sel({ any: true })), { choice: "any", values: [] });
  assert.equal(answerFor(modes, sel()), null);
});

test("single sends the option's answer; 'other' sends the typed place", () => {
  assert.deepEqual(answerFor(level, sel({ option: { choice: "junior" } })), { choice: "junior", values: [] });
  assert.deepEqual(answerFor(location, sel({ option: { choice: "country", value: "Brazil" } })), { choice: "country", values: ["Brazil"] });
  assert.deepEqual(answerFor(city, sel({ option: { choice: "other" }, text: " Recife " })), { choice: "city", values: ["Recife"] });
  assert.deepEqual(answerFor(location, sel({ option: { choice: "other" }, text: "Chile" })), { choice: "country", values: ["Chile"] });
  assert.equal(answerFor(city, sel({ option: { choice: "other" }, text: " " })), null);
  assert.equal(answerFor(level, sel()), null);
});

test("the modal opens on the current answer", () => {
  assert.equal(initialSelection(role, undefined, { terms: ["ai engineer", "python"] }).text, "ai engineer, python");
  assert.deepEqual(initialSelection(modes, { choice: "pick", values: ["remote"] }, {}).picked, ["remote"]);
  assert.equal(initialSelection(modes, { choice: "any", values: [] }, {}).any, true);
  assert.equal(initialSelection(level, { choice: "junior", values: [] }, {}).option.choice, "junior");
  assert.equal(initialSelection(location, { choice: "country", values: ["Brazil"] }, {}).option.value, "Brazil");
  const typed = initialSelection(city, { choice: "city", values: ["Recife"] }, {});
  assert.equal(typed.option.choice, "other");
  assert.equal(typed.text, "Recife");
  assert.equal(initialSelection(level, undefined, {}).option, null);
});

test("with no answer, the modal opens on what the summary shows", () => {
  assert.equal(initialSelection(level, undefined, { level: "junior" }).option.choice, "junior");
  assert.deepEqual(initialSelection(modes, undefined, { work_modes: ["remote"] }).picked, ["remote"]);
  assert.equal(initialSelection(skills, undefined, { skills: ["python", "sql"] }).text, "python, sql");
  assert.equal(initialSelection(level, undefined, { level: null }).option, null);
});

test("while Save is in flight the modal cannot be closed", async () => {
  const { fakeDocument, findElement } = await import("./fake-dom.js");
  globalThis.document = fakeDocument;
  const proto = Object.getPrototypeOf(fakeDocument.createElement("div"));
  proto.showModal ||= function () { this.open = true; };
  proto.close ||= function () { this.open = false; (this.listeners.close || []).forEach((fn) => fn({})); };
  proto.remove ||= function () {};
  proto.removeAttribute ||= function (name) { delete this.attributes[name]; };
  fakeDocument.body ||= fakeDocument.createElement("body");
  const { openEditModal } = await import("../../src/jobscout/web/js/editmodal.js");
  let resolve;
  openEditModal(role, { summary: { terms: ["qa"] }, onSave: () => new Promise((r) => { resolve = r; }) });
  const dialog = fakeDocument.body.childNodes[fakeDocument.body.childNodes.length - 1];
  const form = findElement(dialog, (el) => el.tagName === "FORM");
  const cancel = findElement(dialog, (el) => el.tagName === "BUTTON" && el.getAttribute("type") === "button");
  form.listeners.submit[0]({ preventDefault() {} });
  assert.notEqual(cancel.getAttribute("disabled"), null);
  cancel.listeners.click[0]({});
  dialog.listeners.click[0]({ target: dialog });
  let prevented = false;
  dialog.listeners.cancel[0]({ preventDefault() { prevented = true; } });
  assert.equal(dialog.open, true);
  assert.equal(prevented, true);
  resolve();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(cancel.getAttribute("disabled"), null);
});

test("typed skills are split on commas; an empty field clears them", () => {
  assert.deepEqual(answerFor(skills, sel({ text: " Python, django ,, python, SQL " })), { choice: "pick", values: ["Python", "django", "SQL"] });
  assert.deepEqual(answerFor(skills, sel({ text: "  " })), { choice: "pick", values: [] });
});

test("the skills field opens on the answered skills", () => {
  assert.equal(initialSelection(skills, { choice: "pick", values: ["go", "rust"] }, { skills: ["python"] }).text, "go, rust");
});
