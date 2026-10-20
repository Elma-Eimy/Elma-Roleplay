const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const sourceRoot = path.resolve(__dirname, "../../src");

function createLoader({ platform = "H5", mocks = {}, globals = {} } = {}) {
  const cache = new Map();
  function load(filename) {
    const fullPath = path.isAbsolute(filename) ? filename : path.resolve(sourceRoot, filename);
    if (cache.has(fullPath)) return cache.get(fullPath).exports;
    const stack = [true];
    const source = fs.readFileSync(fullPath, "utf8").split(/\r?\n/).filter((line) => {
      const directive = line.match(/^\s*\/\/\s*#(ifdef|ifndef|endif)\s*(.*)$/);
      if (!directive) return stack.at(-1);
      if (directive[1] === "endif") stack.pop();
      else {
        const match = directive[2].split(/\s*\|\|\s*/).includes(platform);
        stack.push(stack.at(-1) && (directive[1] === "ifdef" ? match : !match));
      }
      return false;
    }).join("\n");
    const code = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    }).outputText;
    const module = { exports: {} };
    cache.set(fullPath, module);
    const localRequire = (name) => {
      if (Object.hasOwn(mocks, name)) return mocks[name];
      if (name.startsWith("@/") || name.startsWith(".")) {
        const base = name.startsWith("@/") ? path.join(sourceRoot, name.slice(2)) : path.resolve(path.dirname(fullPath), name);
        return load(base.endsWith(".ts") ? base : base + ".ts");
      }
      return require(name);
    };
    vm.runInNewContext(code, {
      module, exports: module.exports, require: localRequire,
      console, setTimeout, clearTimeout, setInterval, clearInterval,
      TextDecoder, TextEncoder, Uint8Array, ArrayBuffer, AbortController, Error,
      ...globals,
    }, { filename: fullPath });
    return module.exports;
  }
  return load;
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

module.exports = { createLoader, deferred, sourceRoot };
