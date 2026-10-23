// Triage: every finding the user has given a status, across all repos.

import { api } from "../api.js";
import { TRIAGE_LABELS, parseFindingKey, timeAgo } from "../format.js";
import {
  confirmDialog,
  emptyState,
  errorState,
  h,
  icon,
  openSheet,
  skeletonList,
  toast,
  withBusy,
} from "../ui.js";

export async function render(view, _params, ctx) {
  ctx.setTitle("Triage");
  const body = h("div", {}, skeletonList(3));
  view.append(body);

  let entries;
  try {
    entries = await api.listTriage();
  } catch (error) {
    body.replaceChildren(errorState(error.message, ctx.reload));
    return;
  }

  if (entries.length === 0) {
    body.replaceChildren(
      emptyState(
        "Nothing triaged yet",
        "Add a repo to your watchlist, then set a status on its findings in its report. They show up here so you can track them across repos.",
        h("a", { class: "btn", href: "#/" }, "Scan a repo"),
      ),
    );
    return;
  }

  // Filters run in the page: the full list is already loaded and small.
  const statusFilter = h(
    "select",
    { id: "filter-status", class: "select" },
    h("option", { value: "" }, "All statuses"),
    Object.entries(TRIAGE_LABELS).map(([value, text]) => h("option", { value }, text)),
  );
  const repos = [...new Set(entries.map((e) => e.repo_full_name))].sort();
  const repoFilter = h(
    "select",
    { id: "filter-repo", class: "select" },
    h("option", { value: "" }, "All repos"),
    repos.map((repo) => h("option", { value: repo }, repo)),
  );
  const list = h("div", { class: "list" });

  const showList = () => {
    const shown = entries.filter(
      (e) =>
        (!statusFilter.value || e.status === statusFilter.value) &&
        (!repoFilter.value || e.repo_full_name === repoFilter.value),
    );
    list.replaceChildren(
      ...(shown.length
        ? shown.map((entry) => entryRow(entry, ctx))
        : [h("p", { class: "muted row" }, "No triaged findings match these filters.")]),
    );
  };
  statusFilter.addEventListener("change", showList);
  repoFilter.addEventListener("change", showList);
  showList();

  body.replaceChildren(
    h(
      "div",
      { class: "form" },
      h("div", { class: "field" }, h("label", { for: "filter-status" }, "Status"), statusFilter),
      h("div", { class: "field" }, h("label", { for: "filter-repo" }, "Repository"), repoFilter),
    ),
    list,
  );
}

function entryRow(entry, ctx) {
  const finding = parseFindingKey(entry.finding_key);
  const stillDetected = entry.status === "fixed" && entry.still_detected;
  return h(
    "button",
    { class: "row-link", type: "button", onclick: () => openEditSheet(entry, ctx) },
    h(
      "span",
      { class: "row-head" },
      h("span", { class: "row-path" }, finding.path),
      h("span", { class: "tag" }, TRIAGE_LABELS[entry.status]),
    ),
    h(
      "span",
      { class: "row-meta" },
      h("span", { class: "tag" }, finding.label),
      h("span", { class: "mono" }, entry.repo_full_name),
      stillDetected && h("span", { class: "tag tag-warn" }, icon("stale"), " Still detected"),
      h("span", {}, `Updated ${timeAgo(entry.updated_at)}`),
    ),
    entry.note && h("span", { class: "meta" }, entry.note),
  );
}

function openEditSheet(entry, ctx) {
  const finding = parseFindingKey(entry.finding_key);
  const status = h(
    "select",
    { id: "edit-status", class: "select" },
    Object.entries(TRIAGE_LABELS).map(([value, text]) =>
      h("option", { value, selected: entry.status === value }, text),
    ),
  );
  const note = h("textarea", { id: "edit-note", class: "textarea", rows: "3", maxlength: "2000" }, entry.note);
  const save = h("button", { class: "btn btn-primary", type: "submit" }, "Save");
  const clear = h(
    "button",
    {
      class: "btn btn-danger",
      type: "button",
      onclick: async () => {
        close();
        const confirmed = await confirmDialog({
          title: "Clear this triage?",
          body: "The finding goes back to Open and your note is deleted.",
          confirmLabel: "Clear",
        });
        if (!confirmed) return;
        try {
          await api.deleteTriage(entry.id);
          toast("Triage cleared");
          ctx.reload();
        } catch (error) {
          toast(error.message, "error");
        }
      },
    },
    "Clear",
  );

  const form = h(
    "form",
    {
      class: "form",
      onsubmit: async (event) => {
        event.preventDefault();
        try {
          await withBusy(save, "Saving…", () =>
            api.updateTriage(entry.id, { status: status.value, note: note.value }),
          );
          close();
          toast("Triage updated");
          ctx.reload();
        } catch (error) {
          toast(error.message, "error");
        }
      },
    },
    h("p", { class: "meta mono" }, `${entry.repo_full_name} · ${finding.label}`),
    h("div", { class: "field" }, h("label", { for: "edit-status" }, "Status"), status),
    h("div", { class: "field" }, h("label", { for: "edit-note" }, "Note"), note),
    h("div", { class: "actions" }, save, clear),
  );
  const close = openSheet(finding.path, form);
}
