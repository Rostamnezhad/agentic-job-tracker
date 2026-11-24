"use strict";

const $ = (selector) => document.querySelector(selector);
const stages = [
  "saved",
  "applied",
  "interview",
  "offer",
  "rejected",
  "withdrawn",
];
const stageNames = {
  saved: "Saved",
  applied: "Applied",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};
const options = {
  modes: {
    unknown: "Not confirmed",
    remote: "Remote",
    hybrid: "Hybrid",
    onsite: "On site",
  },
  types: {
    unknown: "Not confirmed",
    working_student: "Working student",
    internship: "Internship",
    full_time: "Full time",
    part_time: "Part time",
    contract: "Contract",
  },
  languages: {
    unknown: "Not confirmed",
    english: "English",
    german: "German",
    mixed: "English and German",
  },
  levels: {
    unknown: "Not confirmed",
    none: "Not required / not started",
    A1: "A1",
    A2: "A2",
    B1: "B1",
    B2: "B2",
    C1: "C1",
    C2: "C2",
  },
};
let csrf = "",
  user = null,
  jobs = [],
  authMode = "register",
  view = "board",
  editing = null;
let undoId = null;

function node(tag, attributes = {}, children = []) {
  const result = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes))
    result.setAttribute(key, value);
  for (const child of [].concat(children))
    result.append(
      child instanceof Node ? child : document.createTextNode(String(child)),
    );
  return result;
}
function button(label, className, action, accessibleLabel) {
  const result = node("button", { type: "button", class: className }, [label]);
  if (accessibleLabel) result.setAttribute("aria-label", accessibleLabel);
  result.addEventListener("click", action);
  return result;
}
function error(selector, message = "") {
  $(selector).textContent = message;
  $(selector).hidden = !message;
}
function notify(message, deletedId = null) {
  $("#toast-message").textContent = message;
  undoId = deletedId;
  $("#undo-delete").hidden = deletedId === null;
  $("#toast").hidden = false;
}
async function api(path, method = "GET", data) {
  const settings = { method, credentials: "same-origin", headers: {} };
  if (method !== "GET") {
    settings.headers = {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf,
    };
    settings.body = JSON.stringify(data || {});
  }
  let response;
  try {
    response = await fetch("/api" + path, settings);
  } catch {
    throw new Error(
      "Cannot reach the app. Check your connection and try again.",
    );
  }
  const result = await response
    .json()
    .catch(() => ({ error: "The server returned an unexpected response." }));
  if (!response.ok) {
    if (response.status === 401 && user) {
      user = null;
      jobs = [];
      showAuth("login");
    }
    throw new Error(
      result.error || "That action could not be completed. Please try again.",
    );
  }
  return result;
}
async function submit(form, errorId, task) {
  error(errorId);
  const control = form.querySelector('[type="submit"]');
  if (control) control.disabled = true;
  try {
    await task();
  } catch (exception) {
    error(errorId, exception.message);
  } finally {
    if (control) control.disabled = false;
  }
}
function showAuth(mode) {
  for (const dialog of document.querySelectorAll("dialog[open]"))
    dialog.close();
  $("#workspace-view").hidden = true;
  $("#auth-view").hidden = false;
  $("#toast").hidden = true;
  authMode = mode;
  const registering = mode === "register";
  $("#register-tab").classList.toggle("selected", registering);
  $("#login-tab").classList.toggle("selected", !registering);
  $("#register-tab").setAttribute("aria-pressed", registering);
  $("#login-tab").setAttribute("aria-pressed", !registering);
  $("#auth-title").textContent = registering
    ? "Make your next move."
    : "Welcome back.";
  $("#auth-description").textContent = registering
    ? "Create an account to keep your applications together."
    : "Your opportunities are right where you left them.";
  $("#auth-submit").textContent = registering
    ? "Create my workspace"
    : "Sign in";
  const password = $('#auth-form [name="password"]');
  password.minLength = registering ? 12 : 1;
  password.autocomplete = registering ? "new-password" : "current-password";
  password.placeholder = registering
    ? "At least 12 characters"
    : "Your password";
  password.value = "";
  $("#password-hint").hidden = !registering;
  error("#auth-error");
}
function hasPreferences() {
  return Object.values(user?.preferences || {}).some(
    (v) => v !== null && v !== "" && v !== "unknown",
  );
}
function showPage(page) {
  for (const name of ["applications", "preferences", "discovery"]) {
    const selected = page === name;
    $("#" + name + "-page").hidden = !selected;
    const control = $("#nav-" + name);
    control.classList.toggle("active", selected);
    if (selected) control.setAttribute("aria-current", "page");
    else control.removeAttribute("aria-current");
  }
  if (page === "preferences")
    fillForm($("#preferences-form"), user.preferences || {});
  if (page === "discovery")
    loadDiscovery().catch((e) => error("#discovery-error", e.message));
}
async function enterWorkspace() {
  $("#auth-view").hidden = true;
  $("#workspace-view").hidden = false;
  $("#username").textContent = user.username;
  $("#user-avatar").textContent = user.username[0].toUpperCase();
  $("#search-input").value = "";
  $("#status-filter").value = "";
  $("#type-filter").value = "";
  $("#discovery-form").reset();
  $("#discovery-sources").replaceChildren();
  $("#discovery-config").textContent = "Loading search configuration…";
  $("#discovery-results").replaceChildren();
  $("#discovery-output").hidden = true;
  showPage("applications");
  await refreshJobs();
}
async function refreshJobs() {
  error("#load-error");
  try {
    jobs = (await api("/jobs")).jobs;
    render();
  } catch (exception) {
    error("#load-error", exception.message);
    throw exception;
  }
}
function readableDate(value) {
  if (!value) return "—";
  return new Date(value + "T12:00:00").toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
function localToday() {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
function timestamp(value) {
  return new Date(value * 1000).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
function pill(status) {
  return node("span", { class: "pill status-" + status }, stageNames[status]);
}
function externalLink(url, label) {
  return node(
    "a",
    { href: url, target: "_blank", rel: "noopener noreferrer" },
    label,
  );
}
function openJobSafely(id) {
  openJob(id).catch((exception) => notify(exception.message));
}

function card(job) {
  const root = node("article", { class: "job-card" });
  const initial = job.company.trim().slice(0, 2).toUpperCase();
  const edit = button(
    "···",
    "icon-button",
    () => openJobSafely(job.id),
    "Edit " + job.role + " at " + job.company,
  );
  root.append(
    node("div", { class: "card-top" }, [
      node("span", { class: "company-avatar", "aria-hidden": "true" }, initial),
      edit,
    ]),
  );
  root.append(button(job.role, "card-title", () => openJobSafely(job.id)));
  root.append(node("div", { class: "company-name" }, job.company));
  root.append(
    node(
      "div",
      { class: "card-location" },
      job.location || "Location not confirmed",
    ),
  );
  const tags = node("div", { class: "tags" });
  if (job.work_mode !== "unknown")
    tags.append(node("span", { class: "tag" }, options.modes[job.work_mode]));
  if (job.employment_type !== "unknown")
    tags.append(
      node("span", { class: "tag" }, options.types[job.employment_type]),
    );
  if (job.url.startsWith("https://example.com/job-tracker-samples/"))
    tags.append(node("span", { class: "tag" }, "Fictional sample"));
  root.append(tags);
  if (hasPreferences()) {
    const { matches, gaps, unknowns } = job.fit;
    const message = gaps.length
      ? `${gaps.length} preference ${gaps.length === 1 ? "gap" : "gaps"} to review`
      : unknowns.length
        ? `${unknowns.length} ${unknowns.length === 1 ? "detail" : "details"} to confirm`
        : matches.length
          ? `${matches.length} preferences match`
          : "Set more preferences to compare";
    root.append(
      node(
        "div",
        { class: "card-check" + (gaps.length ? " gap" : "") },
        message,
      ),
    );
  }
  root.append(
    node("div", { class: "card-footer" }, [
      externalLink(job.url, "View posting"),
      button(
        "Update stage",
        "text-button",
        () => openJobSafely(job.id),
        "Update stage for " + job.role,
      ),
    ]),
  );
  if (job.applied_date)
    root.append(node("small", {}, "Applied " + readableDate(job.applied_date)));
  return root;
}
function render() {
  $("#stat-total").textContent = jobs.length;
  $("#stat-applied").textContent = jobs.filter((j) => j.applied_date).length;
  $("#stat-interview").textContent = jobs.filter(
    (j) => j.status === "interview",
  ).length;
  $("#stat-offer").textContent = jobs.filter(
    (j) => j.status === "offer",
  ).length;
  $("#nav-count").textContent = jobs.length;
  $("#preference-prompt").hidden = hasPreferences();
  const query = $("#search-input").value.trim().toLowerCase();
  const status = $("#status-filter").value,
    type = $("#type-filter").value;
  const filtered = jobs.filter(
    (j) =>
      (!status || j.status === status) &&
      (!type || j.employment_type === type) &&
      (!query ||
        [j.company, j.role, j.location, j.description].some((value) =>
          value.toLowerCase().includes(query),
        )),
  );
  $("#clear-filters").hidden = !query && !status && !type;
  $("#result-count").textContent =
    `${filtered.length} ${filtered.length === 1 ? "opportunity" : "opportunities"}`;
  $("#empty-state").hidden = jobs.length !== 0;
  $("#no-results").hidden = jobs.length === 0 || filtered.length !== 0;
  $("#board").hidden =
    jobs.length === 0 || filtered.length === 0 || view !== "board";
  $("#list-view").hidden =
    jobs.length === 0 || filtered.length === 0 || view !== "list";
  const board = $("#board");
  board.replaceChildren();
  for (const stage of stages.filter((s) => !status || s === status)) {
    const entries = filtered.filter((j) => j.status === stage);
    const column = node("section", {
      class: "column",
      "aria-label": stageNames[stage],
    });
    column.append(
      node("div", { class: "column-header" }, [
        node("h3", {}, [
          node("span", { class: "stage-dot " + stage, "aria-hidden": "true" }),
          stageNames[stage],
        ]),
        node("span", { class: "column-count" }, entries.length),
      ]),
    );
    const cards = node("div", { class: "cards" });
    for (const entry of entries) cards.append(card(entry));
    if (!entries.length)
      cards.append(
        node("div", { class: "column-empty" }, [
          "Nothing here yet",
          button(
            stage === "saved" ? "+ Save an opportunity" : "+ Add to this stage",
            "",
            () =>
              openJob(null, { status: stage }).catch((e) => notify(e.message)),
          ),
        ]),
      );
    column.append(cards);
    board.append(column);
  }
  const rows = $("#job-rows");
  rows.replaceChildren();
  for (const job of filtered)
    rows.append(
      node("tr", {}, [
        node("td", {}, [
          button(job.role, "table-role", () => openJobSafely(job.id)),
          node("small", {}, job.company),
        ]),
        node("td", {}, [
          job.location || "Unconfirmed",
          node("small", {}, options.modes[job.work_mode]),
        ]),
        node("td", {}, pill(job.status)),
        node("td", {}, readableDate(job.applied_date)),
        node(
          "td",
          {},
          button(
            "Edit",
            "text-button",
            () => openJobSafely(job.id),
            "Edit " + job.role,
          ),
        ),
      ]),
    );
}
function fillForm(form, data) {
  form.reset();
  for (const control of form.elements) {
    if (
      control.name &&
      Object.prototype.hasOwnProperty.call(data, control.name)
    )
      control.value = data[control.name] ?? "";
  }
}
function formData(form) {
  const data = Object.fromEntries(new FormData(form));
  for (const field of ["office_days", "commute_minutes"]) {
    if (field in data)
      data[field] = data[field] === "" ? null : Number(data[field]);
  }
  return data;
}
function updateDateField() {
  const saved = $("#job-status").value === "saved";
  const date = $("#job-date");
  date.disabled = saved;
  date.required = !saved;
  if (saved) date.value = "";
  else if ($("#job-status").value === "applied" && !date.value)
    date.value = localToday();
  $("#date-hint").textContent = saved
    ? "Saved jobs do not have an application date."
    : "Keep the date you originally applied, even when the stage changes.";
}
function renderFit(fit) {
  const results = $("#fit-results");
  results.replaceChildren();
  let any = false;
  for (const [field, title, className] of [
    ["matches", "Matches", "good"],
    ["gaps", "Potential gaps", "gap"],
    ["unknowns", "Needs checking", "unknown"],
  ]) {
    if (!fit[field].length) continue;
    any = true;
    results.append(
      node("div", { class: "fit-group-title " + className }, title),
    );
    results.append(
      node(
        "ul",
        {},
        fit[field].map((item) => node("li", {}, item)),
      ),
    );
  }
  if (!any)
    results.append(
      node(
        "p",
        { class: "muted" },
        "Add preferences to compare this opportunity with what matters to you.",
      ),
    );
}
async function openJob(id = null, draft = null) {
  editing = null;
  error("#job-error");
  let details = draft || {};
  $("#fit-check").hidden = true;
  $("#history-section").hidden = true;
  $("#import-review-note").hidden = !draft?.description;
  if (id !== null) {
    const result = await api("/jobs/" + id);
    editing = result.job;
    details = result.job;
    $("#fit-check").hidden = false;
    renderFit(result.fit);
    const history = $("#history-list");
    history.replaceChildren();
    for (const event of result.history)
      history.append(
        node("li", {}, [
          stageNames[event.status],
          node("small", {}, timestamp(event.created_at)),
        ]),
      );
    $("#history-section").hidden = !result.history.length;
  }
  fillForm($("#job-form"), details);
  $("#job-dialog-title").textContent = editing
    ? "Opportunity details"
    : draft?.description
      ? "Review your import"
      : "Add an opportunity";
  $("#delete-job").hidden = !editing;
  $("#job-form details").open =
    Boolean(details.german_level && details.german_level !== "unknown") ||
    details.office_days != null ||
    details.commute_minutes != null;
  updateDateField();
  $("#job-dialog").showModal();
}

for (const select of document.querySelectorAll("[data-options]")) {
  for (const [value, label] of Object.entries(
    options[select.dataset.options],
  )) {
    let display = value === "unknown" ? select.dataset.unknown || label : label;
    if (value === "none")
      display = select.closest("#preferences-form")
        ? "Not yet started"
        : "Not required";
    select.append(node("option", { value }, display));
  }
}
$("#today").textContent = new Date().toLocaleDateString(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
});
$("#register-tab").addEventListener("click", () => showAuth("register"));
$("#login-tab").addEventListener("click", () => showAuth("login"));
$("#auth-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit(event.currentTarget, "#auth-error", async () => {
    const result = await api("/" + authMode, "POST", formData($("#auth-form")));
    user = result.user;
    csrf = result.csrf;
    $('#auth-form [name="password"]').value = "";
    await enterWorkspace();
  });
});
$("#logout-button").addEventListener("click", async () => {
  try {
    const result = await api("/logout", "POST");
    csrf = result.csrf;
    user = null;
    jobs = [];
    showAuth("login");
  } catch (exception) {
    notify(exception.message);
  }
});
$("#nav-applications").addEventListener("click", () =>
  showPage("applications"),
);
$("#nav-preferences").addEventListener("click", () => showPage("preferences"));
$("#setup-preferences").addEventListener("click", () =>
  showPage("preferences"),
);
for (const id of ["#add-button", "#empty-add"])
  $(id).addEventListener("click", () =>
    openJob().catch((e) => notify(e.message)),
  );
for (const button of document.querySelectorAll("[data-close]"))
  button.addEventListener("click", () =>
    document.getElementById(button.dataset.close).close(),
  );
$("#job-status").addEventListener("change", updateDateField);
$("#job-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit(event.currentTarget, "#job-error", async () => {
    const data = formData($("#job-form"));
    data.applied_date = data.status === "saved" ? null : data.applied_date;
    if (editing) data.version = editing.version;
    await api(
      editing ? "/jobs/" + editing.id : "/jobs",
      editing ? "PUT" : "POST",
      data,
    );
    $("#job-dialog").close();
    notify(editing ? "Opportunity updated." : "Opportunity saved.");
    await refreshJobs();
  });
});
$("#delete-job").addEventListener("click", () => {
  error("#delete-error");
  $("#delete-description").textContent =
    editing.role + " at " + editing.company;
  $("#delete-dialog").showModal();
});
$("#confirm-delete").addEventListener("click", async () => {
  const control = $("#confirm-delete");
  control.disabled = true;
  try {
    const id = editing.id;
    await api("/jobs/" + id, "DELETE", { version: editing.version });
    $("#delete-dialog").close();
    $("#job-dialog").close();
    notify("Opportunity removed from your board.", id);
    await refreshJobs();
  } catch (exception) {
    error("#delete-error", exception.message);
  } finally {
    control.disabled = false;
  }
});
$("#undo-delete").addEventListener("click", async () => {
  $("#undo-delete").disabled = true;
  try {
    await api("/jobs/" + undoId + "/restore", "POST");
    notify("Opportunity restored.");
    await refreshJobs();
  } catch (exception) {
    notify(exception.message);
  } finally {
    $("#undo-delete").disabled = false;
  }
});
$("#close-toast").addEventListener("click", () => {
  $("#toast").hidden = true;
});
$("#preferences-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit(event.currentTarget, "#preferences-error", async () => {
    user = (await api("/preferences", "PUT", formData($("#preferences-form"))))
      .user;
    $("#preferences-saved").textContent =
      "Saved. Your job checks are up to date.";
    await refreshJobs();
  });
});
$("#preferences-form").addEventListener("input", () => {
  $("#preferences-saved").textContent = "";
});
for (const selector of ["#search-input", "#status-filter", "#type-filter"])
  $(selector).addEventListener("input", render);
$("#clear-filters").addEventListener("click", () => {
  $("#search-input").value = "";
  $("#status-filter").value = "";
  $("#type-filter").value = "";
  render();
});
for (const mode of ["board", "list"])
  $("#" + mode + "-toggle").addEventListener("click", () => {
    view = mode;
    for (const value of ["board", "list"]) {
      $("#" + value + "-toggle").classList.toggle("selected", value === mode);
      $("#" + value + "-toggle").setAttribute("aria-pressed", value === mode);
    }
    render();
  });
$("#import-button").addEventListener("click", () => {
  error("#import-error");
  error("#json-error");
  $("#import-dialog").showModal();
});
$("#import-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit(event.currentTarget, "#import-error", async () => {
    const result = await api("/parse", "POST", formData($("#import-form")));
    $("#import-dialog").close();
    await openJob(null, result.draft);
  });
});
$("#json-file").addEventListener("change", async (event) => {
  error("#json-error");
  const file = event.target.files[0];
  if (!file) return;
  event.target.disabled = true;
  try {
    if (file.size > 900000)
      throw new Error("Choose a JSON export smaller than 900 KB.");
    let imported;
    try {
      imported = JSON.parse(await file.text());
    } catch {
      throw new Error("This file is not valid JSON.");
    }
    const result = await api("/import", "POST", { jobs: imported });
    $("#import-dialog").close();
    notify(`Imported ${result.count} opportunities.`);
    await refreshJobs();
  } catch (exception) {
    error("#json-error", exception.message);
  } finally {
    event.target.value = "";
    event.target.disabled = false;
  }
});
$("#sample-button").addEventListener("click", async () => {
  $("#sample-button").disabled = true;
  try {
    const result = await api("/samples", "POST");
    notify(`Added ${result.count} fictional sample jobs.`);
    await refreshJobs();
  } catch (exception) {
    notify(exception.message);
  } finally {
    $("#sample-button").disabled = false;
  }
});
$("#export-button").addEventListener("click", async () => {
  try {
    const exported = await api("/export");
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(exported, null, 2)], {
        type: "application/json",
      }),
    );
    const link = node("a", { href: url, download: "my-jobs.json" });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notify("Your jobs were exported.");
  } catch (exception) {
    notify(exception.message);
  }
});

(async () => {
  try {
    const session = await api("/session");
    csrf = session.csrf;
    user = session.user;
    if (user) await enterWorkspace();
    else showAuth("register");
  } catch (exception) {
    showAuth("login");
    error("#auth-error", exception.message);
  } finally {
    $("#loading").hidden = true;
  }
})();

let discoverySources = [];
let discoveryBusy = false;
async function loadDiscovery() {
  error("#discovery-error");
  const accountId = user?.id;
  const state = await api("/discovery");
  if (!user || user.id !== accountId) return;
  discoverySources = state.sources;
  fillForm($("#discovery-form"), state.profile || {});
  const selected = state.profile?.sources || state.sources.map((s) => s.id);
  const choices = $("#discovery-sources");
  choices.replaceChildren();
  for (const source of state.sources) {
    const input = node("input", {
      type: "checkbox",
      value: source.id,
      name: "source",
    });
    input.checked = selected.includes(source.id);
    choices.append(node("label", {}, [input, source.name]));
  }
  $("#discovery-config").textContent = state.configured
    ? "Tavily is configured. Keep your provider account on the free plan; this app never upgrades it."
    : "Search needs a Tavily free-plan key. Stop the server and restart with: python -m job_tracker serve --ask-search-key";
  $("#find-jobs").disabled = !state.configured || discoveryBusy;
  $("#discovery-budget").textContent =
    `${state.reserved_credits} / ${state.monthly_limit} requests reserved this UTC month across this installation. Maximum 40 per user per rolling day. One basic request per selected source; identical profiles reuse a 24-hour cache. Failed requests still count toward this conservative local limit. Usage elsewhere is not included.`;
  $("#discovery-progress").textContent = "";
  $("#discovery-output").hidden = !state.latest;
  if (state.latest) renderDiscovery(state.latest);
}
function discoveryProfile() {
  const data = formData($("#discovery-form"));
  delete data.source;
  data.radius_km = Number(data.radius_km);
  data.sources = [
    ...document.querySelectorAll("#discovery-sources input:checked"),
  ].map((input) => input.value);
  return data;
}
function renderDiscovery(report) {
  $("#discovery-output").hidden = false;
  $("#discovery-summary").textContent =
    `${report.results.length} leads · ${report.cached ? "Cached results, no new requests" : report.reserved_credits + " requests reserved"} · Search time: ${new Date(report.created_at * 1000).toLocaleString()}. Profile: ${report.profile.interests}; ${report.profile.city}, ${report.profile.radius_km} km requested.`;
  const coverage = $("#discovery-coverage");
  coverage.replaceChildren();
  for (const source of report.coverage)
    coverage.append(
      node(
        "p",
        { class: "source-report" },
        `${source.name}: ${source.state === "failed" ? source.error : source.count + " results returned"}`,
      ),
    );
  const results = $("#discovery-results");
  results.replaceChildren();
  if (!report.results.length)
    results.append(
      node(
        "p",
        {},
        "No leads were returned. Check the source report, broaden your target roles, or try other sources. This does not mean no suitable jobs exist.",
      ),
    );
  for (const job of report.results) {
    const card = node("article", { class: "job-card discovery-card" });
    card.append(node("h3", {}, externalLink(job.url, job.title)));
    card.append(
      node(
        "small",
        {},
        job.sources.join(", ") +
          ` · Keyword relevance: ${job.relevance} points`,
      ),
    );
    card.append(
      node(
        "p",
        {},
        job.snippet.slice(0, 800) ||
          "No description returned. Open the source for details.",
      ),
    );
    if (job.matches.length)
      card.append(
        node(
          "ul",
          { class: "good" },
          job.matches.map((t) => node("li", {}, t)),
        ),
      );
    if (job.gaps.length)
      card.append(
        node(
          "ul",
          { class: "gap" },
          job.gaps.map((t) => node("li", {}, t)),
        ),
      );
    card.append(
      node(
        "ul",
        { class: "muted" },
        job.unknowns.map((t) => node("li", {}, t)),
      ),
    );
    card.append(
      button("Review and save", "button secondary", () =>
        openJob(null, {
          company: "",
          role: job.title,
          url: job.url,
          description: job.snippet,
          notes: `Discovered via ${job.sources.join(", ")}. Verify employer, office location, language and availability.`,
          status: "saved",
        }).catch((e) => notify(e.message)),
      ),
    );
    results.append(card);
  }
}
$("#nav-discovery").addEventListener("click", () => showPage("discovery"));
$("#discovery-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit(event.currentTarget, "#discovery-error", async () => {
    await api("/discovery/profile", "PUT", discoveryProfile());
    $("#discovery-progress").textContent =
      "Search profile saved. No search requests made.";
  });
});
$("#find-jobs").addEventListener("click", async () => {
  if (!$("#discovery-form").reportValidity() || discoveryBusy) return;
  const accountId = user?.id;
  discoveryBusy = true;
  $("#find-jobs").disabled = true;
  error("#discovery-error");
  $("#discovery-progress").textContent =
    "Searching selected sources… This can take up to a minute.";
  try {
    await api("/discovery/profile", "PUT", discoveryProfile());
    const report = await api("/discovery/search", "POST");
    if (!user || user.id !== accountId) return;
    await loadDiscovery();
    renderDiscovery(report);
    $("#discovery-progress").textContent =
      "Search complete. Review each lead before saving or applying.";
  } catch (exception) {
    if (user?.id === accountId) {
      error("#discovery-error", exception.message);
      $("#discovery-progress").textContent = "";
    }
  } finally {
    discoveryBusy = false;
    $("#find-jobs").disabled = false;
  }
});
