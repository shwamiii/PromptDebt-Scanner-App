import assert from "node:assert/strict";
import { test } from "node:test";

import { commitCount, maskKey, parseFindingKey, timeAgo, validateRepoUrl } from "../js/format.js";

test("accepts common GitHub URL forms", () => {
  for (const url of [
    "https://github.com/acme/widgets",
    "https://github.com/acme/widgets/",
    "https://github.com/acme/widgets.git",
    "https://www.github.com/acme/widgets",
    "github.com/acme/widgets",
    "  https://github.com/acme/widgets/tree/main/src  ",
  ]) {
    assert.equal(validateRepoUrl(url), null, url);
  }
});

test("rejects bad input with the same messages as the server", () => {
  assert.equal(validateRepoUrl(""), "Enter a GitHub repository URL");
  assert.equal(validateRepoUrl("https://gitlab.com/acme/widgets"), "That's not a GitHub URL");
  assert.equal(validateRepoUrl("https://github.com.evil.com/a/b"), "That's not a GitHub URL");
  assert.equal(validateRepoUrl("acme/widgets"), "That's not a GitHub URL");
  assert.equal(validateRepoUrl("https://github.com/acme"), "Include the owner and repository name");
  assert.equal(
    validateRepoUrl("https://github.com/-acme/widgets"),
    "That isn't a valid GitHub repository URL",
  );
});

test("parses finding keys, including paths with colons", () => {
  assert.deepEqual(parseFindingKey("stale:.github/copilot-instructions.md"), {
    type: "stale",
    path: ".github/copilot-instructions.md",
    label: "Stale",
  });
  assert.equal(parseFindingKey("undocumented:a:b.md").path, "a:b.md");
  assert.equal(parseFindingKey("undocumented:CLAUDE.md").label, "Not in README");
  assert.equal(parseFindingKey("broken_refs:AGENTS.md").label, "Broken references");
  assert.equal(parseFindingKey("duplicated:AGENTS.md").label, "Duplicated rules");
  assert.equal(parseFindingKey("oversized:AGENTS.md").label, "Oversized");
});

test("shows capped commit counts as 100+", () => {
  assert.equal(commitCount(7), "7");
  assert.equal(commitCount(100), "100+");
});

test("formats relative times", () => {
  const now = Date.parse("2026-10-22T12:00:00Z");
  assert.equal(timeAgo("2026-10-22T11:59:30Z", now), "just now");
  assert.equal(timeAgo("2026-10-22T11:45:00Z", now), "15 min ago");
  assert.equal(timeAgo("2026-10-22T09:00:00Z", now), "3 h ago");
  assert.equal(timeAgo("2026-10-01T09:00:00Z", now), "1 Oct 2026");
});

test("masks keys", () => {
  assert.equal(maskKey("AbCdEfGhIjKlMnOpQrStUvWxYz"), "AbCd…WxYz");
  assert.equal(maskKey("short"), "••••");
});
