// Settings: this device's key (copy, switch, delete), a glossary and the privacy note.

import { api, ensureKey, getKey, setKey } from "../api.js";
import { maskKey } from "../format.js";
import { confirmDialog, h, textField, toast, withBusy } from "../ui.js";

// "What is prompt debt?", in the words of the research paper this app accompanies:
// Nel, G. "Prompts as Technical Debt: A Study on Maintaining AI-Generated Codebases
// and Traceability between Prompts and Source Code" (Introduction and Methodology).
const DEFINITION = [
  "The concept of technical debt, introduced by Ward Cunningham, describes the long-term cost incurred when expedient decisions in development create future maintenance burdens. AI-assisted development introduces a new and underexamined category of technical debt, not rooted in how the code is structured, but the absence of the reasoning that produced it.",
  "The developer's intent exists only in the prompt that produced the code, and in the majority of cases, that prompt is ephemeral and not stored in any way. Unlike source code, prompts are rarely subject to version control, peer review, or documentation standards. The result is a structural and growing gap between the intent behind AI-generated code and the code itself, a gap that widens every time a maintainer inherits a codebase they did not write and cannot interrogate.",
  "Where prompts are kept, they live in development-time prompt artefacts such as CLAUDE.md, AGENTS.md, .cursorrules and .github/copilot-instructions.md. A developer inheriting the repository can only benefit from the artefact if they know it exists and understands its role. When a prompt has been updated less frequently than the surrounding codebase, that is an indicator of prompt-to-code divergence.",
];
// What the scanner can and can't see, given that most prompts are never saved.
const SCOPE =
  "Most prompts are never saved: they are typed into a chat window, used once and discarded, so there is nothing left in the repository to scan. The prompts that do survive are the agent instruction files a team commits alongside the code. This app can't recover the lost prompts, so it checks the next best thing: that those agent files exist, are easy to find, and are kept up to date with the code they describe.";

const SOURCE = "From the research paper Prompts as Technical Debt: A Study on Maintaining AI-Generated Codebases and Traceability between Prompts and Source Code (G. Nel).";

const GLOSSARY = [
  ["Artefact", "A file of instructions written for an AI coding tool, such as CLAUDE.md, AGENTS.md, .cursorrules or .github/copilot-instructions.md."],
  ["Days behind", "How long before the repo's latest commit the artefact was last changed. Measured against the latest commit, not today, so quiet repos aren't penalised."],
  ["Fresh, Ageing, Stale", "Fresh: 30 days behind or less. Ageing: 31 to 90 days. Stale: more than 90. Unknown: no commit history could be found."],
  ["Prompt Debt Score", "One 0–100 score for a repo's AI instruction files as a whole. Points come from conflicting rules found by the AI review (up to 35), broken references (25, total across files), drift (20: staleness and code churn of the most out-of-date file, averaged because they measure the same thing), duplicated rules (10), the share of files not in the README (5) and total size (5). If the AI review hasn't run or fails, conflicting rules are left out and the other 65 points are scaled up to 100. Low is under 25, Moderate 25–49, High 50 and up. The weights are provisional."],
  ["Commits since update", "How many commits have landed in the repo since the artefact last changed: how much code has moved on underneath it."],
  ["Broken references", "File or folder paths an artefact mentions that don't exist in the repo: instructions describing code that's gone. The report shows the line each one is on, and where a file with the same name now lives if it was probably moved."],
  ["Duplicated rules", "The same rule written in more than one artefact. When one copy is updated, the other quietly goes out of date."],
  ["Size", "Lines and approximate tokens (about 4 characters each). Long files cost context on every AI request and are harder to keep accurate."],
  ["AI review", "A check by an AI model, run automatically on each report, that looks for rules that contradict each other and summarises what to fix first. Its conflicts count towards the score; every quoted rule is checked against the real file before it's shown. Verify before acting on it."],
  ["Fragmentation", "Instructions for two or more tools in one repo, so several files must be kept in sync."],
  ["Documented", "Whether the README mentions the artefact by name, so a new contributor would know it exists."],
  ["Finding", "A problem worth a decision: broken references, a stale artefact, duplicated rules, an artefact the README doesn't mention, or an oversized one."],
  ["Triage", "Your decision on a finding: Open, Acknowledged, Fixed or Ignored. Available for repos on your watchlist. If you mark one Fixed but a later scan still finds it, it's flagged Still detected."],
];

export async function render(view, _params, ctx) {
  ctx.setTitle("Settings");
  const key = getKey() ?? (await ensureKey().catch(() => null));
  view.append(keySection(key, ctx), switchSection(ctx), resetSection(ctx), glossarySection(), privacySection());
}

function keySection(key, ctx) {
  if (!key) {
    return h(
      "section",
      { class: "section" },
      h("h2", {}, "Your key"),
      h("p", { class: "muted" }, "No key yet. Connect to the internet to get one."),
      h("button", { class: "btn", type: "button", onclick: ctx.reload }, "Retry"),
    );
  }

  const shown = h("code", { class: "key" }, maskKey(key));
  let revealed = false;
  const reveal = h(
    "button",
    {
      class: "btn",
      type: "button",
      onclick: () => {
        revealed = !revealed;
        shown.textContent = revealed ? key : maskKey(key);
        reveal.textContent = revealed ? "Hide" : "Show";
      },
    },
    "Show",
  );
  const copy = h(
    "button",
    {
      class: "btn",
      type: "button",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(key);
          toast("Key copied");
        } catch {
          toast("Couldn't copy. Use Show and copy it by hand.", "error");
        }
      },
    },
    "Copy",
  );

  return h(
    "section",
    { class: "section" },
    h("h2", {}, "Your key"),
    h(
      "p",
      { class: "muted" },
      "There are no accounts. This key is what links you to your watchlist and triage. Copy it to use the same data on another device, and keep it private.",
    ),
    shown,
    h("div", { class: "actions" }, reveal, copy),
  );
}

function switchSection(ctx) {
  const pasted = textField({ id: "paste-key", label: "Key from another device", autocomplete: "off", spellcheck: "false" });
  const submit = h("button", { class: "btn", type: "submit" }, "Use this key");
  return h(
    "form",
    {
      class: "section",
      novalidate: true,
      onsubmit: async (event) => {
        event.preventDefault();
        const value = pasted.input.value.trim();
        if (value.length < 20) {
          pasted.setError("That doesn't look like a key. Paste the whole thing.");
          return;
        }
        try {
          await withBusy(submit, "Checking…", () => api.checkKey(value));
        } catch (error) {
          pasted.setError(error.code === "invalid_key" ? "That key wasn't recognised" : error.message);
          return;
        }
        setKey(value);
        toast("Switched to the pasted key");
        ctx.reload();
      },
    },
    h("h2", {}, "Use an existing key"),
    pasted.field,
    h("div", { class: "actions" }, submit),
  );
}

function resetSection(ctx) {
  const button = h(
    "button",
    {
      class: "btn btn-danger",
      type: "button",
      onclick: async () => {
        const confirmed = await confirmDialog({
          title: "Delete your data?",
          body: "Your watchlist, triage decisions and key are deleted from the server. This can't be undone. You'll get a new, empty key.",
          confirmLabel: "Delete everything",
        });
        if (!confirmed) return;
        try {
          await withBusy(button, "Deleting…", async () => {
            await api.deleteIdentity();
            setKey(null);
            await ensureKey();
          });
          toast("Your data was deleted and a new key issued");
          ctx.reload();
        } catch (error) {
          toast(error.message, "error");
        }
      },
    },
    "Delete my data & reset",
  );
  return h("section", { class: "section" }, h("h2", {}, "Delete my data"), h("div", { class: "actions" }, button));
}

function glossarySection() {
  return h(
    "section",
    { class: "section" },
    h("h2", {}, "What is prompt debt?"),
    DEFINITION.map((paragraph) => h("p", {}, paragraph)),
    h("p", { class: "meta" }, SOURCE),
    h("h2", {}, "What this app can check"),
    h("p", {}, SCOPE),
    h("h2", {}, "Terms used in this app"),
    h("dl", { class: "glossary" }, GLOSSARY.map(([term, text]) => [h("dt", {}, term), h("dd", {}, text)])),
  );
}

function privacySection() {
  return h(
    "section",
    { class: "section" },
    h("h2", {}, "Privacy"),
    h(
      "p",
      { class: "muted" },
      "Only public GitHub data is scanned. No names, emails or other personal data are collected. Your key is stored on the server only as a one-way hash, and deleting your data removes everything linked to it. If you run an AI review, the repo's public instruction files are sent to a third-party AI provider; nothing about you is included.",
    ),
  );
}
