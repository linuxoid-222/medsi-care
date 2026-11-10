import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import ts from "typescript";
const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
for (const [evidence, dirty, expected] of [["боль в груди", false, 1], ["нет в тексте", false, 0], ["", false, 0], ["боль в груди", true, 0]]) {
  test(`manual draft: ${JSON.stringify(evidence)}, dirty=${dirty}`, () => {
    const handler = app.match(/  function addManualFact\(\) \{[\s\S]*?\n  \}/)?.[0];
    assert.ok(handler, "manual fact entry must work without a successful extraction");
    const errors = [], drafts = [];
    const script = ts.transpileModule(handler + "\naddManualFact", { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
    const add = vm.runInNewContext(script, {
      manualCategory: "chest_pain", manualPolarity: "present", manualEvidence: evidence,
      activeCheckIn: { text_revision: 1, text: "У меня боль в груди", corrected_text: null },
      factText: "У меня боль в груди", textDirty: dirty, facts: [],
      editFacts: (facts) => drafts.push(...facts), setManualEvidence: () => {}, setError: (message) => errors.push(message),
      apiFetch: () => { throw new Error("adding a draft must not call the API or confirm it"); },
    });
    add();
    assert.equal(drafts.length, expected);
    if (expected) {
      assert.equal(drafts[0].confirmed, false);
      assert.equal(drafts[0].category, "chest_pain");
      assert.equal(drafts[0].evidence, evidence);
    } else assert.ok(errors.some(Boolean));
  });
}
