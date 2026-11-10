import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import ts from "typescript";

// Run the actual submission handler with only IO/state setters substituted.
// This reproduces the original Number("") bug without copying its conversion.
const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const handler = app.match(/  async function submitObservation\(event: FormEvent\) \{[\s\S]*?\n  \}/)[0];
const helperPath = new URL("../src/observationInput.ts", import.meta.url);
const helpers = {};
if (existsSync(helperPath)) {
  const code = ts.transpileModule(readFileSync(helperPath, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  vm.runInNewContext(code, { exports: helpers });
}
for (const metric of ["sleep_hours", "activity_minutes"]) {
  for (const value of ["", "   ", "0", "8"]) {
    test(`${metric}: ${JSON.stringify(value)}`, async () => {
      const calls = [], errors = [];
      const script = ts.transpileModule(handler + "\nsubmitObservation", { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
      const submit = vm.runInNewContext(script, {
        ...helpers, value, metric, unit: metric === "sleep_hours" ? "hours" : "minutes", profileId: "profile-demo",
        setError: (message) => errors.push(message),
        apiFetch: async (path, init) => { calls.push(JSON.parse(init.body)); return { ok: true }; },
        loadObservations: async () => {},
      });
      await submit({ preventDefault() {} });
      if (!value.trim()) {
        assert.equal(calls.length, 0, "blank input must not send an API request");
        assert.ok(errors.some((message) => message.length > 0), "show a readable error");
      } else {
        assert.equal(calls.length, 1);
        assert.equal(calls[0].value, Number(value));
      }
    });
  }
}
