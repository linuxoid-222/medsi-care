import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import ts from "typescript";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const handler = app.match(/  async function saveTranscript\(\) \{[\s\S]*?\n  \}/)?.[0];
assert.ok(handler, "The transcript must have its own save handler");
const script = ts.transpileModule(handler + "\nsaveTranscript", {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText;

function createHandler(saveCheckIn, statuses, errors = []) {
  return vm.runInNewContext(script, {
    transcript: { text: "Сегодня чувствую слабость" },
    transcriptSaveRef: { current: null },
    transcriptAttemptRef: { current: null },
    crypto: { randomUUID },
    setError: (error) => errors.push(error),
    setTranscriptSaveStatus: (status) => statuses.push(status),
    saveCheckIn,
  });
}

test("one transcript is saved once across concurrent and subsequent clicks", async () => {
  let requests = 0;
  let finish;
  const pending = new Promise((resolve) => { finish = resolve; });
  const statuses = [];
  const save = createHandler((text) => {
    assert.equal(text, "Сегодня чувствую слабость");
    requests += 1;
    return pending;
  }, statuses);
  const first = save();
  await save();
  finish({ id: "synthetic-check-in" });
  await first;
  await save();
  assert.equal(requests, 1);
  assert.deepEqual(statuses, ["saving", "saved"]);
});

test("a failed save permits a retry", async () => {
  let requests = 0;
  const statuses = [];
  const errors = [];
  const save = createHandler(async () => {
    requests += 1;
    return requests === 1 ? null : { id: "synthetic-check-in" };
  }, statuses, errors);
  await save();
  await save();
  assert.equal(requests, 2);
  assert.deepEqual(statuses, ["saving", "idle", "saving", "saved"]);
  assert.deepEqual(errors, []);
});


test("retry after a committed save loses its response reuses the attempt key", async () => {
  const records = new Map();
  const attempts = [];
  const statuses = [];
  const errors = [];
  const save = createHandler(async (text, key) => {
    assert.match(key, /^[a-f0-9-]{36}$/);
    attempts.push(key);
    if (!records.has(key)) {
      records.set(key, { id: "committed-check-in", text });
      throw new TypeError("synthetic response loss");
    }
    return records.get(key);
  }, statuses, errors);
  await save();
  await save();
  assert.deepEqual(attempts, [attempts[0], attempts[0]]);
  assert.equal(records.size, 1);
  assert.deepEqual(statuses, ["saving", "idle", "saving", "saved"]);
  assert.equal(errors.length, 1);
  assert.match(errors[0], /Сервер мог уже сохранить запись/);
  assert.match(errors[0], /безопасно повторить ту же попытку/);
  assert.match(errors[0], /Перезагрузка страницы удалит текущий черновик/);
  assert.match(errors[0], /Открыть последнюю запись/);
});
