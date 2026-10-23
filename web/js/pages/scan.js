// Scan (home): paste a GitHub URL, scan it, go to the report.

import { api } from "../api.js";
import { validateRepoUrl } from "../format.js";
import { applyOnlineState, h, spinner, textField, toast } from "../ui.js";

// Errors that are about what was typed are shown under the field; others as toasts.
const FIELD_ERRORS = new Set(["invalid_url", "repo_not_found", "empty_repository"]);

export function render(view, _params, ctx) {
  ctx.setTitle("PromptDebt Scanner");

  const { field, input, setError } = textField({
    id: "repo-url",
    label: "GitHub repository URL",
    type: "url",
    inputmode: "url",
    autocomplete: "off",
    autocapitalize: "off",
    spellcheck: "false",
    placeholder: "https://github.com/owner/repo",
  });
  const button = h("button", { class: "btn btn-primary", type: "submit", "data-online-only": true }, "Scan");
  const loading = h("p", { class: "loading", role: "status", hidden: true }, spinner(), "Scanning… usually a few seconds");

  // Live validation: once the user has typed something, check as they go.
  input.addEventListener("input", () => {
    setError(input.value.trim() ? validateRepoUrl(input.value) : null);
  });

  const setBusy = (busy) => {
    button.disabled = busy;
    input.readOnly = busy;
    loading.hidden = !busy;
    if (!busy) applyOnlineState();
  };

  const form = h(
    "form",
    {
      class: "form",
      novalidate: true,
      onsubmit: async (event) => {
        event.preventDefault();
        const problem = validateRepoUrl(input.value);
        setError(problem);
        if (problem) {
          input.focus();
          return;
        }
        setBusy(true);
        try {
          const report = await api.scan(input.value);
          ctx.navigate(`/report/${report.id}`);
        } catch (error) {
          if (FIELD_ERRORS.has(error.code)) {
            setError(error.message);
            input.focus();
          } else {
            toast(error.message, "error");
          }
          setBusy(false);
        }
      },
    },
    field,
    h("div", { class: "actions" }, button),
    loading,
  );

  view.append(
    h(
      "p",
      { class: "muted" },
      "Check whether a repo's AI coding-tool instruction files (CLAUDE.md, AGENTS.md, .cursorrules, Copilot instructions) have kept up with its code.",
    ),
    form,
    h("p", { class: "meta" }, "Public repositories only. ", h("a", { href: "#/watchlist" }, "Go to your watchlist")),
  );
}
