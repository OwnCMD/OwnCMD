import { test } from "node:test";
import assert from "node:assert/strict";
import { activitySteps, currentTurn } from "../lib/activity.mjs";
test("output recovery and pause clear stale thinking without a false failure", () => {
  for (const kind of ["retry", "pause"]) {
    const result = activitySteps([
      { id: 1, kind: "thinking", body: { text: "Choosing the next action" } },
      { id: 2, kind, body: { text: "Completed work is preserved" } },
    ]);
    assert.equal(result.length, 1);
    assert.equal(result[0].kind, kind);
    assert.equal(result[0].status, "completed");
  }
});
test("follow-ups show only the current turn", () => {
  assert.deepEqual(
    currentTurn([
      { kind: "tool_started" },
      { kind: "followup" },
      { kind: "thinking" },
    ]),
    [{ kind: "thinking" }],
  );
});
test("overlapping tools are paired by call ID, including failures", () => {
  const result = activitySteps([
    { id: 1, kind: "tool_started", body: { call_id: "a", name: "browse" } },
    { id: 2, kind: "tool_started", body: { call_id: "b", name: "browse" } },
    {
      id: 3,
      kind: "tool_finished",
      body: { call_id: "b", name: "browse", ok: false },
    },
    {
      id: 4,
      kind: "tool_finished",
      body: { call_id: "a", name: "browse", ok: true },
    },
  ]);
  assert.equal(result.length, 2);
  assert.equal(result[0].id, 1);
  assert.equal(result[0].body.ok, true);
  assert.equal(result[1].body.ok, false);
});
test("events without call ID pair with the latest matching tool", () => {
  const result = activitySteps([
    { id: 1, kind: "tool_started", body: { name: "run_code" } },
    { id: 2, kind: "tool_finished", body: { name: "run_code", ok: true } },
  ]);
  assert.equal(result.length, 1);
  assert.equal(result[0].body.ok, true);
});
test('approval retries keep one current activity and complete the same call',()=>{
 const result=activitySteps([{id:1,kind:'tool_started',body:{call_id:'pay',name:'browse'}},{id:2,kind:'approval',body:{}},{id:3,kind:'tool_started',body:{call_id:'pay',name:'browse'}},{id:4,kind:'tool_finished',body:{call_id:'pay',ok:true}}]);
 assert.equal(result.filter(s=>s.kind==='tool_started').length,1);
 assert.equal(result.filter(s=>s.status==='running').length,0);
});
