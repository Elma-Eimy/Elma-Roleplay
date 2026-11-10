const test = require("node:test");
const assert = require("node:assert/strict");
const { createLoader } = require("./helpers/load-ts.cjs");
const { groupRoundStatus, groupRoundNotice } = createLoader()("utils/groupRounds.ts");

test("round display distinguishes normal stops and preserves older server responses", () => {
  const round = { status: "awaiting_confirmation", confirmed: false };
  assert.equal(groupRoundStatus(round), "待确认");
  assert.equal(groupRoundNotice(round), "");
  assert.match(groupRoundNotice({ ...round, finish_reason: "wait_user" }), /结束本轮/);
  assert.match(groupRoundNotice({ ...round, finish_reason: "no_visible_basis" }), /未生成角色发言/);
  assert.match(groupRoundNotice({ ...round, finish_reason: "step_limit" }), /发言上限/);
  assert.equal(groupRoundNotice({ ...round, confirmed: true, finish_reason: "step_limit" }), "");
});

test("failed prefix and in-progress states never show a successful stop reason or raw error", () => {
  const round = { status: "failed", finish_reason: "step_limit", error_code: "PRIVATE_RAW_ERROR" };
  assert.equal(groupRoundStatus(round), "未完成");
  assert.match(groupRoundNotice(round), /已保存的发言仍可查看/);
  assert.doesNotMatch(groupRoundNotice(round), /PRIVATE|上限/);
  assert.match(groupRoundNotice({ ...round, error_code: "timeout" }), /超时/);
  assert.match(groupRoundNotice({ ...round, error_code: "incomplete_output" }), /截断/);
  assert.match(groupRoundNotice({ ...round, error_code: "invalid_output" }), /格式校验/);
  assert.match(groupRoundNotice({ ...round, error_code: "experience_check_failed" }), /亲历审查/);
  assert.equal(groupRoundNotice({ ...round, status: "generating" }), "");
});
