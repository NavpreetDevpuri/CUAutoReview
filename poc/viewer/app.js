"use strict";

const RUN_URL = "/poc/runs/latest/run.json";
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { run: null, taskIndex: 0, section: "run", detailTab: "trajectory", stepIndex: 0, rawTaskUrl: null, sidebarCollapsed: false };

function node(tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined && value !== null) element.textContent = String(value);
  return element;
}

function valueText(value, fallback = "Not recorded") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value, null, 2); } catch (_) { return String(value); }
}

function appendField(parent, label, value, options = {}) {
  const block = node("div", "field-block");
  block.append(node("div", "field-label", label));
  const text = node(options.muted ? "div" : "div", `field-text${options.muted ? " muted" : ""}`, valueText(value, options.fallback));
  block.append(text);
  parent.append(block);
  return block;
}

function makeLink(label, href, className = "") {
  const link = node("a", className, label);
  link.href = href;
  if (/^https?:\/\//i.test(href)) {
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
  return link;
}

function internalArtifactPath(path) {
  if (typeof path !== "string" || !path.trim()) return null;
  const raw = path.trim();
  if (/^(javascript|data|file):/i.test(raw)) return null;
  if (/^https?:\/\//i.test(raw)) return raw;
  if (raw.startsWith("/poc/")) return raw;
  if (raw.startsWith("/")) return null;
  const clean = raw.replace(/^\.\//, "").replace(/^poc\//, "");
  return `/poc/${clean}`;
}

function screenshotPath(path) {
  if (typeof path !== "string" || !path.trim()) return null;
  const raw = path.trim();
  if (/^(javascript|data|file|https?):/i.test(raw)) return null;
  const parts = (raw.startsWith("/poc/") ? raw.slice(5) : raw.replace(/^\//, "").replace(/^poc\//, ""))
    .split("/").filter(part => part && part !== ".");
  const safe = [];
  for (const part of parts) {
    if (part === "..") safe.pop();
    else safe.push(part);
  }
  return safe.length ? `/poc/${safe.map(encodeURIComponent).join("/")}` : null;
}

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "Not available";
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat().format(number) : "Not available";
}

function formatCredits(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(number) : valueText(value, "Not available");
}

function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "Not priced";
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 4 }).format(number) : valueText(value);
}

function formatDate(value) {
  if (!value) return "Time not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function statusTone(value) {
  const normalized = String(value || "").toLowerCase();
  if (/complete|success|accepted|pass|resolved/.test(normalized)) return "good";
  if (/error|fail|blocked|rejected/.test(normalized)) return "bad";
  if (/review|warn|partial|in.progress|pending|stale/.test(normalized)) return "warn";
  return "";
}

function makeBadge(value, tone = "") {
  return node("span", `badge${tone ? ` ${tone}` : ""}`, valueText(value, "unmarked"));
}

function loadMessage(message, isError = false) {
  const host = $("#load-state");
  host.textContent = message;
  host.classList.toggle("error", isError);
  host.hidden = false;
  if (!isError) window.setTimeout(() => { host.hidden = true; }, 3800);
}

function updateOverview(run) {
  $("#run-id").textContent = valueText(run.run_id, "Unnamed batch");
  const status = $("#run-status");
  status.textContent = valueText(run.status, "unknown");
  status.dataset.status = String(run.status || "").toLowerCase();
  $("#model-name").textContent = valueText(run.model, "Not recorded");
  $(".usage-details > summary").textContent = `${valueText(run.model, "Model unavailable")}${run.reasoning_effort ? ` · ${run.reasoning_effort} reasoning` : ""} · Usage, cost and limits`;
  $("#task-count").textContent = formatNumber(Array.isArray(run.tasks) ? run.tasks.length : 0);
  const usage = run.usage || {};
  $("#input-tokens").textContent = formatNumber(usage.input_tokens);
  $("#cached-tokens").textContent = formatNumber(usage.cached_input_tokens);
  $("#output-tokens").textContent = formatNumber(usage.output_tokens);
  $("#estimated-cost").textContent = formatMoney(usage.estimated_usd);
  $("#pricing-note").textContent = valueText(usage.pricing_note, "");
  const estimatedCredits = usage.estimated_credits ?? run.estimated_credits ?? run.cost_summary?.estimated_credits;
  $("#estimated-credits").textContent = estimatedCredits === undefined ? "Not available" : formatCredits(estimatedCredits);
  $("#estimated-credit-note").textContent = estimatedCredits === undefined ? "" : "Estimate only; not an actual invoice";
  const started = run.started_at ? formatDate(run.started_at) : "Start time not recorded";
  const finished = run.finished_at ? ` · finished ${formatDate(run.finished_at)}` : "";
  $("#batch-dates").textContent = `${started}${finished}`;
  const limits = $("#limits-row");
  limits.replaceChildren();
  for (const [key, value] of Object.entries(run.limits || {})) {
    const chip = node("span", "limit-chip");
    chip.append(node("b", "", key.replaceAll("_", " ")), document.createTextNode(` ${valueText(value)}`));
    limits.append(chip);
  }
}

function taskReviewStatus(task) {
  const status = task.review?.review_kind || task.status || "unreviewed";
  return String(status);
}

function taskHasReview(task) {
  const review = task?.review;
  return Boolean(review && typeof review === "object" && !Array.isArray(review) && Object.keys(review).length);
}

function evaluatorOutcome(task) {
  const raw = task?.outcome;
  if (raw === true) return { label: "Passed", tone: "good" };
  if (raw === false) return { label: "Failed", tone: "bad" };
  const outcome = typeof raw === "string" ? raw.trim() : "";
  const normalized = outcome.toLowerCase();
  if (["pass", "passed", "success", "successful"].includes(normalized)) return { label: "Passed", tone: "good" };
  if (["fail", "failed", "failure"].includes(normalized)) return { label: "Failed", tone: "bad" };
  return outcome ? { label: outcome, tone: "" } : { label: "Outcome not recorded", tone: "" };
}

function taskRecordedCounts(task) {
  if (!taskHasReview(task) || !Array.isArray(task.review.episodes)) return null;
  const flagged = new Set();
  const recovery = new Set();
  for (const episode of task.review.episodes) {
    for (const id of episode.onset_step_ids || []) if (id !== null && id !== undefined) flagged.add(String(id));
    for (const id of episode.recovery?.step_ids || []) if (id !== null && id !== undefined) recovery.add(String(id));
  }
  return { problems: task.review.episodes.length, flaggedSteps: flagged.size, recoverySteps: recovery.size };
}

function taskCanonicalLabelCounts(task) {
  if (!taskHasReview(task) || !Array.isArray(task.review.episodes)) return null;
  const counts = new Map();
  for (const episode of task.review.episodes) {
    const resolved = episodeLabel(episode);
    const key = resolved.canonical && resolved.canonicalId ? `canonical:${resolved.canonicalId}` : "unmapped";
    const existing = counts.get(key) || { label: resolved.canonical ? resolved.label : "Draft / unclassified", id: resolved.canonical ? resolved.canonicalId : null, count: 0 };
    existing.count += 1;
    counts.set(key, existing);
  }
  return [...counts.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

function taskDialogPoints(task) {
  const episodes = Array.isArray(task.review?.episodes) ? task.review.episodes : [];
  const groups = [];
  for (const episode of episodes) {
    const primary = new Map();
    const related = new Map();
    const add = (collection, stepId, role) => {
      if (stepId === null || stepId === undefined) return;
      const key = String(stepId);
      const point = collection.get(key) || { stepId: key, roles: [] };
      if (!point.roles.includes(role)) point.roles.push(role);
      collection.set(key, point);
    };

    const origin = problemOrigin(task, episode);
    const onsetIds = new Set((episode.onset_step_ids || []).filter(id => id !== null && id !== undefined).map(String));
    // Schema v2 has an explicit first-observed anchor; if it is also flagged,
    // stepRole supplies the one correct label without adding a duplicate link.
    if (origin.recorded && !onsetIds.has(String(origin.stepId))) add(primary, origin.stepId, "First observed");
    for (const id of episode.onset_step_ids || []) {
      if (id === null || id === undefined) continue;
      add(primary, id, stepRole("onset", task, episode, { step_id: id })[0].replace(/ here$/, ""));
    }
    for (const id of episode.recovery?.step_ids || []) add(primary, id, "Recovery");
    for (const step of task.steps || []) {
      if (step.step_id === null || step.step_id === undefined) continue;
      if (episodesForStep(task, step).some(item => item.episode === episode && item.kinds.includes("context"))) {
        add(related, step.step_id, "Related");
      }
    }
    const makePoints = collection => [...collection.values()].map(point => ({
      ...point,
      available: (task.steps || []).some(step => String(step.step_id) === point.stepId),
    }));
    groups.push({ episode, problem: problemNumber(task, episode), label: episodeLabel(episode), primary: makePoints(primary), related: makePoints(related) });
  }
  return groups;
}

function updateTaskSearch() {
  const query = String($("#task-search")?.value || "").trim().toLocaleLowerCase();
  const cards = $$("[data-task-card]", $("#task-dialog-list"));
  let visible = 0;
  for (const card of cards) {
    const matches = !query || card.dataset.search.includes(query);
    card.hidden = !matches;
    if (matches) visible += 1;
  }
  $("#task-search-count").textContent = `${visible} of ${cards.length} tasks`;
  $("#task-dialog-empty").hidden = visible > 0;
  $("#task-dialog-empty").textContent = cards.length ? "No tasks match this search." : "No task records are available in this batch.";
}

function renderTaskDialogList() {
  const host = $("#task-dialog-list");
  if (!host) return;
  host.replaceChildren();
  const tasks = Array.isArray(state.run?.tasks) ? state.run.tasks : [];
  for (const [index, task] of tasks.entries()) {
    const card = node("article", "task-dialog-card");
    card.dataset.taskCard = "true";
    const episodes = Array.isArray(task.review?.episodes) ? task.review.episodes : [];
    const problemGroups = taskDialogPoints(task);
    const labelSearch = episodes.map(episode => episodeLabel(episode).label).join(" ");
    const stepSearch = problemGroups.flatMap(group => [...group.primary, ...group.related].flatMap(point => [point.stepId, ...point.roles])).join(" ");
    card.dataset.search = [task.title, task.task_id, task.instruction, task.outcome, labelSearch, stepSearch].filter(Boolean).join(" ").toLocaleLowerCase();

    const head = node("div", "task-dialog-card-head");
    const identity = node("div", "task-dialog-identity");
    identity.append(node("span", "task-dialog-index", `TASK ${index + 1}`));
    if (index === state.taskIndex) identity.append(node("span", "task-dialog-current", "Current task"));
    identity.append(node("h3", "task-dialog-title", task.title || task.task_id || `Task ${index + 1}`));
    if (task.task_id) identity.append(node("span", "task-dialog-id", task.task_id));
    head.append(identity);
    const open = node("button", "small-button task-dialog-open", "Open task");
    open.type = "button";
    open.addEventListener("click", () => {
      $("#task-dialog").close("select-task");
      selectTaskAt(index);
    });
    head.append(open);
    card.append(head);

    const status = node("div", "task-dialog-status");
    const outcome = evaluatorOutcome(task);
    status.append(makeBadge(`Evaluator · ${outcome.label}`, outcome.tone));
    status.append(makeBadge(taskHasReview(task) ? "Review available" : "Review unavailable", taskHasReview(task) ? "good" : ""));
    card.append(status);

    const counts = taskRecordedCounts(task);
    const facts = node("dl", "task-dialog-facts");
    const factItems = [
      ["Recorded problems", counts ? String(counts.problems) : "Not recorded"],
      ["Unique explicitly flagged steps", counts ? String(counts.flaggedSteps) : "Not recorded"],
      ["Unique recovery steps", counts ? String(counts.recoverySteps) : "Not recorded"],
    ];
    for (const [label, value] of factItems) {
      const fact = node("div", "task-dialog-fact");
      fact.append(node("dt", "", label), node("dd", "", value));
      facts.append(fact);
    }
    card.append(facts);

    const categories = taskCanonicalLabelCounts(task);
    const categorySection = node("div", "task-dialog-categories");
    categorySection.append(node("span", "task-dialog-section-label", "Problems by label"));
    if (categories === null) {
      categorySection.append(node("span", "task-dialog-unrecorded", "Not recorded"));
    } else if (!categories.length) {
      categorySection.append(node("span", "task-dialog-unrecorded", "No problem labels recorded"));
    } else {
      const categoryList = node("div", "task-dialog-category-list");
      for (const category of categories) {
        const pill = applyLabelColor(node("span", "task-dialog-category"), { canonicalId: category.id, label: category.label });
        pill.append(node("span", "", category.label), node("b", "", `${category.count} ${category.count === 1 ? "problem" : "problems"}`));
        categoryList.append(pill);
      }
      categorySection.append(categoryList);
    }
    card.append(categorySection);

    const quick = node("details", "task-dialog-quick");
    const quickCount = counts ? `${counts.problems} recorded ${counts.problems === 1 ? "problem" : "problems"}` : "review points";
    quick.append(node("summary", "", `Steps by problem · ${quickCount}`));
    quick.append(node("p", "task-dialog-help", "Links show recorded flags, recovery and related steps. Repeated flags for one problem do not count as new problems."));
    const points = problemGroups;
    if (!taskHasReview(task)) {
      quick.append(node("p", "task-dialog-no-points", "No review is available, so no problem points are inferred."));
    } else if (!points.length) {
      quick.append(node("p", "task-dialog-no-points", episodes.length ? "No step links were recorded for these problems." : "No problem episodes were recorded."));
    } else {
      const pointList = node("div", "task-dialog-problem-list");
      for (const problem of points) {
        const group = node("section", "task-dialog-problem-group");
        applyLabelColor(group, problem.label);
        const groupHead = node("div", "task-dialog-problem-head");
        groupHead.append(node("span", "task-dialog-point-problem", `Problem ${problem.problem}`), labelChip(problem.label));
        group.append(groupHead);
        const primary = node("div", "task-dialog-point-list");
        const appendPoint = point => {
          const jump = node("button", "task-dialog-point", `${point.roles.join(" · ")} · ${point.stepId}`);
          jump.type = "button";
          jump.disabled = !point.available;
          if (!point.available) jump.setAttribute("aria-label", `Unavailable referenced step ${point.stepId}: ${point.roles.join(" and ")}`);
          jump.addEventListener("click", () => {
            $("#task-dialog").close("select-step");
            selectTaskAt(index, point.stepId);
          });
          return jump;
        };
        for (const point of problem.primary) primary.append(appendPoint(point));
        if (primary.childElementCount) group.append(primary);
        if (problem.related.length) {
          const related = node("details", "task-dialog-related");
          related.append(node("summary", "", `Related steps · ${problem.related.length}`));
          const relatedList = node("div", "task-dialog-point-list");
          for (const point of problem.related) relatedList.append(appendPoint(point));
          related.append(relatedList);
          group.append(related);
        }
        pointList.append(group);
      }
      quick.append(pointList);
    }
    card.append(quick);
    host.append(card);
  }
  updateTaskSearch();
}

function renderTaskList() {
  const tasks = Array.isArray(state.run?.tasks) ? state.run.tasks : [];
  const reviewed = tasks.filter(taskHasReview).length;
  $("#task-picker-position").textContent = tasks.length ? `Task ${state.taskIndex + 1} of ${tasks.length}` : "No tasks";
  $("#task-picker-status").textContent = `${reviewed} of ${tasks.length} tasks have saved review data`;
  const opener = $("#task-picker-open");
  opener.disabled = tasks.length === 0;
  const current = tasks[state.taskIndex];
  $("#sidebar-task-title").textContent = current?.title || current?.task_id || (tasks.length ? "No task selected" : "No tasks available");
  opener.setAttribute("aria-label", current ? `Choose task. Current task ${current.title || current.task_id || state.taskIndex + 1}` : "Choose a task");
  if ($("#task-dialog")?.open) renderTaskDialogList();
}

function activeTask() {
  return state.run?.tasks?.[state.taskIndex] || null;
}

function makeTaskHeader(task) {
  const header = node("header", "task-header");
  const heading = node("div", "task-heading");
  const kicker = node("div", "task-kicker");
  kicker.append(node("span", "eyebrow", task.task_id || `TASK ${state.taskIndex + 1}`));
  if (task.review?.review_kind) kicker.append(makeBadge(task.review.review_kind, statusTone(task.review.review_kind)));
  heading.append(kicker);
  heading.append(node("h1", "", task.title || task.task_id || `Task ${state.taskIndex + 1}`));
  const titleText = String(task.title || "").trim();
  const instructionText = String(task.instruction || "").trim();
  if (instructionText && instructionText !== titleText) heading.append(node("p", "task-instruction", instructionText));
  const badges = node("div", "task-badges");
  badges.append(makeBadge(task.status || "status unavailable", statusTone(task.status)));
  if (task.score !== undefined && task.score !== null) badges.append(makeBadge(`Score ${task.score}`));
  if (task.usage && typeof task.usage === "object") {
    const input = task.usage.input_tokens;
    const output = task.usage.output_tokens;
    if (input !== undefined || output !== undefined) badges.append(makeBadge(`${formatNumber(input)} in · ${formatNumber(output)} out`));
    if (task.usage.estimated_usd !== undefined) badges.append(makeBadge(formatMoney(task.usage.estimated_usd)));
  }
  heading.append(badges);
  header.append(heading);
  return header;
}

function makeOutcome(task) {
  const outcome = valueText(task.outcome, "No outcome was recorded for this task.");
  const card = node("details", "outcome-card");
  const summary = node("summary", "outcome-summary");
  summary.append(node("span", "outcome-icon", "↗"));
  const copy = node("div", "outcome-copy");
  copy.append(node("span", "eyebrow", "RECORDED OUTCOME"));
  const preview = outcome.length > 210 ? `${outcome.slice(0, 207)}...` : outcome;
  copy.append(node("p", "", preview));
  summary.append(copy);
  card.append(summary);
  if (outcome.length > 210) card.append(node("p", "outcome-full", outcome));
  return card;
}

function makeDetailTabs() {
  const tabs = node("nav", "detail-tabs");
  tabs.setAttribute("aria-label", "Task details");
  const choices = [["trajectory", "Trajectory"], ["review", "Review notes"], ["trace", "Agent trace"], ["raw", "Raw data"]];
  for (const [key, label] of choices) {
    const button = node("button", `detail-tab${state.detailTab === key ? " active" : ""}`, label);
    button.type = "button";
    button.addEventListener("click", () => { state.detailTab = key; renderTaskWorkspace(); });
    tabs.append(button);
  }
  return tabs;
}

function taskReviewStep(task, step) {
  const reviewSteps = Array.isArray(task.review?.steps) ? task.review.steps : [];
  return reviewSteps.find(item => String(item.step_id) === String(step?.step_id)) || null;
}

function stepIntentText(value) {
  if (value && typeof value === "object") return value.text || value.description || value.content || value.value || "";
  return value == null ? "" : String(value);
}

// Display wording only. Recorded taxonomy names, IDs and run artifacts stay immutable.
const LABEL_TITLES = {
  "Repeated intended-control activation miss": "Repeated clicks do not activate the target",
  "Unintended control activation": "Wrong control activated",
  "Persistent modal after dismissal attempts": "Dialog stays open after attempts to close it",
  "Network-path resource blockage": "Network error blocks the page",
  "Malformed command-entry sequence": "Command entered incorrectly",
  "Retrieved scope mismatch": "Result does not match the requested information",
  "Entry into still-focused wrong field": "Text entered in the wrong field",
  "Dialog abandoned before correction and confirmation": "Dialog left unfinished",
};
const STEP_ROLES = {
  recovery: ["Recovery step", "The reviewer links this step to an attempt to fix the problem or evidence of recovery. Check the recovery status below; a linked step does not by itself prove success."],
  context: ["Related step", "The reviewer links this step to the same problem, without marking it as a new starting point or recovery step."],
};
function displayLabel(name) { return LABEL_TITLES[name] || name; }
function problemOrigin(task, episode) {
  const explicit = new Set((episode.onset_step_ids || []).map(String));
  const firstFlagged = (task.steps || []).find(step => explicit.has(String(step.step_id)))?.step_id;
  const recorded = task.review?.schema_version === "2" && episode.first_observed_step_id != null;
  return {
    stepId: recorded ? episode.first_observed_step_id : firstFlagged,
    term: recorded ? "First observed" : "First flagged",
    recorded,
  };
}
function originText(task, episode) {
  const origin = problemOrigin(task, episode);
  return origin.stepId == null ? "First step not recorded" : `${origin.term} at step ${origin.stepId}`;
}
function stepRole(kind, task, episode, step) {
  if (kind !== "onset") return STEP_ROLES[kind];
  const origin = problemOrigin(task, episode);
  const isFirst = origin.stepId != null && String(origin.stepId) === String(step.step_id);
  if (isFirst) return [
    `${origin.term} here`,
    `This is the first step ${origin.recorded ? "identified by the agent" : "explicitly flagged in the saved review"} for this problem. It may have begun earlier; this does not prove the action caused it.`,
  ];
  return [origin.recorded ? "Also observed here" : "Also flagged here",
    `The same numbered problem is flagged at this step. ${originText(task, episode)}. This is not a new problem.`];
}
function roleBadge(kind, task, episode, step) {
  return node("span", `episode-kind ${kind}`, stepRole(kind, task, episode, step)[0]);
}
function flaggedStepText(task, episode, stepId) {
  const origin = problemOrigin(task, episode);
  return `${String(origin.stepId) === String(stepId) ? origin.term : origin.recorded ? "Also observed" : "Also flagged"} · Step ${stepId}`;
}
function originJump(task, episode, step) {
  const origin = problemOrigin(task, episode);
  const button = node("button", "small-button problem-origin-jump", `${originText(task, episode)}${String(origin.stepId) === String(step?.step_id) ? " · this step" : " ↗"}`);
  button.type = "button";
  button.disabled = origin.stepId == null || String(origin.stepId) === String(step?.step_id)
    || !(task.steps || []).some(item => String(item.step_id) === String(origin.stepId));
  button.addEventListener("click", () => jumpToStep(task, origin.stepId));
  return button;
}
function labelColor(key) {
  const canonical = /^c(\d+)$/i.exec(String(key));
  if (canonical) return (Number(canonical[1]) - 1) % 8;
  return [...String(key)].reduce((hash, char) => (hash * 31 + char.charCodeAt(0)) >>> 0, 0) % 8;
}
function applyLabelColor(element, resolved) {
  element.classList.add(`label-color-${labelColor(resolved.canonicalId || resolved.proposalId || resolved.originalName || resolved.label)}`);
  return element;
}
function labelChip(resolved) {
  const chip = applyLabelColor(node("span", "label-chip"), resolved);
  const code = resolved.canonicalId || resolved.proposalId;
  if (code) chip.append(node("span", "label-code", String(code).toUpperCase()));
  chip.append(node("span", "label-chip-text", resolved.label));
  return chip;
}
function problemNumber(task, episode) {
  if (task.review?.schema_version === "2" && Number.isInteger(episode.problem_number) && episode.problem_number > 0) return episode.problem_number;
  return (task.review?.episodes || []).findIndex(item => item === episode || item.episode_id === episode.episode_id) + 1;
}
function jumpToProblem(number) {
  const card = $(`#problem-card-${number}`);
  if (!card) return;
  card.focus({ preventScroll: true });
  const toolbarHeight = $(".step-toolbar")?.offsetHeight || 0;
  window.scrollTo({ top: window.scrollY + card.getBoundingClientRect().top - toolbarHeight - 12, behavior: "instant" });
}

function episodeLabel(episode) {
  const taxonomy = state.run?.taxonomy || {};
  const mapping = (taxonomy.deduplication?.mappings || []).find(item => String(item.proposal_id) === String(episode.label_id));
  const canonical = (taxonomy.labels || []).find(label => String(label.id) === String(mapping?.canonical_label_id ?? episode.label_id));
  const proposal = (taxonomy.proposals || []).find(item => String(item.id) === String(episode.label_id));
  const draftName = proposal?.name || (episode.label_id && episode.label_name);
  const originalName = canonical?.name || draftName || `Unclassified: ${episode.mechanism || episode.episode_id || "episode"}`;
  return {
    label: displayLabel(originalName),
    originalName,
    proposalId: proposal?.id || episode.label_id || null,
    description: canonical?.description || proposal?.description || "No label definition was recorded. This problem has not been classified yet.",
    canonical: Boolean(canonical),
    classification: canonical ? "Canonical draft" : draftName ? "Draft proposal" : "Unclassified",
    canonicalId: canonical?.id || mapping?.canonical_label_id || null,
  };
}

function containsId(values, id) {
  return id !== undefined && id !== null && Array.isArray(values) && values.some(value => String(value) === String(id));
}

function episodesForStep(task, step, reviewStep = taskReviewStep(task, step)) {
  const episodes = Array.isArray(task.review?.episodes) ? task.review.episodes : [];
  const explicitRefs = [
    ...(Array.isArray(step.episode_refs) ? step.episode_refs : []),
    ...(Array.isArray(reviewStep?.episode_refs) ? reviewStep.episode_refs : []),
  ].map(String);
  return episodes.map(episode => {
    const kinds = [];
    if (containsId(episode.onset_step_ids, step.step_id)) kinds.push("onset");
    if (containsId(episode.recovery?.step_ids, step.step_id)) kinds.push("recovery");
    if (kinds.length === 0 && episode.episode_id != null && explicitRefs.includes(String(episode.episode_id))) kinds.push("context");
    return { episode, kinds };
  }).filter(item => item.kinds.length > 0);
}

function alignStepView(focusSelector) {
  const anchor = $("#step-view");
  if (!anchor) return;
  const focus = focusSelector ? $(focusSelector) : anchor;
  (focus && !focus.disabled ? focus : anchor).focus({ preventScroll: true });
  // Explicit navigation snaps to one stable anchor before paint. Ordinary reading scroll is free.
  window.scrollTo({ top: window.scrollY + anchor.getBoundingClientRect().top, behavior: "instant" });
}
function selectStep(task, index, focusSelector) {
  if (index < 0 || index >= (task.steps || []).length) return;
  state.stepIndex = index;
  state.detailTab = "trajectory";
  renderTaskWorkspace();
  alignStepView(focusSelector);
}
function selectTaskAt(taskIndex, stepId) {
  const tasks = Array.isArray(state.run?.tasks) ? state.run.tasks : [];
  const task = tasks[taskIndex];
  if (!task) return;
  state.taskIndex = taskIndex;
  state.detailTab = "trajectory";
  state.stepIndex = 0;
  if (stepId !== undefined && stepId !== null) {
    const targetIndex = (task.steps || []).findIndex(step => String(step.step_id) === String(stepId));
    if (targetIndex >= 0) state.stepIndex = targetIndex;
  }
  renderTaskList();
  renderTaskWorkspace();
  if ((task.steps || []).length) alignStepView();
  else requestAnimationFrame(() => $("#task-workspace").scrollIntoView({ block: "start", behavior: "instant" }));
}
function jumpToStep(task, stepId) {
  const index = (task.steps || []).findIndex(item => String(item.step_id) === String(stepId));
  selectStep(task, index);
}

function renderEpisodeOverview(task) {
  const section = node("details", "episode-overview");
  const episodes = Array.isArray(task.review?.episodes) ? task.review.episodes : [];
  const summary = node("summary", "episode-overview-summary", `${episodes.length} ${episodes.length === 1 ? "problem" : "problems"} · First flags, related steps and recovery`);
  section.append(summary);
  if (!episodes.length) {
    section.append(node("p", "episode-overview-note", "No episodes were recorded. Steps without explicit episode links are not classified as failure-free."));
    return section;
  }
  section.append(node("p", "episode-overview-note", "Each problem keeps the same number across its flagged and recovery steps. The first flag is the earliest recorded evidence, not necessarily when the problem began."));
  const list = node("div", "episode-overview-list");
  for (const episode of episodes) {
    const row = node("div", "episode-overview-row");
    const copy = node("div", "episode-overview-label");
    const resolved = episodeLabel(episode);
    copy.append(node("strong", "", `Problem ${problemNumber(task, episode)}`), labelChip(resolved), node("span", "problem-origin", originText(task, episode)));
    copy.append(node("span", "", `${episode.episode_id || "Episode"} · recovery ${episode.recovery?.status || "not recorded"}`));
    row.append(copy);
    const jumps = node("div", "episode-overview-jumps");
    for (const stepId of episode.onset_step_ids || []) {
      const button = node("button", "episode-jump onset-jump", flaggedStepText(task, episode, stepId));
      button.type = "button";
      button.disabled = !(task.steps || []).some(item => String(item.step_id) === String(stepId));
      button.addEventListener("click", () => jumpToStep(task, stepId));
      jumps.append(button);
    }
    for (const stepId of episode.recovery?.step_ids || []) {
      const button = node("button", "episode-jump recovery-jump", `Recovery · Step ${stepId}`);
      button.title = `Jump to the recorded recovery at step ${stepId}`;
      button.type = "button";
      button.disabled = !(task.steps || []).some(item => String(item.step_id) === String(stepId));
      button.addEventListener("click", () => jumpToStep(task, stepId));
      jumps.append(button);
    }
    row.append(jumps);
    list.append(row);
  }
  section.append(list);
  return section;
}

function renderEvidence(parent, refs, label = "Evidence") {
  if (!Array.isArray(refs) || refs.length === 0) return;
  const block = node("div", "field-block");
  block.append(node("div", "field-label", label));
  const row = node("div", "evidence-list");
  for (const ref of refs) row.append(node("span", "evidence-chip", valueText(ref)));
  block.append(row);
  parent.append(block);
}

function renderSidebarSteps(task) {
  const steps = Array.isArray(task?.steps) ? task.steps : [];
  const stepSidebar = $("#sidebar-steps");
  const previousScroll = $(".step-list", stepSidebar)?.scrollTop || 0;
  stepSidebar.replaceChildren();
  const stepSidebarHead = node("div", "step-sidebar-head");
  stepSidebarHead.append(node("strong", "", "Trajectory steps"), node("span", "", `${steps.length} steps`));
  stepSidebar.append(stepSidebarHead);
  stepSidebar.append(node("p", "step-sidebar-note", "Colored labels name each problem. Separate badges show this step’s role."));
  const stepList = node("div", "step-list");
  for (const [index, item] of steps.entries()) {
    const itemReview = taskReviewStep(task, item);
    const linkedEpisodes = episodesForStep(task, item, itemReview);
    const row = node("button", `step-row${index === state.stepIndex ? " active" : ""}`);
    row.type = "button";
    row.setAttribute("aria-current", index === state.stepIndex ? "step" : "false");
    const number = node("span", "step-row-number", String(item.step_id ?? index + 1).padStart(2, "0"));
    row.append(number);
    const copy = node("span", "step-row-copy");
    const preview = String(
      stepIntentText(itemReview?.intent)
      || itemReview?.action
      || stepIntentText(item.intent)
      || (item.action ? "Source action recorded; select for details" : "Step details not recorded")
    ).replace(/\s+/g, " ").trim();
    copy.append(node("span", "step-row-action", preview.length > 116 ? `${preview.slice(0, 113)}...` : preview));
    if (linkedEpisodes.length) {
      if (linkedEpisodes.length > 1) copy.append(node("span", "problem-count", `${linkedEpisodes.length} linked problems`));
      const marks = node("span", "step-episode-marks");
      for (const { episode, kinds } of linkedEpisodes) {
        const resolved = episodeLabel(episode);
        const group = applyLabelColor(node("span", "step-episode-mark"), resolved);
        group.append(node("span", "problem-number", `Problem ${problemNumber(task, episode)}`));
        group.append(node("span", "problem-origin", originText(task, episode)));
        group.append(labelChip(resolved));
        const roles = node("span", "problem-roles");
        for (const kind of kinds) roles.append(roleBadge(kind, task, episode, item));
        group.append(roles);
        marks.append(group);
      }
      copy.append(marks);
    } else {
      copy.append(node("span", "step-unlinked", "No problem linked"));
    }
    row.append(copy);
    row.id = `step-link-${index}`;
    row.addEventListener("click", () => selectStep(task, index, `#step-link-${index}`));
    stepList.append(row);
  }
  stepSidebar.append(stepList);
  stepList.scrollTop = previousScroll;
  const activeRow = stepList.children[state.stepIndex];
  if (activeRow) requestAnimationFrame(() => {
    const top = activeRow.getBoundingClientRect().top - stepList.getBoundingClientRect().top + stepList.scrollTop;
    if (top < stepList.scrollTop) stepList.scrollTop = top;
    else if (top + activeRow.offsetHeight > stepList.scrollTop + stepList.clientHeight)
      stepList.scrollTop = top + activeRow.offsetHeight - stepList.clientHeight;
  });


}

function renderTrajectory(task) {
  const panel = node("section", "detail-panel");
  const steps = Array.isArray(task.steps) ? task.steps : [];
  if (!steps.length) {
    panel.append(node("div", "empty-state", "This task has no recorded interaction steps."));
    return panel;
  }
  state.stepIndex = Math.min(Math.max(state.stepIndex, 0), steps.length - 1);
  const step = steps[state.stepIndex];
  const reviewStep = taskReviewStep(task, step);
  const layout = node("div", "trajectory-layout");

  const main = node("div", "step-main");
  main.id = "step-view";
  main.tabIndex = -1;
  const toolbar = node("div", "step-toolbar");
  const count = node("span", "step-count");
  count.append(node("strong", "", `Step ${step.step_id ?? state.stepIndex + 1}`), document.createTextNode(` · ${state.stepIndex + 1} of ${steps.length}`));
  toolbar.append(count);

  const navigation = node("div", "step-nav");
  const previous = node("button", "small-button", "← Previous step");
  previous.type = "button"; previous.disabled = state.stepIndex === 0;
  previous.id = "previous-step";
  previous.addEventListener("click", () => selectStep(task, state.stepIndex - 1, "#previous-step"));
  const next = node("button", "small-button", "Next step →");
  next.type = "button"; next.disabled = state.stepIndex >= steps.length - 1;
  next.id = "next-step";
  next.addEventListener("click", () => selectStep(task, state.stepIndex + 1, "#next-step"));
  const screen = node("button", "small-button", "Screen ↑");
  screen.type = "button";
  screen.setAttribute("aria-label", "View selected step screenshot");
  screen.addEventListener("click", () => alignStepView());
  navigation.append(screen, previous, next); toolbar.append(navigation); main.append(toolbar);

  const content = node("div", "step-content-grid");
  const screenshot = node("section", "screenshot-card");
  const shotHead = node("div", "card-heading");
  shotHead.append(node("strong", "", "Captured screen"));
  shotHead.append(node("span", "spacer"));
  const reviewerSawFrame = step.step_id !== undefined && step.step_id !== null
    && Array.isArray(task.attached_frame_steps)
    && task.attached_frame_steps.some(id => String(id) === String(step.step_id));
  const coverageBadge = makeBadge(
    reviewerSawFrame ? "Inspected by reviewer" : step.screenshot ? "Available to viewer, not supplied to reviewer" : "Screenshot missing",
    reviewerSawFrame ? "good" : "warn"
  );
  coverageBadge.classList.add("screenshot-coverage");
  shotHead.append(coverageBadge);
  if (step.screenshot) {
    const shotUrl = screenshotPath(step.screenshot);
    if (shotUrl) shotHead.append(makeLink("Open image ↗", shotUrl));
  }
  screenshot.append(shotHead);
  const stage = node("div", "screenshot-stage");
  const shotUrl = screenshotPath(step.screenshot);
  if (shotUrl) {
    const image = document.createElement("img");
    image.src = shotUrl;
    image.alt = `Screenshot for step ${step.step_id ?? state.stepIndex + 1}`;
    image.addEventListener("error", () => {
      stage.replaceChildren();
      const empty = node("div", "empty-visual");
      empty.append(node("span", "", "▧"), node("strong", "", "Screenshot could not be loaded"), node("p", "", valueText(step.screenshot)));
      stage.append(empty);
    }, { once: true });
    stage.append(image);
  } else {
    const empty = node("div", "empty-visual");
    empty.append(node("span", "", "▧"), node("strong", "", "No screenshot for this step"), node("p", "", "This run may include steps without a captured screen."));
    stage.append(empty);
  }
  screenshot.append(stage);

  const annotation = node("section", "annotation-card");
  const annHead = node("div", "annotation-head");
  annHead.append(node("strong", "", "Step annotation"));
  if (step.step_id !== undefined) annHead.append(node("span", "step-id", valueText(step.step_id)));
  annotation.append(annHead);
  appendField(annotation, "Source intent", step.intent);
  appendField(annotation, "Source action", step.action);
  appendField(annotation, "Source observation", step.observation);
  renderEvidence(annotation, step.evidence_refs, "Source evidence");
  if (reviewStep) {
    const inference = node("section", "review-inference");
    inference.append(node("div", "review-inference-title", "Reviewer interpretation"));
    const intent = reviewStep.intent;
    const intentKind = reviewStep.intent_kind || reviewStep.intent_type
      || (intent && typeof intent === "object" ? (intent.kind || intent.type) : undefined);
    const intentText = intent && typeof intent === "object"
      ? (intent.text ?? intent.description ?? intent.content ?? intent.value ?? intent)
      : intent;
    appendField(inference, "Intent kind", intentKind);
    appendField(inference, "Reviewer intent", intentText);
    appendField(inference, "Reviewer action", reviewStep.action);
    appendField(inference, "Observed UI", reviewStep.observed_ui);
    appendField(inference, "Effect", reviewStep.effect);
    appendField(inference, "Assessment", reviewStep.assessment);
    renderEvidence(inference, reviewStep.evidence_refs, "Reviewer evidence");
    annotation.append(inference);
  }
  content.append(screenshot, renderStepEpisodeContext(task, step, reviewStep), annotation);
  main.append(content);
  layout.append(main);
  panel.append(layout);
  return panel;
}

function renderStepEpisodeContext(task, step, reviewStep) {
  const section = node("section", "step-episode-context");
  const linkedEpisodes = episodesForStep(task, step, reviewStep);
  const heading = node("div", "step-episode-context-head");
  heading.append(node("h2", "", "Labels on this step"));
  const limitedEvidence = reviewStep?.review_status === "insufficient_evidence";
  const reviewStatus = limitedEvidence ? "Limited evidence" : reviewStep?.review_status === "reviewed" ? "Reviewed by model" : valueText(reviewStep?.review_status, "Not reviewed").replaceAll("_", " ");
  heading.append(makeBadge(reviewStatus, limitedEvidence ? "warn" : ""));
  section.append(heading);
  if (limitedEvidence) section.append(node("p", "evidence-note", "The model had limited evidence for this step. Treat its links and explanation as provisional."));
  if (!linkedEpisodes.length) {
    const empty = node("div", "step-no-episode");
    empty.append(node("strong", "", "No problem linked"));
    empty.append(node("p", "", "The reviewer did not link this step to a problem or recovery. That does not prove the step is error-free."));
    section.append(empty);
    return section;
  }
  section.append(node("p", "problem-summary-note", `${linkedEpisodes.length} linked ${linkedEpisodes.length === 1 ? "problem" : "problems"}. Colors identify labels, not severity. Each problem has its own step role and recovery status.`));
  if (linkedEpisodes.length > 1) {
    const overview = node("nav", "step-problem-overview");
    overview.setAttribute("aria-label", "Problems linked to this step");
    for (const { episode, kinds } of linkedEpisodes) {
      const number = problemNumber(task, episode);
      const resolved = episodeLabel(episode);
      const item = applyLabelColor(node("article", "problem-summary-item"), resolved);
      item.append(node("span", "problem-number", `Problem ${number}`), originJump(task, episode, step), labelChip(resolved));
      const roles = node("span", "problem-roles");
      kinds.forEach(kind => roles.append(roleBadge(kind, task, episode, step)));
      const jump = node("button", "small-button problem-summary-link", "Read explanation ↓");
      jump.type = "button";
      jump.setAttribute("aria-label", `Read explanation for Problem ${number}`);
      jump.addEventListener("click", () => jumpToProblem(number));
      item.append(roles, jump);
      overview.append(item);
    }
    section.append(overview);
  }
  for (const { episode, kinds } of linkedEpisodes) {
    const resolved = episodeLabel(episode);
    const number = problemNumber(task, episode);
    const card = applyLabelColor(node("article", "step-episode-card"), resolved);
    card.id = `problem-card-${number}`;
    card.tabIndex = -1;
    card.setAttribute("aria-label", `Problem ${number}: ${resolved.label}`);
    const header = node("div", "step-episode-card-head");
    header.append(node("h3", "problem-card-number", `Problem ${number}`), makeBadge(resolved.classification));
    card.append(header, originJump(task, episode, step), labelChip(resolved));
    const roles = node("div", "problem-roles");
    kinds.forEach(kind => roles.append(roleBadge(kind, task, episode, step)));
    card.append(roles);
    const definition = node("p", "label-definition");
    definition.append(node("b", "", "Meaning: "), document.createTextNode(resolved.description));
    card.append(definition);
    const role = node("p", "step-episode-meta");
    role.append(node("b", "", "This step: "), document.createTextNode(kinds.map(kind => stepRole(kind, task, episode, step)[1]).join(" ")));
    card.append(role);
    const recorded = node("details", "recorded-label");
    recorded.append(node("summary", "", `Recorded label · ${resolved.canonicalId || episode.label_id || "unclassified"}`));
    recorded.append(node("p", "", resolved.originalName));
    recorded.append(node("p", "", `Episode ${episode.episode_id || "not recorded"} · ${task.review?.schema_version === "2" ? "Problem number and first observed step recorded by the agent." : "Legacy review: problem number follows saved episode order; first flagged step is derived from explicit flagged IDs."}`));
    card.append(recorded);
    if (episode.mechanism && episode.mechanism !== resolved.label) {
      const mechanism = node("p", "step-episode-meta");
      mechanism.append(node("b", "", "What happened: "), document.createTextNode(episode.mechanism));
      card.append(mechanism);
    }
    const recovery = node("p", "step-episode-meta");
    recovery.append(node("b", "", "Recovery status: "), document.createTextNode(valueText(episode.recovery?.status, "not recorded").replaceAll("_", " ")));
    card.append(recovery);
    if (episode.recovery?.rationale) {
      const rationale = node("p", "step-episode-meta");
      rationale.append(node("b", "", "Why this recovery status: "), document.createTextNode(episode.recovery.rationale));
      card.append(rationale);
    }
    if (episode.uncertainty) {
      const uncertainty = node("p", "step-episode-meta");
      uncertainty.append(node("b", "", "Uncertainty: "), document.createTextNode(episode.uncertainty));
      card.append(uncertainty);
    }
    renderEvidence(card, episode.evidence_refs, "Episode evidence");
    if (episode.recovery?.evidence_refs?.length) renderEvidence(card, episode.recovery.evidence_refs, "Recovery evidence");
    const jumps = node("div", "step-episode-jumps");
    for (const stepId of episode.onset_step_ids || []) {
      const jump = node("button", "episode-jump onset-jump", flaggedStepText(task, episode, stepId));
      jump.type = "button";
      jump.disabled = !(task.steps || []).some(item => String(item.step_id) === String(stepId));
      jump.addEventListener("click", () => jumpToStep(task, stepId));
      jumps.append(jump);
    }
    for (const stepId of episode.recovery?.step_ids || []) {
      const jump = node("button", "episode-jump recovery-jump", `Recovery · Step ${stepId}`);
      jump.title = `Jump to the recorded recovery at step ${stepId}`;
      jump.type = "button";
      jump.disabled = !(task.steps || []).some(item => String(item.step_id) === String(stepId));
      jump.addEventListener("click", () => jumpToStep(task, stepId));
      jumps.append(jump);
    }
    if (jumps.childElementCount) card.append(jumps);
    section.append(card);
  }
  return section;
}

function renderReview(task) {
  const panel = node("section", "detail-panel");
  const review = task.review || {};
  const summary = node("div", "review-summary");
  summary.append(node("strong", "", review.review_kind ? `Review summary · ${review.review_kind}` : "Review summary"));
  summary.append(document.createTextNode(valueText(review.summary, "No summary was recorded for this review.")));
  panel.append(summary);

  const items = Array.isArray(review.steps) ? review.steps : [];
  if (items.length) {
    const grid = node("div", "review-grid");
    for (const item of items) {
      const card = node("article", "review-step");
      const head = node("div", "review-step-head");
      const jump = node("button", "small-button", `Step ${valueText(item.step_id, "not identified")}`);
      jump.type = "button";
      const index = (task.steps || []).findIndex(step => String(step.step_id) === String(item.step_id));
      jump.disabled = index < 0;
      jump.addEventListener("click", () => selectStep(task, index));
      head.append(jump, makeBadge(item.review_status || "unmarked", statusTone(item.review_status)));
      card.append(head);
      const fields = node("div", "review-fields");
      appendField(fields, "Intent", item.intent);
      appendField(fields, "Action", item.action);
      appendField(fields, "Observed UI", item.observed_ui);
      appendField(fields, "Effect", item.effect);
      const assessment = node("div", "assessment");
      appendField(assessment, "Assessment", item.assessment);
      fields.append(assessment);
      card.append(fields);
      renderEvidence(card, item.evidence_refs);
      grid.append(card);
    }
    panel.append(grid);
  } else panel.append(node("div", "empty-state", "No step-level review notes were recorded."));

  const episodes = Array.isArray(review.episodes) ? review.episodes : [];
  const section = node("section", "episodes");
  const title = node("h2", "section-title", "Episodes");
  title.append(node("span", "", String(episodes.length)));
  section.append(title);
  if (!episodes.length) section.append(node("div", "empty-state", "No episodes recorded for this task."));
  for (const episode of episodes) {
    const card = node("article", "episode-card");
    const top = node("div", "episode-top");
    top.append(node("span", "problem-number", `Problem ${problemNumber(task, episode)}`), labelChip(episodeLabel(episode)));
    top.append(makeBadge(episode.recovery?.status || "recovery not recorded", statusTone(episode.recovery?.status)));
    card.append(top, originJump(task, episode));
    const meta = node("div", "episode-meta");
    const proposal = episode.label_id === undefined || episode.label_id === null ? null
      : (state.run?.taxonomy?.proposals || []).find(item => String(item.id) === String(episode.label_id));
    const mapping = episode.label_id === undefined || episode.label_id === null ? null
      : (state.run?.taxonomy?.deduplication?.mappings || []).find(item => String(item.proposal_id) === String(episode.label_id));
    const canonical = mapping && (state.run?.taxonomy?.labels || []).find(label => String(label.id) === String(mapping.canonical_label_id));
    meta.append(node("span", "", "Original proposal: "), node("b", "", valueText(episode.label_name || proposal?.name || episode.label_id, "Not recorded")), document.createTextNode(" · Canonical draft: "), node("b", "", canonical?.name || (mapping ? valueText(mapping.canonical_label_id) : "No canonical mapping")));
    card.append(meta);
    const mechanism = node("div", "episode-meta");
    mechanism.append(node("span", "", "Mechanism: "), node("b", "", valueText(episode.mechanism, "Not recorded")), document.createTextNode(" · Flagged steps: "), node("b", "", valueText(episode.onset_step_ids, "Not recorded")));
    card.append(mechanism);
    const recovery = node("div", "episode-meta");
    recovery.append(node("span", "", "Recovery steps: "), node("b", "", valueText(episode.recovery?.step_ids, "Not recorded")), document.createTextNode(" · Outcome contribution: "), node("b", "", valueText(episode.outcome_contribution, "Not recorded")));
    card.append(recovery);
    const recoveryRationale = node("div", "episode-meta");
    recoveryRationale.append(node("span", "", "Why this recovery status: "), node("b", "", valueText(episode.recovery?.rationale, "Not recorded")));
    card.append(recoveryRationale);
    const uncertainty = node("div", "episode-meta");
    uncertainty.append(node("span", "", "Uncertainty: "), node("b", "", valueText(episode.uncertainty, "Not recorded")));
    card.append(uncertainty);
    renderEvidence(card, episode.evidence_refs || episode.recovery?.evidence_refs);
    section.append(card);
  }
  panel.append(section);
  return panel;
}

function renderTrace(task) {
  const panel = node("section", "detail-panel");
  const entries = Array.isArray(task.agent_trace) ? task.agent_trace : [];
  if (!entries.length) {
    panel.append(node("div", "empty-state", "No visible agent trace events were recorded for this task."));
    return panel;
  }
  const list = node("div", "trace-list");
  for (const [index, entry] of entries.entries()) {
    const item = node("article", "trace-entry");
    item.append(node("span", "trace-index", String(index + 1).padStart(2, "0")));
    const body = node("div", "trace-body");
    const meta = node("div", "trace-meta");
    meta.append(node("strong", "", entry.type || "event"));
    if (entry.at) meta.append(node("span", "trace-time", formatDate(entry.at)));
    body.append(meta);
    body.append(node("p", "", valueText(entry.text, "Trace event has no text payload.")));
    item.append(body);
    list.append(item);
  }
  panel.append(list);
  return panel;
}

function collectArtifactLinks(task) {
  const links = [{ label: "Run JSON", path: RUN_URL }];
  const fields = [["review_yaml", "Review YAML"], ["review_json", "Review JSON"], ["agent_jsonl", "Agent trace JSONL"]];
  for (const [key, label] of fields) {
    const path = task.artifacts?.[key];
    if (path) links.push({ label, path });
  }
  const sourceArtifacts = [["task_definition", "Task definition"], ["trajectory", "Trajectory"], ["score_file", "Score file"], ["provenance_file", "Provenance file"]];
  for (const [key, label] of sourceArtifacts) {
    const path = task.source?.[key];
    if (typeof path === "string" && path.trim()) links.push({ label, path });
  }
  const visitSource = (value, prefix = "source") => {
    if (typeof value === "string" && /^https?:\/\//i.test(value)) links.push({ label: prefix.replaceAll("_", " "), path: value });
    else if (Array.isArray(value)) value.forEach((item, index) => visitSource(item, `${prefix} ${index + 1}`));
    else if (value && typeof value === "object") {
      for (const [key, child] of Object.entries(value)) visitSource(child, `${prefix} · ${key}`);
    }
  };
  visitSource(task.source || {});
  return links;
}

function renderRaw(task) {
  const panel = node("section", "detail-panel");
  const toolbar = node("div", "raw-toolbar");
  toolbar.append(node("span", "eyebrow", "RECORDED ARTIFACTS"), node("span", "spacer"));
  if (state.rawTaskUrl) URL.revokeObjectURL(state.rawTaskUrl);
  state.rawTaskUrl = URL.createObjectURL(new Blob([JSON.stringify(task, null, 2)], { type: "application/json" }));
  const download = makeLink("Selected task JSON ↓", state.rawTaskUrl, "small-button");
  download.download = `${task.task_id || "task"}.json`;
  toolbar.append(download);
  panel.append(toolbar);
  const links = node("div", "evidence-list");
  for (const item of collectArtifactLinks(task)) {
    const href = internalArtifactPath(item.path);
    if (href) links.append(makeLink(`${item.label} ↗`, href, "small-button"));
  }
  panel.append(links);
  panel.append(node("div", "field-block"));
  panel.lastChild.append(node("div", "field-label", "Selected task data"));
  panel.append(node("pre", "raw-output", JSON.stringify(task, null, 2)));
  return panel;
}

function renderTaskWorkspace() {
  const host = $("#task-workspace");
  const previousScroll = window.scrollY;
  if (state.rawTaskUrl) {
    URL.revokeObjectURL(state.rawTaskUrl);
    state.rawTaskUrl = null;
  }
  host.replaceChildren();
  const task = activeTask();
  if (!task) {
    const empty = node("div", "empty-state");
    empty.append(node("strong", "", state.run?.tasks?.length ? "Choose a task" : "No task records in this batch"));
    empty.append(document.createTextNode(" Interaction, review, and source fields will appear here when available."));
    host.append(empty);
    return;
  }
  renderSidebarSteps(task);
  host.append(makeTaskHeader(task), makeOutcome(task));
  if (state.detailTab === "trajectory") host.append(renderEpisodeOverview(task));
  host.append(makeDetailTabs());
  const content = state.detailTab === "review" ? renderReview(task)
    : state.detailTab === "trace" ? renderTrace(task)
      : state.detailTab === "raw" ? renderRaw(task)
        : renderTrajectory(task);
  host.append(content);
  window.scrollTo({ top: previousScroll, behavior: "instant" });
}

function renderTaxonomy() {
  const host = $("#taxonomy-content");
  host.replaceChildren();
  const taxonomy = state.run?.taxonomy || {};
  const labels = Array.isArray(taxonomy.labels) ? taxonomy.labels : [];
  const proposals = Array.isArray(taxonomy.proposals) ? taxonomy.proposals : [];
  const dedup = taxonomy.deduplication || {};
  $("#proposal-count").textContent = String(proposals.length);

  const head = node("header", "taxonomy-head");
  const intro = node("div");
  intro.append(node("span", "eyebrow", "SHARED TAXONOMY"), node("h1", "", "Labels & deduplication"));
  const taxonomyMeta = node("div", "taxonomy-meta");
  if (taxonomy.candidate_version !== undefined && taxonomy.candidate_version !== null) {
    const candidateVersion = String(taxonomy.candidate_version).replace(/^v/i, "");
    taxonomyMeta.append(makeBadge(`Candidate taxonomy v${candidateVersion}`));
  }
  if (taxonomy.status) taxonomyMeta.append(makeBadge(taxonomy.status, statusTone(taxonomy.status)));
  if (taxonomy.pool_version) taxonomyMeta.append(makeBadge(`Pool ${taxonomy.pool_version}`));
  intro.append(taxonomyMeta);
  head.append(intro, node("p", "", "Review the batch’s shared vocabulary, incoming label proposals, and recorded canonical mappings. This view is read-only."));
  host.append(head);
  const grid = node("div", "taxonomy-grid");

  const labelPanel = node("section", "taxonomy-panel");
  const labelHead = node("div", "taxonomy-panel-head");
  labelHead.append(node("h2", "", "Canonical labels"), node("span", "", String(labels.length)));
  labelPanel.append(labelHead);
  if (!labels.length) labelPanel.append(node("div", "empty-state", "No canonical labels were included in this run."));
  labels.forEach((label, index) => {
    const row = node("article", "label-row");
    const swatch = node("span", "label-swatch");
    applyLabelColor(swatch, { canonicalId: label.id, label: label.name });
    swatch.style.background = "var(--label-color)";
    row.append(swatch);
    const copy = node("div");
    copy.append(labelChip({ label: displayLabel(label.name) || label.id || "Unnamed label", canonicalId: label.id }));
    if (displayLabel(label.name) !== label.name) copy.append(node("div", "label-id", `Recorded name: ${label.name}`));
    copy.append(node("div", "label-id", `${valueText(label.id, "no id")}${label.status ? ` · ${label.status}` : ""}`));
    copy.append(node("div", "label-description", valueText(label.description, "No description")));
    if (Array.isArray(label.aliases) && label.aliases.length) {
      const aliases = node("div", "alias-row");
      label.aliases.forEach(alias => aliases.append(node("span", "evidence-chip", alias)));
      copy.append(aliases);
    }
    row.append(copy);
    labelPanel.append(row);
  });
  grid.append(labelPanel);

  const rightColumn = node("div");
  const proposalPanel = node("section", "taxonomy-panel");
  const proposalHead = node("div", "taxonomy-panel-head");
  proposalHead.append(node("h2", "", "Label proposals"), node("span", "", String(proposals.length)));
  proposalPanel.append(proposalHead);
  if (!proposals.length) proposalPanel.append(node("div", "empty-state", "No pending label proposals in this batch."));
  for (const proposal of proposals) {
    const card = node("article", "proposal-card");
    const top = node("div", "proposal-top");
    top.append(node("strong", "", proposal.name || proposal.id || "Unnamed proposal"));
    if (proposal.type) top.append(makeBadge(proposal.type, statusTone(proposal.type)));
    if (proposal.status) top.append(makeBadge(proposal.status, statusTone(proposal.status)));
    card.append(top);
    const baseVersion = proposal.base_version === undefined || proposal.base_version === null
      ? null : String(proposal.base_version).replace(/^v/i, "");
    const proposalMeta = [proposal.id && `id ${proposal.id}`, proposal.target_label_id && `target ${proposal.target_label_id}`, baseVersion !== null && `base v${baseVersion}`].filter(Boolean).join(" · ");
    if (proposalMeta) card.append(node("p", "", proposalMeta));
    card.append(node("p", "", valueText(proposal.description, "No description")));
    const provenance = [proposal.task_id, proposal.episode_id].filter(Boolean).join(" · ");
    if (provenance) card.append(node("p", "", provenance));
    proposalPanel.append(card);
  }
  rightColumn.append(proposalPanel);

  const dedupPanel = node("section", "taxonomy-panel");
  dedupPanel.style.marginTop = "12px";
  const dedupHead = node("div", "taxonomy-panel-head");
  const mappings = Array.isArray(dedup.mappings) ? dedup.mappings : [];
  const trace = Array.isArray(dedup.trace) ? dedup.trace : [];
  dedupHead.append(node("h2", "", "Deduplication"), node("span", "", `${mappings.length} mappings`));
  dedupPanel.append(dedupHead);
  if (dedup.summary) dedupPanel.append(node("div", "dedup-summary", dedup.summary));
  if (!mappings.length && !trace.length) dedupPanel.append(node("div", "empty-state", "No deduplication mappings or trace were recorded."));
  for (const mapping of mappings) {
    const from = mapping.proposal_id || "proposal";
    const to = mapping.canonical_label_id || "canonical label";
    const row = node("div", "mapping-row");
    row.append(node("span", "", from), node("span", "", "→"), node("span", "", to));
    dedupPanel.append(row);
    if (mapping.rationale) dedupPanel.append(node("div", "dedup-summary", mapping.rationale));
  }
  if (trace.length) {
    const details = node("details", "dedup-trace");
    details.append(node("summary", "", `Deduplication trace · ${trace.length} events`));
    const traceBody = node("div", "dedup-trace-content");
    for (const [index, event] of trace.entries()) {
      const row = node("div", "dedup-trace-row");
      row.append(node("span", "", String(index + 1).padStart(2, "0")), node("span", "", valueText(event.text ?? event)));
      traceBody.append(row);
    }
    details.append(traceBody);
    dedupPanel.append(details);
  }
  rightColumn.append(dedupPanel);
  grid.append(rightColumn);
  host.append(grid);
}

function setSection(section) {
  state.section = section;
  $("#run-section").hidden = section !== "run";
  $("#taxonomy-section").hidden = section !== "taxonomy";
  $$(".top-tab").forEach(button => button.classList.toggle("active", button.dataset.section === section));
  if (section === "taxonomy") renderTaxonomy();
}

function applySidebarState() {
  $("#run-section").classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  $("#sidebar-content").hidden = state.sidebarCollapsed;
  const button = $("#sidebar-toggle");
  button.textContent = state.sidebarCollapsed ? "»" : "«";
  button.setAttribute("aria-expanded", String(!state.sidebarCollapsed));
  button.setAttribute("aria-label", `${state.sidebarCollapsed ? "Expand" : "Collapse"} task and step sidebar`);
  button.title = state.sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar";
}
function bindControls() {
  try { state.sidebarCollapsed = localStorage.getItem("cu-sidebar-collapsed") === "true"; } catch (_) { /* storage may be disabled */ }
  if (window.matchMedia("(max-width: 640px)").matches) state.sidebarCollapsed = true;
  applySidebarState();
  $("#sidebar-toggle").addEventListener("click", () => {
    const atSteps = $("#step-view")?.getBoundingClientRect().top <= 2;
    state.sidebarCollapsed = !state.sidebarCollapsed;
    applySidebarState();
    try { localStorage.setItem("cu-sidebar-collapsed", String(state.sidebarCollapsed)); } catch (_) { /* storage may be disabled */ }
    if (atSteps) alignStepView("#sidebar-toggle");
  });
  $$(".top-tab").forEach(button => button.addEventListener("click", () => setSection(button.dataset.section)));
  const taskDialog = $("#task-dialog");
  const taskOpener = $("#task-picker-open");
  taskOpener.addEventListener("click", () => {
    renderTaskDialogList();
    taskDialog.showModal();
    taskOpener.setAttribute("aria-expanded", "true");
    $("#task-search").focus();
  });
  $("#task-dialog-close").addEventListener("click", () => taskDialog.close("dismiss"));
  taskDialog.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      event.preventDefault();
      taskDialog.close("dismiss");
    }
  });
  taskDialog.addEventListener("close", () => taskOpener.setAttribute("aria-expanded", "false"));
  taskDialog.addEventListener("click", event => {
    if (event.target === taskDialog) taskDialog.close("backdrop");
  });
  $("#task-search").addEventListener("input", updateTaskSearch);
  $("#reload-snapshot").addEventListener("click", () => loadSnapshot(false));
  $("#theme-toggle").addEventListener("click", () => {
    const root = document.documentElement;
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    $("#theme-toggle").setAttribute("aria-label", `Switch to ${next === "dark" ? "light" : "dark"} theme`);
    try { localStorage.setItem("cu-auto-review-theme", next); } catch (_) { /* storage can be disabled */ }
  });
  try {
    const saved = localStorage.getItem("cu-auto-review-theme");
    if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  } catch (_) { /* storage can be disabled */ }
}

async function loadSnapshot(initial = false) {
  const button = $("#reload-snapshot");
  const buttonLabel = button.textContent;
  const previousTask = activeTask();
  const previousTaskId = previousTask?.task_id;
  const previousStepId = previousTask?.steps?.[state.stepIndex]?.step_id;
  button.disabled = true;
  button.textContent = "Loading...";
  try {
    const response = await fetch(RUN_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    const run = await response.json();
    if (!run || typeof run !== "object") throw new Error("The run record was empty or malformed.");
    state.run = run;
    if (previousTaskId !== undefined) {
      const matchedTask = (run.tasks || []).findIndex(task => String(task.task_id) === String(previousTaskId));
      state.taskIndex = matchedTask >= 0 ? matchedTask : Math.min(state.taskIndex, Math.max(0, (run.tasks || []).length - 1));
    } else state.taskIndex = Math.min(state.taskIndex, Math.max(0, (run.tasks || []).length - 1));
    const nextSteps = run.tasks?.[state.taskIndex]?.steps || [];
    if (previousStepId !== undefined) {
      const matchedStep = nextSteps.findIndex(step => String(step.step_id) === String(previousStepId));
      state.stepIndex = matchedStep >= 0 ? matchedStep : Math.min(state.stepIndex, Math.max(0, nextSteps.length - 1));
    } else state.stepIndex = Math.min(state.stepIndex, Math.max(0, nextSteps.length - 1));
    document.title = `${run.run_id || "Batch"} · CU Auto Review`;
    updateOverview(run);
    renderTaskList();
    renderTaskWorkspace();
    renderTaxonomy();
    setSection(state.section);
    if (!initial) loadMessage("Latest snapshot reloaded.");
  } catch (error) {
    if (!state.run) {
      $("#run-id").textContent = "Batch unavailable";
      $("#run-status").textContent = "load error";
      $("#run-status").dataset.status = "error";
      $("#task-workspace").replaceChildren(node("div", "empty-state", `Could not load ${RUN_URL}: ${error.message}. Keep the project root server running and check that the latest run file exists.`));
      $("#task-picker-open").disabled = true;
      $("#task-picker-position").textContent = "No tasks";
      $("#task-picker-status").textContent = "No batch data loaded";
    }
    loadMessage(initial ? `Batch could not be loaded (${error.message}).` : `Snapshot reload failed (${error.message}).`, true);
  } finally {
    button.disabled = false;
    button.textContent = buttonLabel;
  }
}

async function init() {
  bindControls();
  await loadSnapshot(true);
}

init();
