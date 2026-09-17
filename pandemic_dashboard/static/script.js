/**
 * Hospital Resource Stability Lab: Client
 */

"use strict";

let mcChart = null;
let running = false;
let lastMcMeta = null;
let lastExternalSignal = null;

const EMPTY = "N/A";

const ACCENT = "#7a1f2e";
const ACCENT_FILL = "rgba(122, 31, 46, 0.10)";

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btnBankers")?.addEventListener("click", runBankers);
  document.getElementById("btnMonteCarlo")?.addEventListener("click", () => runMonteCarlo(false));
  document.getElementById("btnSensitivity")?.addEventListener("click", runSensitivity);
  document.getElementById("btnDynamic")?.addEventListener("click", runDynamic);
  document.getElementById("btnPhase3")?.addEventListener("click", runPhase3);
  document.getElementById("btnRandomize")?.addEventListener("click", fillRandomInputs);
  document.getElementById("btnMcExperiment")?.addEventListener("click", runMcExperiment);
  document.getElementById("btnMcExperimentStop")?.addEventListener("click", stopMcExperiment);
  ["exp_min_n", "exp_max_n", "exp_trials", "exp_model", "exp_seed"].forEach(id => {
    document.getElementById(id)?.addEventListener("input", updateExpConfigSummary);
    document.getElementById(id)?.addEventListener("change", updateExpConfigSummary);
  });
  document.getElementById("btnLoadExternal")?.addEventListener("click", loadExternalData);
  document.getElementById("btnExplainChart")?.addEventListener("click", toggleChartExplain);
  document.querySelectorAll(".sim-tab").forEach(btn => {
    btn.addEventListener("click", () => switchTab(btn.getAttribute("data-tab")));
  });
  HSLabExport?.init();
  document.getElementById("btnDlJson")?.addEventListener("click", () => downloadExperiment("json"));
  loadConfig();
  updateExpConfigSummary();
});

function switchTab(name) {
  if (!name) return;
  document.querySelectorAll(".sim-tab").forEach(btn => {
    const active = btn.getAttribute("data-tab") === name;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".tab-panel").forEach(panel => {
    const active = panel.id === `panel-${name}`;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
  requestAnimationFrame(() => {
    if (name === "mc" && mcChart) mcChart.resize();
    if (name === "experiment" && typeof Plotly !== "undefined") {
      ["expConvPlot", "expCurvePlot"].forEach(id => {
        const el = document.getElementById(id);
        if (el?.data) Plotly.Plots.resize(el);
      });
    }
  });
}

function toggleChartExplain() {
  const panel = document.getElementById("chartExplain");
  const btn = document.getElementById("btnExplainChart");
  if (!panel || !btn) return;
  const open = panel.hidden;
  panel.hidden = !open;
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) updateChartExplainNote();
}

function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function fillRandomInputs() {
  setInput("icu_beds", randomInt(8, 28));
  setInput("oxygen_units", randomInt(40, 160));
  setInput("ventilators", randomInt(6, 24));
  setInput("nurses", randomInt(18, 80));
  setInput("blood_units", randomInt(40, 200));
  const mild = randomInt(35, 70);
  const moderate = randomInt(8, 25);
  const severe = randomInt(8, 25);
  let critical = 100 - mild - moderate - severe;
  if (critical < 1) critical = 1;
  setInput("sev_mild", mild);
  setInput("sev_moderate", moderate);
  setInput("sev_severe", severe);
  setInput("sev_critical", critical);
  setInput("demo_patients", randomInt(8, 30));
  setInput("max_patients", randomInt(20, 60));
  setInput("trials_per_n", randomInt(10, 50));
  setInput("horizon_hours", randomInt(24, 168));
  setInput("arrivals_per_step", randomInt(1, 4));
  setInput("seed", randomInt(1, 99999));
  setInput("exp_seed", document.getElementById("seed")?.value);
  updateExpConfigSummary();
  hideError();
  setLiveStatus("Random inputs filled — run when ready", false);
}

function pct(val) {
  return (val * 100).toFixed(1) + "%";
}

function fmtProb(val) {
  return (val * 100).toFixed(2) + "%";
}

async function loadConfig() {
  try {
    const resp = await fetch("/api/config");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Failed to load config");

    const res = data.resources || {};
    setInput("icu_beds", res.ICU_Beds);
    setInput("oxygen_units", res.Oxygen_Units);
    setInput("ventilators", res.Ventilators);
    setInput("nurses", res.Nurses);
    setInput("blood_units", res.Blood_Units);

    const sev = data.severity_distribution || {};
    setInput("sev_mild", Math.round((sev.Mild || 0) * 100));
    setInput("sev_moderate", Math.round((sev.Moderate || 0) * 100));
    setInput("sev_severe", Math.round((sev.Severe || 0) * 100));
    setInput("sev_critical", Math.round((sev.Critical || 0) * 100));
    setInput("max_patients", data.max_patients);
    setInput("exp_seed", data.random_seed);
    setInput("exp_max_n", Math.min(40, data.max_patients || 40));
    updateExpConfigSummary();

    const name = data.model_name || data.hospital_name;
    const subtitle = document.getElementById("siteSubtitle");
    if (subtitle && name) {
      subtitle.textContent = `${name}: Banker's Algorithm with Monte Carlo collapse estimation`;
    }
  } catch (err) {
    showError(`Config load failed: ${err.message}`);
  }
}

function setInput(id, value) {
  const el = document.getElementById(id);
  if (el && value !== undefined && value !== null) el.value = value;
}

function collectPayload() {
  const sev = {
    Mild: parseFloat(document.getElementById("sev_mild").value) || 0,
    Moderate: parseFloat(document.getElementById("sev_moderate").value) || 0,
    Severe: parseFloat(document.getElementById("sev_severe").value) || 0,
    Critical: parseFloat(document.getElementById("sev_critical").value) || 0,
  };
  const payload = {
    icu_beds: parseInt(document.getElementById("icu_beds").value, 10),
    oxygen_units: parseInt(document.getElementById("oxygen_units").value, 10),
    ventilators: parseInt(document.getElementById("ventilators").value, 10),
    nurses: parseInt(document.getElementById("nurses").value, 10),
    blood_units: parseInt(document.getElementById("blood_units").value, 10),
    severity_distribution: sev,
    seed: parseInt(document.getElementById("seed").value, 10) || 42,
  };
  if (document.getElementById("useExternalSignal")?.checked) {
    payload.use_external_signal = true;
  }
  return payload;
}

function setLoading(loading) {
  running = loading;
  ["btnBankers", "btnMonteCarlo", "btnSensitivity", "btnDynamic", "btnPhase3", "btnRandomize", "btnMcExperiment"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = loading;
  });
  setLiveStatus(loading ? "Running..." : "Ready", loading);
}

function setLiveStatus(text, isRunning) {
  const pill = document.getElementById("liveStatus");
  if (!pill) return;
  pill.textContent = text;
  pill.classList.toggle("running", isRunning);
}

function showError(msg) {
  const box = document.getElementById("errorBox");
  if (!box) return;
  box.textContent = msg;
  box.classList.add("visible");
}

function hideError() {
  document.getElementById("errorBox")?.classList.remove("visible");
}

async function postJSON(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const msg = data.details ? `${data.error}: ${data.details}` : (data.error || `HTTP ${resp.status}`);
    throw new Error(msg);
  }
  return data;
}

/* ── External data ─────────────────────────────────────────────── */

async function loadExternalData() {
  const panel = document.getElementById("externalDataPanel");
  if (!panel) return;
  panel.innerHTML = `<p class="placeholder">Fetching...</p>`;
  try {
    const resp = await fetch("/api/external-data");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Fetch failed");
    lastExternalSignal = data;
    const sourceLink = data.source_url
      ? `<a href="${escapeHtml(data.source_url)}" target="_blank" rel="noopener">${escapeHtml(data.source)}</a>`
      : escapeHtml(data.source);
    const licenseNote = data.license && data.license !== "N/A"
      ? ` (<a href="${escapeHtml(data.source_url || "#")}" target="_blank" rel="noopener">${escapeHtml(data.license)}</a>)`
      : "";
    panel.innerHTML = `
      <dl class="data-dl">
        <dt>Source</dt><dd>${sourceLink}${licenseNote}</dd>
        <dt>Availability</dt><dd>${escapeHtml(data.availability_status || (data.available ? "CURRENT_EXTERNAL" : "SYNTHETIC_FALLBACK"))}</dd>
        <dt>Data type</dt><dd>${escapeHtml(data.data_type)} — latest available public epidemiological signal, not live hospital occupancy</dd>
        <dt>Metric</dt><dd><code>${escapeHtml(data.metric)}</code></dd>
        <dt>Region</dt><dd>${escapeHtml(data.region || "N/A")}</dd>
        <dt>Last data date</dt><dd>${escapeHtml(data.last_data_date || "N/A")}</dd>
        <dt>Fetched at</dt><dd>${escapeHtml(data.fetched_at)}</dd>
        <dt>14-day avg (smoothed)</dt><dd>${data.avg_new_cases_smoothed_14d != null ? data.avg_new_cases_smoothed_14d.toLocaleString(undefined, {maximumFractionDigits: 0}) : "N/A"}</dd>
        <dt>Workload factor</dt><dd><strong>${data.workload_factor?.toFixed(3) ?? "1.000"}</strong> ${escapeHtml(typeof data.transformation === "object" ? (data.transformation.formula || "") : "")} [${escapeHtml((data.transformation && data.transformation.classification) || "MODEL_ASSUMPTION")}]</dd>
      </dl>
      <p class="note">${escapeHtml(data.interpretation)}</p>
      <p class="note">Reference: <a href="https://github.com/owid/covid-19-data" target="_blank" rel="noopener">github.com/owid/covid-19-data</a></p>
      ${data.available ? "" : `<p class="note warn">Fallback active: ${escapeHtml(data.fallback_reason || "source unavailable")}</p>`}
    `;
    updateChartExplainNote();
  } catch (err) {
    panel.innerHTML = `<p class="placeholder">Error: ${escapeHtml(err.message)}</p>`;
  }
}

/* ── Banker's ──────────────────────────────────────────────────── */

async function runBankers() {
  if (running) return;
  hideError();
  setLoading(true);
  const payload = collectPayload();
  payload.patients = parseInt(document.getElementById("demo_patients").value, 10) || 15;
  try {
    const data = await postJSON("/bankers_demo", payload);
    renderResourceState(data);
    renderBankersSteps(data);
    renderBankersBanner(data);
    renderPostMortem(data);
    HSLabExport?.store("bankers", data, payload);
  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false);
  }
}

function renderBankersBanner(data) {
  const banner = document.getElementById("safetyResult");
  if (!banner) return;
  if (data.safe) {
    banner.textContent = `Banker's: SAFE (${data.patients_admitted}/${data.patients_requested} admitted)`;
    banner.className = "result-banner compact safe";
  } else {
    banner.textContent = `Banker's: UNSAFE${data.blocking_resource ? ` (${data.blocking_resource})` : ""}`;
    banner.className = "result-banner compact unsafe";
  }
}

function renderResourceState(data) {
  const names = data.resource_names;
  const pids = Object.keys(data.allocation);
  document.getElementById("stateDesc").textContent =
    `Admitted ${data.patients_admitted} of ${data.patients_requested} requested. Severity: ${formatSeverity(data.severity_breakdown)}`;
  renderVectorTable("tableTotal", names, data.total);
  renderVectorTable("tableAvailable", names, data.available);
  renderVectorTable("tableWork", names, data.available);
  renderMatrixTable("tableAllocation", names, pids, data.allocation);
  renderMatrixTable("tableMax", names, pids, data.max_demand);
  renderMatrixTable("tableNeed", names, pids, data.need);
}

function formatSeverity(breakdown) {
  if (!breakdown) return EMPTY;
  return Object.entries(breakdown).filter(([, v]) => v > 0).map(([k, v]) => `${k}: ${v}`).join(", ") || EMPTY;
}

function updateChartExplainNote() {
  const el = document.getElementById("explainExternalNote");
  if (!el) return;
  let text = "";
  if (lastMcMeta) {
    text += `Current run: T = ${lastMcMeta.trials_per_n} trials per n, N = ${lastMcMeta.max_patients} max patients. `;
  }
  if (lastExternalSignal?.available) {
    text += `External signal applied: workload factor = ${lastExternalSignal.workload_factor.toFixed(3)} `
      + `(from ${lastExternalSignal.metric}, reference: `
      + `<a href="${lastExternalSignal.source_url}" target="_blank" rel="noopener">OWID COVID-19 data</a>). `
      + `Scaled max n uses: N' = clamp(round(N × factor), 5, 200).`;
  } else if (document.getElementById("useExternalSignal")?.checked) {
    text += "External signal checkbox is on; load the signal to apply scaling.";
  } else {
    text += "External signal not applied; patient count uses configured N directly.";
  }
  el.innerHTML = text;
}

function renderVectorTable(tableId, names, values) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  if (!tbody) return;
  tbody.innerHTML = names.map((n, i) =>
    `<tr><td class="row-label">${formatName(n)}</td><td>${values[i]}</td></tr>`
  ).join("");
}

function renderMatrixTable(tableId, names, pids, matrix) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  thead.innerHTML = `<tr><th>Patient</th>${names.map(n => `<th>${formatName(n)}</th>`).join("")}</tr>`;
  if (!pids.length) {
    tbody.innerHTML = `<tr><td colspan="${names.length + 1}" class="empty-cell">No patients admitted</td></tr>`;
    return;
  }
  tbody.innerHTML = pids.map(pid => {
    const row = matrix[pid];
    return `<tr><td class="row-label">${pid}</td>${row.map(v => `<td>${v}</td>`).join("")}</tr>`;
  }).join("");
}

function formatName(key) { return key.replace(/_/g, " "); }

function renderBankersSteps(data) {
  const seqDesc = document.getElementById("sequenceDesc");
  const container = document.getElementById("stepsContainer");
  if (seqDesc) {
    seqDesc.textContent = data.safe && data.safe_sequence?.length
      ? `Safe sequence: ${data.safe_sequence.join(" → ")}`
      : (!data.safe ? "No safe completion ordering exists." : "");
  }
  if (!container) return;
  if (!data.steps?.length) {
    container.innerHTML = `<p class="placeholder">No trace available.</p>`;
    return;
  }
  container.innerHTML = data.steps.map(step => {
    let cls = "step-card";
    if (step.action === "initialize") cls += " init";
    else if (step.action === "check") cls += step.need_le_work ? " check-pass" : " check-fail";
    else if (step.action === "complete") cls += " complete";
    else if (step.action === "unsafe") cls += " unsafe";
    else if (step.action === "safe") cls += " safe";

    let body = "";
    if (step.action === "check") {
      const condCls = step.need_le_work ? "cond-true" : "cond-false";
      body = `
        <div class="step-detail"><strong>Process:</strong> ${step.patient}</div>
        <div class="step-detail"><strong>Work before:</strong> [${step.work_before?.join(", ") ?? ""}]</div>
        <div class="step-detail"><strong>Need:</strong> [${step.need?.join(", ") ?? ""}]</div>
        <div class="step-detail"><strong>Allocation:</strong> [${step.allocation?.join(", ") ?? ""}]</div>
        <div class="step-detail"><span class="${condCls}">Need &le; Work: ${step.need_le_work ? "TRUE" : "FALSE"}</span></div>
        <div class="step-detail"><strong>Work after:</strong> [${step.work_after?.join(", ") ?? step.work_before?.join(", ") ?? ""}]</div>
      `;
    }

    return `<div class="${cls}">
      <div class="step-meta">Step ${step.step} · ${step.action}</div>
      <div class="step-msg">${escapeHtml(step.message)}</div>${body}
    </div>`;
  }).join("");
}

function renderPostMortem(data) {
  const panel = document.getElementById("postMortemPanel");
  if (!panel) return;
  if (data.safe || !data.post_mortem) {
    panel.hidden = true;
    return;
  }
  const pm = data.post_mortem;
  panel.hidden = false;
  const expl = (pm.explanations || []).map(e => `<li>${escapeHtml(e)}</li>`).join("");
  panel.innerHTML = `
    <h4>Unsafe State Post-Mortem (diagnostic)</h4>
    <p><strong>Completed:</strong> ${(pm.completed_processes || []).join(", ") || "none"}</p>
    <p><strong>Remaining:</strong> ${(pm.remaining_processes || []).join(", ") || "none"}</p>
    <p><strong>Final Work:</strong> [${(pm.final_work || []).join(", ")}]</p>
    <p><strong>Most constraining resource (heuristic):</strong> ${escapeHtml(pm.most_constraining_resource || "N/A")}</p>
    <p class="note">${escapeHtml(pm.most_constraining_rule || "")}</p>
    <ul>${expl}</ul>
  `;
}

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

/* ── Monte Carlo ───────────────────────────────────────────────── */

async function runMonteCarlo(isAuto) {
  if (running) return;
  hideError();
  setLoading(true);
  const payload = collectPayload();
  payload.max_patients = parseInt(document.getElementById("max_patients").value, 10) || 60;
  payload.trials_per_n = parseInt(document.getElementById("trials_per_n").value, 10) || 30;
  try {
    const data = await postJSON("/run_simulation", payload);
    renderMonteCarlo(data, payload);
    if (isAuto) setLiveStatus("Updated", false);
  } catch (err) {
    if (!isAuto) showError(err.message);
    setLiveStatus("Error", false);
  } finally {
    setLoading(false);
  }
}

function renderMonteCarlo(data, inputs) {
  const curve = data.probability_curve;
  const risk = data.risk_summary;
  ["mcTh10", "mcTh50", "mcTh70"].forEach((id, i) => {
    const el = document.getElementById(id);
    const key = ["threshold_10pct", "threshold_50pct", "threshold_70pct"][i];
    if (el) el.textContent = risk[key] ?? EMPTY;
  });
  const peakAdmit = curve.reduce((b, e) => e.p_admission_failure > (b?.p_admission_failure ?? -1) ? e : b, null);
  const peakUnsafe = curve.reduce((b, e) => e.p_unsafe > (b?.p_unsafe ?? -1) ? e : b, null);
  const pa = document.getElementById("mcPeakAdmit");
  const pu = document.getElementById("mcPeakUnsafe");
  const meta = document.getElementById("mcTrialsMeta");
  if (pa) pa.textContent = peakAdmit ? `${fmtProb(peakAdmit.p_admission_failure)} @n=${peakAdmit.n}` : EMPTY;
  if (pu) pu.textContent = peakUnsafe?.p_unsafe > 0 ? `${fmtProb(peakUnsafe.p_unsafe)} @n=${peakUnsafe.n}` : "0%";
  if (meta) meta.textContent = `${inputs.trials_per_n} / ${inputs.max_patients}`;
  lastMcMeta = { trials_per_n: inputs.trials_per_n, max_patients: inputs.max_patients };
  if (data.external_signal) lastExternalSignal = data.external_signal;
  updateChartExplainNote();
  renderMCChart(curve);
  renderUtilTable(risk.collapse_utilization || {});
  HSLabExport?.store("mc", data, inputs);
}

function renderMCChart(curve) {
  document.getElementById("chartPlaceholder")?.classList.add("hidden");
  const ns = curve.map(d => d.n);
  const probs = curve.map(d => d.p_collapse * 100);
  const ciLo = curve.map(d => d.ci_lo * 100);
  const ciHi = curve.map(d => d.ci_hi * 100);
  if (mcChart) { mcChart.destroy(); mcChart = null; }
  const canvas = document.getElementById("mcChart");
  if (!canvas) return;
  mcChart = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      labels: ns,
      datasets: [
        { label: "CI upper", data: ciHi, fill: "+1", borderWidth: 0, pointRadius: 0, backgroundColor: ACCENT_FILL, tension: 0.3 },
        { label: "CI lower", data: ciLo, fill: false, borderWidth: 0, pointRadius: 0 },
        { label: "P(Collapse)", data: probs, borderColor: ACCENT, borderWidth: 2, pointRadius: 0, tension: 0.3 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { filter: i => !i.text.includes("CI"), font: { size: 11 } } } },
      scales: {
        x: { title: { display: true, text: "Patients (n)" }, grid: { color: "#e8e8ec" } },
        y: { min: 0, max: 100, title: { display: true, text: "Estimated P(Collapse) %" }, ticks: { callback: v => v + "%" }, grid: { color: "#e8e8ec" } },
      },
    },
  });
  window.mcChart = mcChart;
}

function renderUtilTable(util) {
  const el = document.getElementById("utilTable");
  if (!el) return;
  const entries = Object.entries(util);
  if (!entries.length) { el.innerHTML = `<p class="placeholder">No 50% threshold in range.</p>`; return; }
  el.innerHTML = `<table class="matrix-table"><thead><tr><th>Resource</th><th>Util.</th></tr></thead>
    <tbody>${entries.map(([k, v]) => `<tr><td class="row-label">${formatName(k)}</td><td>${pct(v)}</td></tr>`).join("")}</tbody></table>`;
}

/* ── Sensitivity ───────────────────────────────────────────────── */

async function runSensitivity() {
  if (running) return;
  hideError();
  setLoading(true);
  const payload = collectPayload();
  payload.max_patients = Math.min(40, parseInt(document.getElementById("max_patients").value, 10) || 40);
  payload.trials_per_n = Math.min(30, parseInt(document.getElementById("trials_per_n").value, 10) || 25);
  try {
    const data = await postJSON("/api/sensitivity", payload);
    renderSensitivity(data);
    HSLabExport?.store("sensitivity", data, payload);
    switchTab("sensitivity");
  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false);
  }
}

function renderSensitivity(data) {
  const el = document.getElementById("sensitivityResults");
  if (!el) return;
  const rows = data.rows || [];
  el.innerHTML = `
    <p class="section-desc">Baseline n<sub>50</sub> = ${data.n50_baseline ?? EMPTY}. ${escapeHtml(data.elasticity_interpretation || "")}</p>
    <table class="matrix-table">
      <thead><tr>
        <th>Resource</th><th>Baseline C</th><th>+&Delta;c</th><th>New C</th>
        <th>n<sub>50</sub> baseline</th><th>n<sub>50</sub> perturbed</th><th>&Delta;n<sub>50</sub></th><th>&epsilon;<sub>k</sub> (discrete marginal)</th>
      </tr></thead>
      <tbody>${rows.map(r => `<tr>
        <td class="row-label">${formatName(r.resource)}</td>
        <td>${r.baseline_capacity}</td>
        <td>+${r.added_capacity}</td>
        <td>${r.new_capacity}</td>
        <td>${r.n50_baseline ?? EMPTY}</td>
        <td>${r.n50_perturbed ?? EMPTY}</td>
        <td>${r.delta_n50 ?? EMPTY}</td>
        <td>${r.elasticity != null ? r.elasticity.toFixed(3) : EMPTY}</td>
      </tr>`).join("")}</tbody>
    </table>`;
}

/* ── Phase 2 time model ────────────────────────────────────────── */

async function runDynamic() {
  if (running) return;
  hideError();
  setLoading(true);
  const payload = collectPayload();
  payload.horizon_hours = parseInt(document.getElementById("horizon_hours")?.value, 10) || 48;
  payload.arrivals_per_step = parseInt(document.getElementById("arrivals_per_step")?.value, 10) || 2;
  payload.normal_staffing_multiplier = parseFloat(document.getElementById("normal_staffing_multiplier")?.value);
  payload.handover_staffing_multiplier = parseFloat(document.getElementById("handover_staffing_multiplier")?.value);
  payload.weekend_staffing_multiplier = parseFloat(document.getElementById("weekend_staffing_multiplier")?.value);
  try {
    const data = await postJSON("/api/dynamic_simulation", payload);
    renderDynamic(data);
    HSLabExport?.store("timemodel", data, payload);
    switchTab("timemodel");
  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false);
  }
}

function renderDynamic(data) {
  const el = document.getElementById("dynamicResults");
  if (!el) return;
  const m = data.secondary_metrics || {};
  const last = data.last_snapshot || {};
  const counts = data.state_counts || {};
  const bottleneck = m.resource_bottleneck_exposure_hours || {};
  const trace = data.example_trace || [];
  el.innerHTML = `
    <p class="note">${escapeHtml(data.parameter_status || "")}</p>
    <p class="section-desc">t = ${data.horizon_hours ?? EMPTY} h, &Delta;t = ${data.dt_hours ?? EMPTY} h.
      Fatigue state: ${escapeHtml(data.fatigue?.state || EMPTY)}.
      Last Banker's snapshot: ${last.banker_safe ? "SAFE" : "UNSAFE"}.</p>
    <div class="mc-summary compact">
      <div class="stat"><span class="stat-label">Overflow event rate</span><span class="stat-value">${m.overflow_event_rate != null ? m.overflow_event_rate.toFixed(3) : EMPTY}</span></div>
      <div class="stat"><span class="stat-label">Mean overflow hours</span><span class="stat-value">${m.mean_overflow_duration != null ? m.mean_overflow_duration.toFixed(2) : EMPTY}</span></div>
      <div class="stat"><span class="stat-label">Max overflow hours</span><span class="stat-value">${m.maximum_overflow_duration ?? EMPTY}</span></div>
      <div class="stat"><span class="stat-label">Fraction overflowed</span><span class="stat-value">${m.fraction_of_patients_experiencing_overflow != null ? pct(m.fraction_of_patients_experiencing_overflow) : EMPTY}</span></div>
      <div class="stat"><span class="stat-label">Fatigue duration (h)</span><span class="stat-value">${m.fatigue_duration ?? EMPTY}</span></div>
      <div class="stat"><span class="stat-label">Unsafe timesteps</span><span class="stat-value">${m.banker_unsafe_timesteps ?? EMPTY}</span></div>
    </div>
    <h3>Patient states</h3>
    <table class="matrix-table"><thead><tr><th>State</th><th>Count</th></tr></thead>
      <tbody>${Object.entries(counts).map(([k, v]) => `<tr><td class="row-label">${k}</td><td>${v}</td></tr>`).join("")}</tbody>
    </table>
    <h3>Bottleneck exposure (hours with Available = 0)</h3>
    <table class="matrix-table"><thead><tr><th>Resource</th><th>Hours</th></tr></thead>
      <tbody>${Object.entries(bottleneck).map(([k, v]) => `<tr><td class="row-label">${formatName(k)}</td><td>${v}</td></tr>`).join("")}</tbody>
    </table>
    <h3>Example trace</h3>
    <div class="steps-container">${trace.length ? trace.map(ev => `
      <div class="step-card">
        <div class="step-meta">t=${ev.t} · ${escapeHtml(ev.kind)}</div>
        <div class="step-msg">${escapeHtml(summarizeDynamicEvent(ev))}</div>
      </div>`).join("") : `<p class="placeholder">No events.</p>`}</div>
    <p class="note">${escapeHtml(data.preemption?.reason || "")}</p>
  `;
}

function summarizeDynamicEvent(ev) {
  if (ev.kind === "capacity") {
    return `C=[${(ev.C || []).join(", ")}]  W=[${(ev.W || []).join(", ")}]  m=${ev.staffing_multiplier}`;
  }
  if (ev.kind === "overflow") {
    return `${ev.patient || ""} ${ev.cause || ""} ${(ev.missing || []).join(", ")}`;
  }
  if (ev.kind === "admit") {
    return `${ev.patient} -> ${ev.state} bundle=[${(ev.bundle || []).join(", ")}]`;
  }
  if (ev.kind === "complete") return `${ev.patient} completed`;
  if (ev.kind === "fatigue_onset") return `fatigue onset, alpha=${ev.alpha}, util=${ev.utilization}`;
  if (ev.kind === "fatigue_recovery") return `fatigue recovery, util=${ev.utilization}`;
  return JSON.stringify(ev);
}

/* ── Phase 3 ───────────────────────────────────────────────────── */

async function runPhase3() {
  if (running) return;
  hideError();
  setLoading(true);
  const payload = collectPayload();
  payload.max_patients = Math.min(16, parseInt(document.getElementById("max_patients")?.value, 10) || 16);
  payload.trials_per_n = Math.min(8, parseInt(document.getElementById("trials_per_n")?.value, 10) || 8);
  payload.horizon_hours = Math.min(24, parseInt(document.getElementById("horizon_hours")?.value, 10) || 16);
  payload.include_sensitivity = false;
  try {
    const data = await postJSON("/api/phase3_experiment", payload);
    renderPhase3(data);
    HSLabExport?.store("phase3", data, payload);
    switchTab("phase3");
  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false);
  }
}

function tagCell(obj) {
  if (!obj || typeof obj !== "object") return EMPTY;
  const klass = obj.classification || "";
  const val = obj.value;
  const shown = val == null ? EMPTY : (typeof val === "number" ? (Number.isInteger(val) ? String(val) : val.toFixed(4)) : String(val));
  return `${shown} <span class="note">[${escapeHtml(klass)}]</span>`;
}

function renderPhase3(data) {
  const el = document.getElementById("phase3Results");
  if (!el) return;
  const cal = data.calibration || {};
  const prov = cal.series_provenance || {};
  const summary = cal.calibration_summary || {};
  const params = cal.parameters || {};
  const models = data.models || {};
  const copula = data.copula || {};
  const families = data.experiment_families || {};
  const repro = data.reproducibility || {};
  const avail = prov.availability_status || summary.availability_status || "";
  const losW = summary.los_ward || {};
  const losI = summary.los_icu || {};
  const sens = data.empirical_assumption_sensitivity || {};
  const sensRows = (sens.rows || []).map(r => `<tr>
      <td>${escapeHtml(r.parameter || "")}</td>
      <td>${r.scale != null ? r.scale : EMPTY}</td>
      <td>${r.overflow_event_rate != null ? r.overflow_event_rate.toFixed(3) : EMPTY}</td>
      <td>${r.mean_overflow_duration != null ? r.mean_overflow_duration.toFixed(2) : EMPTY}</td>
    </tr>`).join("");
  el.innerHTML = `
    <p class="note"><strong>Availability:</strong> ${escapeHtml(avail)} · source ${escapeHtml(prov.source_id || "")} ·
      ${escapeHtml(prov.classification || "")} · ${escapeHtml(prov.current_vs_historical || "")}.
      This is an external epidemiological / hospital-activity signal, not real-time occupancy of a named hospital.</p>
    <p class="note">Metric: ${escapeHtml(summary.metric || "")}. Geographic scope: ${escapeHtml(summary.geographic_scope || "")}.
      Access: ${escapeHtml(summary.timestamp_access || "")}. Coverage: ${escapeHtml(JSON.stringify(summary.coverage || {}))}.</p>
    <p class="note">${escapeHtml(cal.uncertainty_labels?.not_real_world_ci || "")} ${escapeHtml(cal.uncertainty_labels?.bootstrap || "")}</p>
    <h3>Experiment families</h3>
    <p class="note"><strong>${escapeHtml(families.static_banker_collapse?.title || "Static Banker collapse analysis")}</strong> —
      ${escapeHtml(families.static_banker_collapse?.note || "")}</p>
    <p class="note"><strong>${escapeHtml(families.dynamic_empirically_informed?.title || "Dynamic empirically informed simulation")}</strong> —
      ${escapeHtml(families.dynamic_empirically_informed?.note || "")}</p>
    <h3>Calibration summary</h3>
    <table class="matrix-table">
      <thead><tr><th>Item</th><th>Value</th></tr></thead>
      <tbody>
        <tr><td class="row-label">Arrival model</td><td>${escapeHtml(String(summary.arrival_model || EMPTY))} [${escapeHtml(params.arrival_model?.classification || "")}]</td></tr>
        <tr><td class="row-label">Arrival mean</td><td>${summary.arrival_mean != null ? Number(summary.arrival_mean).toFixed(4) : EMPTY}</td></tr>
        <tr><td class="row-label">Arrival variance</td><td>${summary.arrival_variance != null ? Number(summary.arrival_variance).toFixed(4) : EMPTY}</td></tr>
        <tr><td class="row-label">Dispersion D=Var/Mean</td><td>${summary.dispersion != null ? Number(summary.dispersion).toFixed(4) : EMPTY}</td></tr>
        <tr><td class="row-label">Selection</td><td>${escapeHtml(summary.selection_reason || EMPTY)}</td></tr>
        <tr><td class="row-label">NB parameterization</td><td>${escapeHtml(summary.nbinom_parameterization || EMPTY)}</td></tr>
        <tr><td class="row-label">LOS method</td><td>${escapeHtml(summary.los_method || EMPTY)}</td></tr>
        <tr><td class="row-label">Ward LOS selected</td><td>${escapeHtml(losW.selected_family || EMPTY)} SSE=${losW.reconstruction_error_sse != null ? Number(losW.reconstruction_error_sse).toFixed(4) : EMPTY}</td></tr>
        <tr><td class="row-label">ICU LOS selected</td><td>${escapeHtml(losI.selected_family || EMPTY)} SSE=${losI.reconstruction_error_sse != null ? Number(losI.reconstruction_error_sse).toFixed(4) : EMPTY}</td></tr>
        <tr><td class="row-label">Observed ward quantiles</td><td>${escapeHtml(JSON.stringify(losW.observed_quantiles || {}))}</td></tr>
        <tr><td class="row-label">Reconstructed ward quantiles</td><td>${escapeHtml(JSON.stringify(losW.reconstructed_quantiles || {}))}</td></tr>
        <tr><td class="row-label">Weekday relative rates (Mon–Sun)</td><td>${escapeHtml(JSON.stringify(summary.weekday_relative_rates || []))}</td></tr>
        <tr><td class="row-label">Occupancy ICU/MV ratio</td><td>${tagCell(params.p_icu_given_hospital_occupancy)}</td></tr>
      </tbody>
    </table>
    <p class="note">Copula used: ${copula.used ? "yes" : "no"}. ${escapeHtml(copula.reason || "")}</p>
    <h3>Model A vs B vs C</h3>
    <table class="matrix-table">
      <thead><tr>
        <th>Model</th><th>n<sub>50</sub> (static)</th><th>P(collapse) at max n (static)</th>
        <th>Overflow rate (dynamic)</th><th>Mean overflow hours</th><th>Fraction overflowed</th>
      </tr></thead>
      <tbody>${["A","B","C"].map(k => {
        const m = models[k] || {};
        const ov = m.overflow || {};
        return `<tr>
          <td class="row-label">${escapeHtml(m.label || k)}: ${escapeHtml(m.description || "")}</td>
          <td>${m.n50 ?? EMPTY}</td>
          <td>${m.p_collapse_at_max_n != null ? fmtProb(m.p_collapse_at_max_n) : EMPTY}</td>
          <td>${ov.overflow_event_rate != null ? ov.overflow_event_rate.toFixed(3) : EMPTY}</td>
          <td>${ov.mean_overflow_duration != null ? ov.mean_overflow_duration.toFixed(2) : EMPTY}</td>
          <td>${ov.fraction_overflowed != null ? pct(ov.fraction_overflowed) : EMPTY}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>
    <p class="note">n<sub>50</sub> is from the static Banker family only. Overflow metrics are from the dynamic family. Differences are observed simulation differences, not statistical significance tests.</p>
    <h3>Empirical assumption sensitivity (Model C dynamic)</h3>
    <p class="note">${escapeHtml(sens.note || "")}</p>
    <table class="matrix-table">
      <thead><tr><th>Parameter</th><th>Scale</th><th>Overflow rate</th><th>Mean overflow hours</th></tr></thead>
      <tbody>${sensRows || `<tr><td colspan="4">${EMPTY}</td></tr>`}</tbody>
    </table>
    <p class="note">Reproducibility: seed=${escapeHtml(String(repro.random_seed ?? ""))}, trials=${escapeHtml(String(repro.trial_count ?? ""))},
      source=${escapeHtml(String(repro.data_source ?? ""))}, availability=${escapeHtml(String(repro.availability_status ?? ""))},
      calibrated_at=${escapeHtml(String(repro.calibration_timestamp ?? ""))}.</p>
  `;
}

/* ── Interactive Monte Carlo experiment ───────────────────────── */

let lastMcExperiment = null;
let mcExperimentAbort = null;
let convState = { n: null, t: [], p: [], lo: [], hi: [] };
let curveRows = [];

function collectExperimentPayload() {
  const payload = collectPayload();
  payload.min_patients = parseInt(document.getElementById("exp_min_n").value, 10);
  payload.max_patients = parseInt(document.getElementById("exp_max_n").value, 10);
  payload.trials_per_n = parseInt(document.getElementById("exp_trials").value, 10);
  payload.seed = parseInt(document.getElementById("exp_seed").value, 10);
  payload.model = document.getElementById("exp_model").value;
  return payload;
}

function updateExpConfigSummary() {
  const el = document.getElementById("expConfigSummary");
  if (!el) return;
  const model = document.getElementById("exp_model");
  const label = model?.selectedOptions?.[0]?.text || model?.value || "";
  const minN = document.getElementById("exp_min_n")?.value;
  const maxN = document.getElementById("exp_max_n")?.value;
  const trials = document.getElementById("exp_trials")?.value;
  const seed = document.getElementById("exp_seed")?.value;
  el.innerHTML = `<strong>Monte Carlo Experiment</strong><br>
    Patient range: ${escapeHtml(minN)} → ${escapeHtml(maxN)}<br>
    Trials per patient count: ${escapeHtml(trials)}<br>
    Model: ${escapeHtml(label)}<br>
    Seed: ${escapeHtml(seed)}`;
}

function stopMcExperiment() {
  mcExperimentAbort?.abort();
}

function resetConvForN(n) {
  convState = { n, t: [], p: [], lo: [], hi: [] };
}

function plotlyLayout(title, xTitle, yTitle) {
  return {
    title: { text: title, font: { size: 13 } },
    margin: { t: 36, r: 16, b: 40, l: 52 },
    paper_bgcolor: "#fff",
    plot_bgcolor: "#fff",
    font: { family: "Segoe UI, system-ui, sans-serif", size: 11, color: "#1f1f24" },
    xaxis: { title: xTitle, gridcolor: "#e8e8ec" },
    yaxis: { title: yTitle, range: [0, 1], gridcolor: "#e8e8ec" },
    showlegend: true,
    legend: { orientation: "h", y: -0.22 },
    hovermode: "closest",
    autosize: true,
  };
}

function requirePlotly(el) {
  if (typeof Plotly !== "undefined") return true;
  if (el) {
    el.innerHTML = '<p class="plot-error">Plotly failed to load. Check your network connection and refresh the page.</p>';
  }
  return false;
}

function drawPlotly(el, traces, layout) {
  const config = { displayModeBar: false, responsive: true };
  if (!el._plotlyInit) {
    Plotly.newPlot(el, traces, layout, config);
    el._plotlyInit = true;
  } else {
    Plotly.react(el, traces, layout, config);
  }
  requestAnimationFrame(() => {
    if (el && el.offsetParent !== null) Plotly.Plots.resize(el);
  });
}

function renderConvPlot() {
  const el = document.getElementById("expConvPlot");
  if (!el || !requirePlotly(el)) return;
  const traces = [
    {
      x: convState.t, y: convState.hi, name: "Wilson upper",
      mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false,
    },
    {
      x: convState.t, y: convState.lo, name: "95% Wilson CI",
      mode: "lines", line: { width: 0 }, fill: "tonexty",
      fillcolor: "rgba(122,31,46,0.12)", hoverinfo: "skip",
    },
    {
      x: convState.t, y: convState.p, name: "p̂_t = K_t / t",
      mode: "lines", line: { color: "#7a1f2e", width: 2 },
      customdata: convState.t.map((_, i) => [convState.lo[i], convState.hi[i]]),
      hovertemplate: "trial %{x}<br>p̂=%{y:.4f}<br>Wilson [%{customdata[0]:.4f}, %{customdata[1]:.4f}]<extra></extra>",
    },
    {
      x: [convState.t[0] || 0, convState.t[convState.t.length - 1] || 1],
      y: [0.5, 0.5], name: "0.50 reference",
      mode: "lines", line: { color: "#5a5a66", width: 1, dash: "dash" },
    },
  ];
  drawPlotly(el, traces, plotlyLayout(`Running estimate at n = ${convState.n ?? "—"}`, "Completed trials t", "Estimated P(collapse)"));
}

function renderCurvePlot(n50) {
  const el = document.getElementById("expCurvePlot");
  if (!el || !requirePlotly(el)) return;
  const ns = curveRows.map(r => r.patient_count ?? r.n);
  const p = curveRows.map(r => r.collapse_probability ?? r.p_collapse);
  const lo = curveRows.map(r => r.wilson_lower ?? r.ci_lo);
  const hi = curveRows.map(r => r.wilson_upper ?? r.ci_hi);
  const trials = curveRows.map(r => r.trials);
  const unsafe = curveRows.map(r => r.collapse_trials);
  const traces = [
    { x: ns, y: hi, mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
    {
      x: ns, y: lo, name: "95% Wilson CI", mode: "lines", line: { width: 0 },
      fill: "tonexty", fillcolor: "rgba(122,31,46,0.12)", hoverinfo: "skip",
    },
    {
      x: ns, y: p, name: "p̂_n", mode: "lines+markers",
      line: { color: "#7a1f2e", width: 2 }, marker: { size: 5, color: "#7a1f2e" },
      customdata: ns.map((_, i) => [trials[i], unsafe[i], lo[i], hi[i]]),
      hovertemplate: "n=%{x}<br>P(collapse)=%{y:.4f}<br>trials=%{customdata[0]}<br>collapse count=%{customdata[1]}<br>Wilson [%{customdata[2]:.4f}, %{customdata[3]:.4f}]<extra></extra>",
    },
    {
      x: [ns[0] || 0, ns[ns.length - 1] || 1], y: [0.5, 0.5], name: "0.50",
      mode: "lines", line: { color: "#5a5a66", width: 1, dash: "dash" },
    },
  ];
  if (n50 != null) {
    const hit = curveRows.find(r => (r.patient_count ?? r.n) === n50);
    traces.push({
      x: [n50], y: [hit ? (hit.collapse_probability ?? hit.p_collapse) : 0.5],
      name: "n50", mode: "markers", marker: { size: 11, color: "#1f1f24", symbol: "diamond" },
      hovertemplate: "n50=%{x}<br>p̂=%{y:.4f}<extra></extra>",
    });
  }
  drawPlotly(el, traces, plotlyLayout("Estimated P(collapse) vs patient load", "Patient load n", "Estimated P(collapse)"));
}

function renderExpProgress(ev) {
  const el = document.getElementById("expProgress");
  if (!el) return;
  el.innerHTML = `
    <div><span class="stat-label">Patient load</span><span class="stat-value">${ev.n}</span></div>
    <div><span class="stat-label">Trial</span><span class="stat-value">${ev.trial} / ${ev.trials_per_n}</span></div>
    <div><span class="stat-label">SAFE (non-collapse)</span><span class="stat-value">${ev.safe_trials}</span></div>
    <div><span class="stat-label">Collapse trials K<sub>t</sub></span><span class="stat-value">${ev.collapse_trials}</span></div>
    <div><span class="stat-label">Banker's UNSAFE</span><span class="stat-value">${ev.unsafe_trials}</span></div>
    <div><span class="stat-label">Estimated P(collapse)</span><span class="stat-value">${Number(ev.p_hat).toFixed(4)}</span></div>
    <div><span class="stat-label">Completed / planned</span><span class="stat-value">${ev.completed_trials} / ${ev.planned_trials}</span></div>
  `;
}

function renderExpResultCard(payload) {
  const el = document.getElementById("expResultCard");
  if (!el) return;
  const exp = payload.experiment || {};
  const range = exp.patient_range || {};
  const results = payload.results || [];
  const maxP = results.reduce((m, r) => Math.max(m, r.collapse_probability || 0), 0);
  const totalTrials = results.reduce((s, r) => s + (r.trials || 0), 0);
  el.hidden = false;
  el.innerHTML = `
    <h3>Experiment completed</h3>
    <dl>
      <dt>Model</dt><dd>${escapeHtml(exp.model_label || exp.model || "")}</dd>
      <dt>Trials per patient load</dt><dd>${escapeHtml(String(exp.trials_per_load ?? ""))}</dd>
      <dt>Patient range</dt><dd>${escapeHtml(String(range.min))}–${escapeHtml(String(range.max))}</dd>
      <dt>n<sub>50</sub></dt><dd>${payload.n50 ?? "not reached in range"}</dd>
      <dt>Maximum observed P(collapse)</dt><dd>${maxP.toFixed(4)}</dd>
      <dt>Total simulation trials</dt><dd>${totalTrials}</dd>
      <dt>Seed</dt><dd>${escapeHtml(String(exp.seed ?? ""))}</dd>
      <dt>Data source</dt><dd>${escapeHtml(String((payload.provenance || {}).data_source || ""))}
        [${escapeHtml(String((payload.provenance || {}).availability_status || ""))}]</dd>
    </dl>
    <p class="note">${escapeHtml((payload.provenance || {}).note || "")}</p>
  `;
  document.getElementById("export-experiment")?.removeAttribute("hidden");
}

async function downloadExperiment(kind) {
  if (!lastMcExperiment) return;
  try {
    const resp = await fetch(`/api/mc_experiment/export.${kind}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastMcExperiment),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.details || data.error || "Export failed");
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = kind === "csv" ? "mc_experiment.csv" : "mc_experiment.json";
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    showError(err.message);
  }
}

function handleMcEvent(ev) {
  if (ev.event === "started") {
    curveRows = [];
    resetConvForN(null);
    document.getElementById("expResultCard").hidden = true;
    document.getElementById("export-experiment")?.setAttribute("hidden", "");
    return;
  }
  if (ev.event === "progress") {
    if (convState.n !== ev.n) resetConvForN(ev.n);
    convState.t.push(ev.trial);
    convState.p.push(ev.p_hat);
    convState.lo.push(ev.wilson_lower);
    convState.hi.push(ev.wilson_upper);
    renderExpProgress(ev);
    renderConvPlot();
    return;
  }
  if (ev.event === "n_complete") {
    const row = ev.row || {};
    curveRows.push({
      n: row.n,
      patient_count: row.n,
      p_collapse: row.p_collapse,
      collapse_probability: row.p_collapse,
      ci_lo: row.ci_lo,
      ci_hi: row.ci_hi,
      wilson_lower: row.ci_lo,
      wilson_upper: row.ci_hi,
      trials: row.trials,
      collapse_trials: row.collapse_trials,
    });
    const n50 = ev.n50;
    renderCurvePlot(n50);
    return;
  }
  if (ev.event === "complete") {
    lastMcExperiment = ev;
    HSLabExport?.store("experiment", ev);
    curveRows = ev.results || curveRows;
    renderCurvePlot(ev.n50);
    renderExpResultCard(ev);
    return;
  }
  if (ev.event === "error") {
    showError(ev.error || "Simulation failed.");
  }
}

async function runMcExperiment() {
  if (running) return;
  hideError();
  updateExpConfigSummary();
  setLoading(true);
  const stopBtn = document.getElementById("btnMcExperimentStop");
  if (stopBtn) stopBtn.disabled = false;
  const payload = collectExperimentPayload();
  mcExperimentAbort = new AbortController();
  try {
    const resp = await fetch("/api/mc_experiment/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: mcExperimentAbort.signal,
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.details ? `${data.error}: ${data.details}` : (data.error || `HTTP ${resp.status}`));
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const chunks = buf.split("\n\n");
      buf = chunks.pop() || "";
      for (const block of chunks) {
        const line = block.split("\n").find(l => l.startsWith("data: "));
        if (!line) continue;
        handleMcEvent(JSON.parse(line.slice(6)));
      }
    }
  } catch (err) {
    if (err.name === "AbortError") {
      showError("Experiment interrupted.");
    } else {
      showError(err.message);
    }
  } finally {
    setLoading(false);
    if (stopBtn) stopBtn.disabled = true;
    mcExperimentAbort = null;
  }
}
