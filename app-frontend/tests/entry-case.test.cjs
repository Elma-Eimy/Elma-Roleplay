const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { sourceRoot } = require("./helpers/load-ts.cjs");

test("the app entry import has the exact same case as its file", () => {
  assert.ok(fs.readdirSync(sourceRoot).includes("App.vue"));
  assert.match(fs.readFileSync(path.join(sourceRoot, "main.ts"), "utf8"), /from ["']\.\/App\.vue["']/);
});
