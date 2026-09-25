const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "static", "index.html"), "utf8");
const app = fs.readFileSync(path.join(root, "static", "app.js"), "utf8");
const ui = fs.readFileSync(path.join(root, "static", "ui.js"), "utf8");

function ids(source) {
  return [...source.matchAll(/\bid=["']([^"']+)["']/g)].map((match) => match[1]);
}

test("redesigned shell has distinct primary views", () => {
  const pages = ["dashboard", "live", "cameras", "recordings", "events", "settings"];
  for (const page of pages) {
    assert.match(html, new RegExp(`data-page=["']${page}["']`));
    assert.match(html, new RegExp(`data-page-target=["']${page}["']`));
  }
});

test("index keeps every DOM id used by the existing app controller", () => {
  const htmlIds = new Set(ids(html));
  const appIds = [
    ...app.matchAll(/\$\(["']([^"']+)["']\)/g),
  ].map((match) => match[1]);

  const missing = [...new Set(appIds)].filter((id) => !htmlIds.has(id));
  assert.deepEqual(missing, []);
});

test("index does not contain duplicate ids", () => {
  const all = ids(html);
  const duplicates = all.filter((id, index) => all.indexOf(id) !== index);
  assert.deepEqual([...new Set(duplicates)], []);
});

test("camera stream credentials are masked by default", () => {
  assert.match(
    html,
    /<input[^>]+id=["']rtspUrl["'][^>]+type=["']password["']|<input[^>]+type=["']password["'][^>]+id=["']rtspUrl["']/
  );
  assert.match(html, /id=["']toggleRtspVisibility["']/);
});

test("multi-camera live wall and camera picker are present", () => {
  assert.match(html, /id=["']liveWall["']/);
  assert.match(html, /id=["']wallCameraPicker["']/);
  assert.match(html, /id=["']wallLayout["']/);
});

test("frontend scripts parse as JavaScript", () => {
  assert.doesNotThrow(() => new vm.Script(app, { filename: "app.js" }));
  assert.doesNotThrow(() => new vm.Script(ui, { filename: "ui.js" }));
});

test("ui controller is loaded after the existing app controller", () => {
  const appIndex = html.indexOf('src="/app.js"');
  const uiIndex = html.indexOf('src="/ui.js"');
  assert.ok(appIndex >= 0);
  assert.ok(uiIndex > appIndex);
});
