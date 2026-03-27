const state = {
  dashboard: null,
  editingJobId: null,
};

const scheduleTemplate = document.getElementById("schedule-template");
const jobDialog = document.getElementById("job-dialog");
const logDialog = document.getElementById("log-dialog");

document.getElementById("refresh-button").addEventListener("click", loadDashboard);
document.getElementById("new-job-button").addEventListener("click", () => openJobDialog());
document.getElementById("close-dialog").addEventListener("click", () => jobDialog.close());
document.getElementById("close-log-dialog").addEventListener("click", () => logDialog.close());
document.getElementById("add-schedule").addEventListener("click", () => addScheduleRow());
document.getElementById("job-form").addEventListener("submit", saveJob);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(data.detail || "Request failed");
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

async function loadDashboard() {
  const dashboard = await api("/api/dashboard");
  state.dashboard = dashboard;
  renderMeta();
  renderJobs();
  renderActiveRuns();
  renderSchedules();
  renderHistory();
}

function renderMeta() {
  document.getElementById("meta-timezone").textContent = state.dashboard.timezone_name;
  document.getElementById("meta-home").textContent = state.dashboard.home_dir;
  document.getElementById("meta-engine").textContent = state.dashboard.engine_command;
}

function renderJobs() {
  const body = document.getElementById("jobs-body");
  body.innerHTML = "";
  if (!state.dashboard.jobs.length) {
    body.innerHTML = `<tr><td colspan="6" class="empty-state">No jobs registered yet.</td></tr>`;
    return;
  }
  state.dashboard.jobs.forEach((job) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>
        <strong>${escapeHtml(job.name)}</strong><br>
        <span class="mono">${escapeHtml(job.working_branch)}</span>
      </td>
      <td class="mono">${escapeHtml(job.repository_path)}</td>
      <td>${job.schedules.map((schedule) => `<div>${escapeHtml(schedule.description)}</div>`).join("") || "<span class='empty-state'>No schedules</span>"}</td>
      <td>
        <span class="pill">${job.enabled ? "enabled" : "disabled"}</span>
        <div>${job.active_run_count} active / queued</div>
      </td>
      <td>${formatDate(job.next_run_at)}</td>
      <td class="actions">
        <button class="button secondary" data-action="run" data-id="${job.id}">Run</button>
        <button class="button secondary" data-action="toggle" data-id="${job.id}">${job.enabled ? "Disable" : "Enable"}</button>
        <button class="button secondary" data-action="edit" data-id="${job.id}">Edit</button>
        <button class="button danger" data-action="delete" data-id="${job.id}">Delete</button>
      </td>
    `;
    body.appendChild(row);
  });
  body.querySelectorAll("button").forEach((button) => button.addEventListener("click", onJobAction));
}

function renderActiveRuns() {
  const target = document.getElementById("active-runs");
  target.innerHTML = "";
  if (!state.dashboard.active_runs.length) {
    target.textContent = "No active runs.";
    target.classList.add("empty-state");
    return;
  }
  target.classList.remove("empty-state");
  state.dashboard.active_runs.forEach((run) => {
    const item = document.createElement("div");
    item.className = "stack-item";
    item.innerHTML = `
      <div class="panel-header">
        <div>
          <strong>${escapeHtml(run.job_name_snapshot)}</strong>
          <div class="pill ${run.status}">${run.status}</div>
        </div>
        <div class="actions">
          <button class="button secondary" data-action="log" data-run="${run.id}">Log</button>
          <button class="button danger" data-action="cancel" data-run="${run.id}">Cancel</button>
        </div>
      </div>
      <p>Trigger: ${run.trigger_source}</p>
      <p>Attempts: ${run.retry_count + 1}</p>
      <p>Started: ${formatDate(run.started_at || run.requested_at)}</p>
      <p>${escapeHtml(run.summary || "-")}</p>
    `;
    target.appendChild(item);
  });
  wireRunActions(target);
}

function renderSchedules() {
  const target = document.getElementById("schedule-overview");
  target.innerHTML = "";
  if (!state.dashboard.schedule_overview.length) {
    target.textContent = "No schedules configured.";
    target.classList.add("empty-state");
    return;
  }
  target.classList.remove("empty-state");
  state.dashboard.schedule_overview.forEach((schedule) => {
    const item = document.createElement("div");
    item.className = "stack-item";
    item.innerHTML = `
      <strong>${escapeHtml(schedule.job_name)}</strong>
      <p>${escapeHtml(schedule.description)}</p>
      <p>${formatDate(schedule.next_run_at)}</p>
    `;
    target.appendChild(item);
  });
}

function renderHistory() {
  const body = document.getElementById("history-body");
  body.innerHTML = "";
  if (!state.dashboard.recent_runs.length) {
    body.innerHTML = `<tr><td colspan="8" class="empty-state">No history yet.</td></tr>`;
    return;
  }
  state.dashboard.recent_runs.forEach((run) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="mono">${run.id.slice(0, 8)}</td>
      <td>${escapeHtml(run.job_name_snapshot)}</td>
      <td><span class="pill ${run.status}">${run.status}</span></td>
      <td>${run.retry_count + 1}</td>
      <td>${formatDate(run.started_at || run.requested_at)}</td>
      <td>${formatDate(run.ended_at)}</td>
      <td>${escapeHtml(run.summary || "-")}</td>
      <td class="actions">
        <button class="button secondary" data-action="log" data-run="${run.id}">Log</button>
        <button class="button secondary" data-action="retry" data-run="${run.id}" ${run.status === "succeeded" ? "disabled" : ""}>Retry</button>
        ${run.ended_at ? "" : `<button class="button danger" data-action="cancel" data-run="${run.id}">Cancel</button>`}
      </td>
    `;
    body.appendChild(row);
  });
  wireRunActions(body);
}

async function onJobAction(event) {
  const action = event.currentTarget.dataset.action;
  const id = event.currentTarget.dataset.id;
  if (action === "edit") {
    const job = state.dashboard.jobs.find((item) => item.id === id);
    openJobDialog(job);
    return;
  }
  if (action === "run") {
    await api(`/api/jobs/${id}/run`, { method: "POST" });
  }
  if (action === "toggle") {
    const job = state.dashboard.jobs.find((item) => item.id === id);
    await api(`/api/jobs/${id}/enabled`, {
      method: "PUT",
      body: JSON.stringify({ enabled: !job.enabled }),
    });
  }
  if (action === "delete") {
    if (!window.confirm("Delete this job? History will stay in the database, but the job will be hidden.")) {
      return;
    }
    await api(`/api/jobs/${id}`, { method: "DELETE" });
  }
  await loadDashboard();
}

function wireRunActions(root) {
  root.querySelectorAll("button[data-run]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.dataset.action;
      const runId = button.dataset.run;
      if (action === "cancel") {
        await api(`/api/runs/${runId}/cancel`, { method: "POST" });
        await loadDashboard();
      }
      if (action === "retry") {
        await api(`/api/runs/${runId}/retry`, { method: "POST" });
        await loadDashboard();
      }
      if (action === "log") {
        const payload = await api(`/api/runs/${runId}/log`);
        document.getElementById("log-path").textContent = payload.log_path || "No log file yet.";
        document.getElementById("log-output").textContent = payload.content || "No log output yet.";
        logDialog.showModal();
      }
    });
  });
}

function openJobDialog(job = null) {
  state.editingJobId = job?.id || null;
  document.getElementById("dialog-title").textContent = job ? `Edit ${job.name}` : "New Job";
  document.getElementById("form-error").hidden = true;
  const form = document.getElementById("job-form");
  form.reset();
  document.getElementById("schedule-rows").innerHTML = "";
  const timezone = state.dashboard?.timezone_name || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

  if (job) {
    setFormValue("name", job.name);
    setFormValue("repository_path", job.repository_path);
    setFormValue("repository_url_override", job.repository_url_override || "");
    setFormValue("prompt_text", job.prompt_text || "");
    setFormValue("prompt_file_path", job.prompt_file_path || "");
    setFormValue("model_provider", job.model_provider || "");
    setFormValue("local_model_provider", job.local_model_provider || "");
    setFormValue("model_name", job.model_name || "");
    setFormValue("reasoning_effort", job.reasoning_effort || "");
    setFormValue("working_branch", job.working_branch || "main");
    setFormValue("workspace_name", job.workspace_name || "");
    setFormValue("test_command", job.test_command || "");
    setFormValue("approval_mode", job.approval_mode || "never");
    setFormValue("sandbox_mode", job.sandbox_mode || "workspace-write");
    setFormValue("max_blocks", job.max_blocks);
    setFormValue("max_concurrent_runs", job.max_concurrent_runs);
    setFormValue("stale_timeout_minutes", job.stale_timeout_minutes);
    form.elements.enabled.checked = job.enabled;
    form.elements.retry_max_attempts.value = job.retry_policy.max_attempts;
    form.elements.retry_delay_seconds.value = job.retry_policy.retry_delay_seconds;
    form.elements.retry_on_crash.checked = job.retry_policy.retry_on_crash;
    form.elements.retry_on_failure.checked = job.retry_policy.retry_on_failure;
    form.elements.retry_on_stale.checked = job.retry_policy.retry_on_stale;
    if (job.schedules.length) {
      job.schedules.forEach((schedule) => addScheduleRow(schedule));
    } else {
      addScheduleRow({ timezone_name: timezone });
    }
  } else {
    form.elements.enabled.checked = true;
    form.elements.retry_on_crash.checked = true;
    addScheduleRow({ timezone_name: timezone });
  }

  jobDialog.showModal();
}

function addScheduleRow(schedule = {}) {
  const fragment = scheduleTemplate.content.cloneNode(true);
  const row = fragment.querySelector(".schedule-row");
  const timezone = schedule.timezone_name || state.dashboard?.timezone_name || "UTC";
  row.querySelector('[name="timezone_name"]').value = timezone;
  row.querySelector('[name="kind"]').value = schedule.kind || "daily";
  row.querySelector('[name="run_at_local"]').value = toInputDate(schedule.anchor_local);
  row.querySelector('[name="start_at_local"]').value = toInputDate(schedule.anchor_local);
  row.querySelector('[name="hour"]').value = schedule.hour ?? "";
  row.querySelector('[name="minute"]').value = schedule.minute ?? "";
  row.querySelector('[name="interval_hours"]').value = schedule.interval_hours ?? 24;
  row.querySelector('[name="enabled"]').checked = schedule.enabled ?? true;
  const weekdayInputs = row.querySelectorAll('.weekday-strip input[type="checkbox"]');
  weekdayInputs.forEach((input) => {
    input.checked = (schedule.weekdays || []).includes(Number(input.value));
  });

  row.querySelector(".remove-schedule").addEventListener("click", () => row.remove());
  row.querySelector('[name="kind"]').addEventListener("change", () => syncScheduleRow(row));
  syncScheduleRow(row);
  document.getElementById("schedule-rows").appendChild(fragment);
}

function syncScheduleRow(row) {
  const kind = row.querySelector('[name="kind"]').value;
  const visible = {
    once: ["run-at"],
    daily: ["hour", "minute"],
    every_hours: ["start-at", "interval"],
    weekdays: ["hour", "minute", "weekdays"],
  }[kind];
  row.querySelectorAll("[data-role]").forEach((element) => {
    element.hidden = !visible.includes(element.dataset.role);
  });
}

async function saveJob(event) {
  event.preventDefault();
  const errorBox = document.getElementById("form-error");
  errorBox.hidden = true;
  try {
    const form = event.currentTarget;
    const payload = {
      name: form.elements.name.value.trim(),
      repository_path: form.elements.repository_path.value.trim(),
      repository_url_override: optional(form.elements.repository_url_override.value),
      prompt_text: optional(form.elements.prompt_text.value),
      prompt_file_path: optional(form.elements.prompt_file_path.value),
      model_provider: optional(form.elements.model_provider.value),
      local_model_provider: optional(form.elements.local_model_provider.value),
      model_name: optional(form.elements.model_name.value),
      reasoning_effort: optional(form.elements.reasoning_effort.value),
      working_branch: optional(form.elements.working_branch.value) || "main",
      workspace_name: optional(form.elements.workspace_name.value),
      test_command: optional(form.elements.test_command.value),
      approval_mode: optional(form.elements.approval_mode.value) || "never",
      sandbox_mode: optional(form.elements.sandbox_mode.value) || "workspace-write",
      max_blocks: Number(form.elements.max_blocks.value || 1),
      enabled: form.elements.enabled.checked,
      max_concurrent_runs: Number(form.elements.max_concurrent_runs.value || 1),
      stale_timeout_minutes: Number(form.elements.stale_timeout_minutes.value || 30),
      retry_policy: {
        max_attempts: Number(form.elements.retry_max_attempts.value || 0),
        retry_delay_seconds: Number(form.elements.retry_delay_seconds.value || 300),
        retry_on_crash: form.elements.retry_on_crash.checked,
        retry_on_failure: form.elements.retry_on_failure.checked,
        retry_on_stale: form.elements.retry_on_stale.checked,
      },
      schedules: collectSchedules(),
    };

    if (state.editingJobId) {
      await api(`/api/jobs/${state.editingJobId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    } else {
      await api("/api/jobs", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    jobDialog.close();
    await loadDashboard();
  } catch (error) {
    errorBox.hidden = false;
    errorBox.textContent = error.message;
  }
}

function collectSchedules() {
  return [...document.querySelectorAll(".schedule-row")].map((row) => {
    const kind = row.querySelector('[name="kind"]').value;
    const schedule = {
      kind,
      timezone_name: row.querySelector('[name="timezone_name"]').value.trim() || "UTC",
      enabled: row.querySelector('[name="enabled"]').checked,
      weekdays: [...row.querySelectorAll('.weekday-strip input[type="checkbox"]:checked')].map((input) => Number(input.value)),
    };
    if (kind === "once") {
      schedule.run_at_local = row.querySelector('[name="run_at_local"]').value;
    }
    if (kind === "daily" || kind === "weekdays") {
      schedule.hour = Number(row.querySelector('[name="hour"]').value || 0);
      schedule.minute = Number(row.querySelector('[name="minute"]').value || 0);
    }
    if (kind === "every_hours") {
      schedule.start_at_local = optional(row.querySelector('[name="start_at_local"]').value);
      schedule.interval_hours = Number(row.querySelector('[name="interval_hours"]').value || 24);
    }
    return schedule;
  });
}

function setFormValue(name, value) {
  const field = document.getElementById("job-form").elements[name];
  if (field) {
    field.value = value ?? "";
  }
}

function optional(value) {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  return new Intl.DateTimeFormat([], {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function toInputDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (part) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

loadDashboard().catch((error) => console.error(error));
setInterval(() => {
  loadDashboard().catch((error) => console.error(error));
}, 5000);
