// Report: one repo's Prompt Debt Score, its artefacts, broken references and findings.
// Findings can be triaged once the repo is on the watchlist.

import { api } from "../api.js";
import {
  SCORE_PARTS,
  TRIAGE_LABELS,
  commitCount,
  formatDate,
  parseFindingKey,
  shortSha,
  timeAgo,
} from "../format.js";
import {
  applyOnlineState,
  debtBadge,
  errorState,
  h,
  skeletonList,
  spinner,
  statusBadge,
  toast,
} from "../ui.js";

const SHOW_AT_MOST = 10;

export async function render(view, [scanId], ctx) {
  ctx.setTitle("Report");
  view.append(skeletonList(4));

  let report;
  try {
    report = await api.getScan(scanId);
  } catch (error) {
    if (error.status === 404) {
      view.replaceChildren(h("p", { class: "muted" }, "This report doesn't exist."));
    } else {
      view.replaceChildren(errorState(error.message, ctx.reload));
    }
    return;
  }

  ctx.setTitle(report.repo_full_name, true);
  const openCount = h("span", { class: "value" }, String(countOpen(report.findings)));
  const updateOpenCount = () => {
    openCount.textContent = String(countOpen(report.findings));
  };

  // Adding the repo to the watchlist swaps in a findings list with triage controls.
  const findings = h("div", {}, findingSection(report, updateOpenCount));
  const onWatched = () => {
    findings.replaceChildren(findingSection(report, updateOpenCount));
    applyOnlineState();
  };

  // The score includes the AI review's conflicts, so it's refreshed once a review lands.
  const summaryBox = h("div", {}, summary(report, openCount));
  const scoreBox = h("div", {}, report.debt && scoreSection(report.debt));
  const refreshScore = async () => {
    try {
      report.debt = (await api.getScan(report.id)).debt;
      summaryBox.replaceChildren(summary(report, openCount));
      scoreBox.replaceChildren(scoreSection(report.debt));
    } catch {
      // The earlier score stays on screen; reopening the report shows the new one.
    }
  };

  const sections = [
    h(
      "p",
      { class: "meta mono" },
      `As of HEAD ${shortSha(report.head_sha)} (${formatDate(report.last_commit_at)}) · scanned ${timeAgo(report.scanned_at)}`,
    ),
    report.archived && h("p", { class: "note" }, "This repository is archived, so it is no longer being updated."),
    summaryBox,
    watchAction(report, onWatched),
    scoreBox,
    reviewSection(report, refreshScore),
    report.tools.length > 1 &&
      h(
        "p",
        { class: "note" },
        `Instructions for ${report.tools.length} tools (${report.tools.join(", ")}). More files to keep in sync with each other and the code.`,
      ),
    report.artefacts.length ? artefactSection(report) : noArtefacts(),
    report.artefacts.length > 0 && brokenRefSection(report),
    report.findings.length > 0 && findings,
  ];
  view.replaceChildren(...sections.filter(Boolean));
  applyOnlineState();
}

function countOpen(findings) {
  return findings.filter((f) => !f.triage || f.triage.status === "open").length;
}

function githubLink(report, path, line) {
  const anchor = line ? `#L${line}` : "";
  return `https://github.com/${report.repo_full_name}/blob/${report.default_branch}/${path}${anchor}`;
}

/** The first few list items, plus a line saying how many more there are. */
function firstFew(items) {
  if (items.length <= SHOW_AT_MOST) return items;
  return [...items.slice(0, SHOW_AT_MOST), h("li", { class: "meta" }, `…and ${items.length - SHOW_AT_MOST} more`)];
}

function summary(report, openCount) {
  return h(
    "div",
    { class: "summary" },
    h("div", {}, h("span", { class: "value" }, String(report.artefacts.length)), h("span", { class: "label" }, "Artefacts")),
    h(
      "div",
      {},
      h("span", { class: "value" }, report.debt ? String(report.debt.score) : "–"),
      h("span", { class: "label" }, "Debt score"),
      report.debt && h("div", {}, debtBadge(null, report.debt.band)),
    ),
    h("div", {}, openCount, h("span", { class: "label" }, "Open findings")),
  );
}

function watchAction(report, onWatched) {
  const onWatchlist = (id) => h("a", { class: "btn", href: `#/watchlist/${id}` }, "On watchlist");
  if (report.watchlist_item_id) return h("div", { class: "actions" }, onWatchlist(report.watchlist_item_id));

  const container = h("div", { class: "actions" });
  const button = h(
    "button",
    {
      class: "btn",
      type: "button",
      "data-online-only": true,
      onclick: async () => {
        button.disabled = true;
        button.textContent = "Adding…";
        try {
          const item = await api.addWatchItem({ scan_id: report.id });
          report.watchlist_item_id = item.id;
          container.replaceChildren(onWatchlist(item.id));
          onWatched();
          toast(`Added ${report.repo_full_name} to your watchlist`);
        } catch (error) {
          toast(error.message, "error");
          button.disabled = false;
          button.textContent = "Add to watchlist";
        }
      },
    },
    "Add to watchlist",
  );
  container.append(button);
  return container;
}

/** Where the repo's score came from: points per component out of its maximum. */
function scoreSection(debt) {
  const value = (key, max) =>
    key === "conflicts" && !debt.conflicts_checked ? "not checked" : `${debt.points[key]} / ${max}`;
  return h(
    "section",
    { class: "section" },
    h("div", { class: "section-head" }, h("h2", { class: "section-title" }, "Prompt Debt Score"), debtBadge(debt.score, debt.band)),
    h(
      "dl",
      { class: "breakdown" },
      SCORE_PARTS.map(([key, label, max]) => [h("dt", {}, label), h("dd", { class: "mono" }, value(key, max))]),
    ),
    !debt.conflicts_checked &&
      h("p", { class: "meta" }, "No AI review yet, so conflicting rules are left out and the other 65 points are scaled up to 100."),
    h(
      "p",
      { class: "meta" },
      "0–100 for the whole repo: higher means more maintenance owed. Drift averages staleness and churn from the most out-of-date file; the rest add up across files. See Settings for the full formula.",
    ),
  );
}

/**
 * The AI review: what's most wrong, and possible conflicting rules (which count
 * towards the score).
 * Runs by itself when the report opens (once per scan; the server saves it). If it
 * can't run (usage limits, provider errors) the section says why and offers Retry.
 */
function reviewSection(report, onReviewed) {
  if (report.review) return renderedReview(report.review);
  if (!report.review_available) return null;

  const title = () => h("h2", { class: "section-title" }, "AI review");
  const note = () =>
    h("p", { class: "meta" }, "This repo's public instruction files are sent to a third-party AI provider for this review.");
  const section = h("section", { class: "section" });

  const run = async () => {
    section.replaceChildren(
      title(),
      h("p", { class: "loading", role: "status" }, spinner(), "Reviewing… usually a few seconds"),
      note(),
    );
    try {
      report.review = await api.reviewScan(report.id);
      section.replaceWith(renderedReview(report.review));
      onReviewed();
    } catch (error) {
      section.replaceChildren(
        title(),
        h("div", { class: "note", role: "alert" }, h("p", {}, "The AI review couldn't run."), h("p", { class: "muted" }, error.message)),
        h("div", { class: "actions" }, h("button", { class: "btn", type: "button", "data-online-only": true, onclick: run }, "Retry")),
        note(),
      );
      applyOnlineState();
    }
  };
  run();
  return section;
}

function renderedReview(review) {
  const conflicts = review.conflicts.length
    ? h(
        "ul",
        { class: "plain" },
        review.conflicts.map((c) =>
          h(
            "li",
            { class: "note conflict" },
            h("p", { class: "meta" }, "Possible conflict · AI-assisted, verify"),
            h("p", { class: "quote" }, h("span", { class: "meta mono" }, c.path_a), c.quote_a),
            h("p", { class: "quote" }, h("span", { class: "meta mono" }, c.path_b), c.quote_b),
            h("p", {}, c.explanation),
          ),
        ),
      )
    : h("p", { class: "muted" }, "No conflicting rules found.");
  return h(
    "section",
    { class: "section" },
    h("div", { class: "section-head" }, h("h2", { class: "section-title" }, "AI review"), h("span", { class: "tag tag-warn" }, "AI-assisted · verify")),
    h("h3", {}, "What's most wrong"),
    h("ol", { class: "overview" }, review.overview.map((sentence) => h("li", {}, sentence))),
    h("h3", {}, "Possible conflicts"),
    conflicts,
    h(
      "p",
      { class: "meta mono" },
      `${review.model} via ${review.provider} · prompt ${review.prompt_version} · ${timeAgo(review.created_at)}`,
    ),
  );
}

function artefactSection(report) {
  const rows = report.artefacts.map((a) =>
    h(
      "li",
      { class: "row" },
      h("div", { class: "row-head" }, h("span", { class: "row-path" }, a.path), statusBadge(a.status)),
      h(
        "div",
        { class: "row-meta" },
        h("span", { class: "tag" }, a.tool),
        a.days_behind === null
          ? h("span", {}, "No commit history found")
          : h("span", {}, h("b", {}, String(a.days_behind)), " days behind"),
        a.commits_since_update !== null &&
          h("span", {}, h("b", {}, commitCount(a.commits_since_update)), " commits since"),
        h("span", {}, h("b", {}, String(a.line_count)), " lines · ~", h("b", {}, a.approx_tokens.toLocaleString()), " tokens"),
        a.broken_refs?.length > 0 && h("span", {}, h("b", {}, String(a.broken_refs.length)), " broken references"),
        h("span", {}, a.documented ? "In README" : "Not in README"),
        a.aliases.length > 0 && h("span", {}, "Also linked as ", h("b", {}, a.aliases.join(", "))),
      ),
      a.duplicate_rules.length > 0 &&
        h(
          "details",
          { class: "details" },
          h("summary", {}, `${a.duplicate_rules.length} rules repeated in other files`),
          h(
            "ul",
            { class: "plain" },
            firstFew(a.duplicate_rules.map((d) => h("li", {}, d.text, h("span", { class: "meta mono" }, ` also in ${d.other_path}`)))),
          ),
        ),
      h(
        "p",
        { class: "meta" },
        `Edited in ${commitCount(a.change_count)} commits in total. `,
        h("a", { href: githubLink(report, a.path), target: "_blank", rel: "noopener noreferrer" }, "View on GitHub"),
      ),
    ),
  );
  return h(
    "section",
    { class: "section" },
    h("h2", { class: "section-title" }, "Artefacts"),
    h(
      "p",
      { class: "meta" },
      "Days behind: how long before the repo's latest commit the file was last changed (Fresh ≤ 30, Ageing 31–90, Stale > 90).",
    ),
    h("ul", { class: "list" }, rows),
  );
}

/** Every broken path, grouped by the file that mentions it, with the line and reason. */
function brokenRefSection(report) {
  const unchecked = report.artefacts.some((a) => a.broken_refs === null);
  const withBroken = report.artefacts.filter((a) => a.broken_refs?.length > 0);
  const body = withBroken.length
    ? withBroken.map((a) =>
        h(
          "div",
          { class: "section" },
          h("h3", { class: "group-title" }, a.path),
          h(
            "ul",
            { class: "list" },
            firstFew(
              a.broken_refs.map((ref) =>
                h(
                  "li",
                  { class: "row" },
                  h(
                    "div",
                    { class: "row-head" },
                    h("span", { class: "row-path" }, ref.path),
                    h("a", { class: "meta", href: githubLink(report, a.path, ref.line), target: "_blank", rel: "noopener noreferrer" }, `line ${ref.line}`),
                  ),
                  h("p", { class: "muted" }, ref.reason),
                  ref.found_at.length > 0 &&
                    h("p", { class: "meta" }, "Probably moved to ", h("span", { class: "mono" }, ref.found_at.join(", "))),
                ),
              ),
            ),
          ),
        ),
      )
    : unchecked
      ? []
      : [h("p", { class: "muted" }, "Every file and folder path mentioned in the artefacts exists.")];
  return h(
    "section",
    { class: "section" },
    h("h2", { class: "section-title" }, "Broken references"),
    unchecked &&
      h("p", { class: "meta" }, "References weren't checked: this repo is too large to list every file (over 40 top-level folders)."),
    body,
  );
}

function noArtefacts() {
  return h(
    "div",
    { class: "empty" },
    h("h2", {}, "No AI-tool artefacts found"),
    h(
      "p",
      { class: "muted" },
      "This repo has none of the instruction files we look for. Either it doesn't use these AI coding-tool conventions, or it keeps its prompts somewhere else. That doesn't mean it has no prompt debt.",
    ),
  );
}

/** Findings, with a triage control each when the repo is on the watchlist. */
function findingSection(report, updateOpenCount) {
  const watched = Boolean(report.watchlist_item_id);
  const rows = report.findings.map((finding, index) => {
    const { label } = parseFindingKey(finding.key);
    let control = null;
    if (watched) {
      const select = h(
        "select",
        { id: `triage-${index}`, class: "select", "data-online-only": true },
        Object.entries(TRIAGE_LABELS).map(([value, text]) =>
          h("option", { value, selected: (finding.triage?.status ?? "open") === value }, text),
        ),
      );
      select.addEventListener("change", () => saveTriage(report, finding, select, updateOpenCount));
      control = h("div", { class: "field" }, h("label", { for: `triage-${index}` }, "Triage"), select);
    }
    return h(
      "li",
      { class: "row" },
      h("div", { class: "row-head" }, h("span", {}, h("span", { class: "tag" }, label), " ", h("span", { class: "mono" }, finding.path))),
      h("p", {}, finding.summary),
      control,
    );
  });
  return h(
    "section",
    { class: "section" },
    h("h2", { class: "section-title" }, "Findings"),
    !watched && h("p", { class: "meta" }, "Add this repo to your watchlist to triage these findings."),
    h("ul", { class: "list" }, rows),
  );
}

/** First change creates the triage entry; later changes update it. */
async function saveTriage(report, finding, select, updateOpenCount) {
  const status = select.value;
  const previous = finding.triage?.status ?? "open";
  select.disabled = true;
  try {
    finding.triage = finding.triage
      ? await api.updateTriage(finding.triage.id, { status })
      : await api.createTriage({ repo_full_name: report.repo_full_name, finding_key: finding.key, status });
    updateOpenCount();
    toast(`Marked as ${TRIAGE_LABELS[status]}`);
  } catch (error) {
    select.value = previous;
    toast(error.message, "error");
  } finally {
    select.disabled = false;
    applyOnlineState();
  }
}
