// Watchlist: saved repos with a one-line status each, and an "Add" sheet.

import { api } from "../api.js";
import { validateRepoUrl } from "../format.js";
import {
  applyOnlineState,
  debtBadge,
  emptyState,
  errorState,
  h,
  openSheet,
  skeletonList,
  textField,
  toast,
} from "../ui.js";

export async function render(view, _params, ctx) {
  ctx.setTitle("Watchlist");
  const addButton = h(
    "button",
    { class: "btn btn-primary", type: "button", "data-online-only": true, onclick: () => openAddSheet(ctx) },
    "Add repository",
  );
  const body = h("div", {}, skeletonList(3));
  view.append(h("div", { class: "actions" }, addButton), body);

  let items;
  try {
    items = await api.listWatchlist();
  } catch (error) {
    body.replaceChildren(errorState(error.message, ctx.reload));
    return;
  }

  if (items.length === 0) {
    body.replaceChildren(
      emptyState(
        "Nothing on your watchlist yet",
        "Add a public GitHub repo to keep an eye on its AI instruction files and rescan it later.",
      ),
    );
    return;
  }
  body.replaceChildren(h("div", { class: "list" }, items.map(itemRow)));
}

function itemRow(item) {
  const latest = item.latest;
  return h(
    "a",
    { class: "row-link", href: `#/watchlist/${item.id}` },
    h(
      "span",
      { class: "row-head" },
      h("span", { class: "row-path" }, item.repo_full_name),
      latest?.debt_band && debtBadge(latest.debt_score, latest.debt_band),
    ),
    h(
      "span",
      { class: "row-meta" },
      item.label && h("span", { class: "tag" }, item.label),
      latest
        ? [
            h("span", {}, h("b", {}, String(latest.artefact_count)), " artefacts"),
            h("span", {}, h("b", {}, String(latest.open_findings)), " open findings"),
          ]
        : h("span", {}, "Not scanned"),
    ),
  );
}

function openAddSheet(ctx) {
  const url = textField({
    id: "add-url",
    label: "GitHub repository URL",
    type: "url",
    inputmode: "url",
    autocomplete: "off",
    autocapitalize: "off",
    spellcheck: "false",
    placeholder: "https://github.com/owner/repo",
  });
  const label = textField({ id: "add-label", label: "Label (optional)", maxlength: "100" });
  label.input.classList.add("input-text");
  const submit = h("button", { class: "btn btn-primary", type: "submit", "data-online-only": true }, "Add");

  url.input.addEventListener("input", () => {
    url.setError(url.input.value.trim() ? validateRepoUrl(url.input.value) : null);
  });

  let close;
  const form = h(
    "form",
    {
      class: "form",
      novalidate: true,
      onsubmit: async (event) => {
        event.preventDefault();
        const problem = validateRepoUrl(url.input.value);
        url.setError(problem);
        if (problem) {
          url.input.focus();
          return;
        }
        submit.disabled = true;
        submit.textContent = "Adding… (scanning)";
        try {
          const item = await api.addWatchItem({ url: url.input.value, label: label.input.value });
          close();
          toast(`Added ${item.repo_full_name} to your watchlist`);
          ctx.reload();
        } catch (error) {
          if (["invalid_url", "repo_not_found", "already_watched", "empty_repository"].includes(error.code)) {
            url.setError(error.message);
          } else {
            toast(error.message, "error");
          }
          submit.disabled = false;
          submit.textContent = "Add";
          applyOnlineState();
        }
      },
    },
    url.field,
    label.field,
    h("div", { class: "actions" }, submit),
  );

  close = openSheet("Add repository", form);
  applyOnlineState();
  url.input.focus();
}
