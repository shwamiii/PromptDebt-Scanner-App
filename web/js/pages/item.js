// Watchlist item: latest result, rescan, edit label and notes, delete.

import { api } from "../api.js";
import { timeAgo } from "../format.js";
import {
  applyOnlineState,
  confirmDialog,
  debtBadge,
  errorState,
  h,
  skeletonList,
  toast,
  withBusy,
} from "../ui.js";

export async function render(view, [itemId], ctx) {
  ctx.setTitle("Watchlist");
  view.append(skeletonList(3));

  let item;
  try {
    item = await api.getWatchItem(itemId);
  } catch (error) {
    if (error.status === 404) {
      view.replaceChildren(h("p", { class: "muted" }, "This watchlist item doesn't exist."));
    } else {
      view.replaceChildren(errorState(error.message, ctx.reload));
    }
    return;
  }

  ctx.setTitle(item.repo_full_name, true);
  view.replaceChildren(latestSection(item, ctx), detailsForm(item), deleteSection(item, ctx));
  applyOnlineState();
}

function latestSection(item, ctx) {
  const latest = item.latest;
  const rescan = h(
    "button",
    {
      class: "btn",
      type: "button",
      "data-online-only": true,
      onclick: async () => {
        try {
          await withBusy(rescan, "Rescanning…", () => api.rescanWatchItem(item.id));
          toast(`Rescanned ${item.repo_full_name}`);
          ctx.reload();
        } catch (error) {
          toast(error.message, "error");
          applyOnlineState();
        }
      },
    },
    "Rescan",
  );

  return h(
    "section",
    { class: "section" },
    h("h2", {}, "Latest scan"),
    latest
      ? h(
          "div",
          { class: "row" },
          h(
            "div",
            { class: "row-head" },
            h("span", {}, `Scanned ${timeAgo(latest.scanned_at)}`),
            latest.debt_band ? debtBadge(latest.debt_score, latest.debt_band) : h("span", { class: "meta" }, "No artefacts"),
          ),
          h(
            "div",
            { class: "row-meta" },
            h("span", {}, h("b", {}, String(latest.artefact_count)), " artefacts"),
            h("span", {}, h("b", {}, String(latest.open_findings)), " open findings"),
          ),
        )
      : h("p", { class: "muted" }, "Not scanned yet."),
    h(
      "div",
      { class: "actions" },
      latest && h("a", { class: "btn btn-primary", href: `#/report/${latest.scan_id}` }, "View full report"),
      rescan,
    ),
  );
}

function detailsForm(item) {
  const label = h("input", { id: "item-label", class: "input input-text", maxlength: "100", value: item.label });
  const notes = h("textarea", { id: "item-notes", class: "textarea", rows: "4", maxlength: "2000" }, item.notes);
  const save = h("button", { class: "btn", type: "submit" }, "Save");

  return h(
    "form",
    {
      class: "section",
      onsubmit: async (event) => {
        event.preventDefault();
        try {
          await withBusy(save, "Saving…", () =>
            api.updateWatchItem(item.id, { label: label.value, notes: notes.value }),
          );
          toast("Saved");
        } catch (error) {
          toast(error.message, "error");
        }
      },
    },
    h("h2", {}, "Details"),
    h("div", { class: "field" }, h("label", { for: "item-label" }, "Label"), label),
    h("div", { class: "field" }, h("label", { for: "item-notes" }, "Notes"), notes),
    h("div", { class: "actions" }, save),
  );
}

function deleteSection(item, ctx) {
  const remove = h(
    "button",
    {
      class: "btn btn-danger",
      type: "button",
      onclick: async () => {
        const confirmed = await confirmDialog({
          title: `Remove ${item.repo_full_name}?`,
          body: "Its label, notes and triage decisions for it will be deleted.",
          confirmLabel: "Remove",
        });
        if (!confirmed) return;
        try {
          await withBusy(remove, "Removing…", () => api.deleteWatchItem(item.id));
          toast(`Removed ${item.repo_full_name}`);
          ctx.goBack();
        } catch (error) {
          toast(error.message, "error");
        }
      },
    },
    "Remove from watchlist",
  );
  return h("section", { class: "section" }, h("div", { class: "actions" }, remove));
}
