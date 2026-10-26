#!/usr/bin/env node
/**
 * 零依赖前端纯函数测试：node mobile-prototype/tests/run.mjs
 *
 * 在 node:vm 里按需加载“无 DOM 的”经典脚本（window.SS 命名空间），再动态 import 本目录全部
 * *.test.mjs；每个测试文件默认导出 (SS, assert) => void。任一失败退出码 1。
 */
import vm from "node:vm";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");

// 只放不碰 document/localStorage 的文件；按依赖顺序
const SCRIPTS = [
  "js/lib/format.js",
  "js/lib/clock-model.js",
  "js/features/news/model.js",
  "js/lib/predict-math.js",
  "js/features/predict/model.js",
  "js/features/pm/model.js",
  "js/features/pm/mock.js",
  "js/features/challenge/model.js",
  "js/features/challenge/mock.js",
  "js/features/replay/model.js",
  "js/features/replay/mock.js",
];

const ctx = vm.createContext({ console });
ctx.window = ctx;
for (const rel of SCRIPTS) vm.runInContext(fs.readFileSync(path.join(ROOT, rel), "utf8"), ctx, { filename: rel });
const SS = ctx.SS;

// vm 里创建的对象原型与宿主不同：deepEqual 先经 JSON 往返再比较
const clone = (v) => JSON.parse(JSON.stringify(v));
const A = Object.assign((...a) => assert(...a), assert, {
  deepEqual: (a, b, m) => assert.deepStrictEqual(clone(a), clone(b), m),
});

let failed = 0;
let passed = 0;
const files = fs.readdirSync(HERE).filter((f) => f.endsWith(".test.mjs")).sort();
for (const f of files) {
  const mod = await import(pathToFileURL(path.join(HERE, f)).href);
  const tests = [];
  const t = (name, fn) => tests.push([name, fn]);
  mod.default(SS, A, t);
  for (const [name, fn] of tests) {
    try {
      fn();
      passed++;
    } catch (e) {
      failed++;
      console.error(`FAIL ${f} › ${name}\n  ${e.message.split("\n").join("\n  ")}`);
    }
  }
}
console.log(`${passed} passed, ${failed} failed (${files.length} files)`);
process.exit(failed ? 1 : 0);
