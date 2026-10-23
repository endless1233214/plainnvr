const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "static", "index.html"), "utf8");
const app = fs.readFileSync(path.join(root, "static", "app.js"), "utf8");
const ui = fs.readFileSync(path.join(root, "static", "ui.js"), "utf8");
const osClient = fs.readFileSync(path.join(root, "static", "os-client.js"), "utf8");
const applianceCss = fs.readFileSync(path.join(root, "static", "appliance.css"), "utf8");

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
  assert.match(ui, /Position \$\{index \+ 1\}/);
  assert.match(ui, /Choose a camera for position \$\{index \+ 1\}/);
  assert.match(ui, /next\[slotIndex\] = ["']["']/);
});

test("refresh explicitly restarts live players before reloading status", () => {
  assert.match(app, /window\.plainNvrUi\?\.stopWallPlayers\?\.\(\)/);
  assert.match(app, /if \(restartFocusedPlayer\) stopLiveMedia\(\)/);
  assert.match(app, /addEventListener\(["']click["'], refreshStatus\)/);
});

test("idle but available relays are not mislabeled as recovering", () => {
  assert.match(ui, /relay\?\.available !== true \|\| relay\?\.media_state === ["']stalled["']/);
  assert.match(app, /relay\?\.available === true && relay\?\.media_state !== ["']stalled["']/);
});

test("frontend scripts parse as JavaScript", () => {
  assert.doesNotThrow(() => new vm.Script(app, { filename: "app.js" }));
  assert.doesNotThrow(() => new vm.Script(ui, { filename: "ui.js" }));
  assert.doesNotThrow(() => new vm.Script(osClient, { filename: "os-client.js" }));
});

test("appliance unlock gives visible password-entry feedback and a reveal control", () => {
  assert.match(osClient, /id="os-unlock-password" type="password"/);
  assert.match(osClient, /class="os-password-toggle"/);
  assert.match(osClient, /character\$\{count === 1/);
  assert.match(applianceCss, /caret-color:\s*#168b7f/);
  assert.match(applianceCss, /-webkit-text-fill-color:\s*#17231f/);
});

test("ui controller is loaded after the existing app controller", () => {
  const appIndex = html.indexOf('src="/app.js"');
  const uiIndex = html.indexOf('src="/ui.js"');
  assert.ok(appIndex >= 0);
  assert.ok(uiIndex > appIndex);
});
