/**
 * Client-side CSV / PDF report downloads for all simulator experiments.
 */
"use strict";

const HSLabExport = (() => {
  const REPORT_TITLES = {
    bankers: "Banker's Safety Analysis",
    mc: "Monte Carlo Collapse Estimation",
    experiment: "Monte Carlo Experiment",
    sensitivity: "Sensitivity Analysis",
    timemodel: "Time-Dependent Hospital Model",
    phase3: "Phase 3 Empirical Calibration",
  };

  const reports = {};

  function store(kind, data, inputs = null) {
    reports[kind] = { data, inputs, storedAt: new Date().toISOString() };
    const bar = document.getElementById(`export-${kind}`);
    if (bar) bar.hidden = false;
  }

  function get(kind) {
    return reports[kind] || null;
  }

  function csvCell(value) {
    if (value == null) return "";
    const s = String(value);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  function csvSection(title, headers, rows) {
    const lines = [`# ${title}`, headers.join(",")];
    for (const row of rows) {
      lines.push(headers.map(h => csvCell(row[h])).join(","));
    }
    return lines.join("\n");
  }

  function downloadText(text, filename, mime) {
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  function bankersCsv(report) {
    const d = report.data;
    const parts = [
      csvSection("Summary", ["field", "value"], [
        { field: "report", value: REPORT_TITLES.bankers },
        { field: "generated_at", value: report.storedAt },
        { field: "safe", value: d.safe },
        { field: "patients_admitted", value: d.patients_admitted },
        { field: "patients_requested", value: d.patients_requested },
        { field: "blocking_resource", value: d.blocking_resource || "" },
        { field: "safe_sequence", value: (d.safe_sequence || []).join(" -> ") },
      ]),
    ];
    const names = d.resource_names || [];
    parts.push(csvSection("Total Resources", ["resource", "value"],
      names.map((n, i) => ({ resource: n, value: d.total[i] }))));
    parts.push(csvSection("Available Resources", ["resource", "value"],
      names.map((n, i) => ({ resource: n, value: d.available[i] }))));
    const pids = Object.keys(d.allocation || {});
    const allocRows = [];
    for (const pid of pids) {
      (d.allocation[pid] || []).forEach((val, i) => {
        allocRows.push({ patient: pid, resource: names[i], allocation: val, max: d.max_demand[pid][i], need: d.need[pid][i] });
      });
    }
    parts.push(csvSection("Patient Resources", ["patient", "resource", "allocation", "max", "need"], allocRows));
    const stepRows = (d.steps || []).map(s => ({
      step: s.step,
      action: s.action,
      patient: s.patient || "",
      message: s.message || "",
      need_le_work: s.need_le_work ?? "",
    }));
    parts.push(csvSection("Safety Trace", ["step", "action", "patient", "message", "need_le_work"], stepRows));
    return parts.join("\n\n");
  }

  function monteCarloCsv(report) {
    const d = report.data;
    const curve = d.probability_curve || [];
    const risk = d.risk_summary || {};
    const parts = [
      csvSection("Summary", ["field", "value"], [
        { field: "report", value: REPORT_TITLES.mc },
        { field: "generated_at", value: report.storedAt },
        { field: "trials_per_n", value: report.inputs?.trials_per_n },
        { field: "max_patients", value: report.inputs?.max_patients },
        { field: "seed", value: report.inputs?.seed },
        { field: "threshold_10pct", value: risk.threshold_10pct },
        { field: "threshold_50pct", value: risk.threshold_50pct },
        { field: "threshold_70pct", value: risk.threshold_70pct },
        { field: "n50", value: risk.n50 },
      ]),
      csvSection("Probability Curve", [
        "n", "p_collapse", "ci_lo", "ci_hi", "p_unsafe", "p_admission_failure", "collapse_trials", "trials",
      ], curve.map(row => ({
        n: row.n,
        p_collapse: row.p_collapse,
        ci_lo: row.ci_lo,
        ci_hi: row.ci_hi,
        p_unsafe: row.p_unsafe,
        p_admission_failure: row.p_admission_failure,
        collapse_trials: row.collapse_trials,
        trials: row.trials,
      }))),
    ];
    const util = risk.collapse_utilization || {};
    parts.push(csvSection("Utilization at 50% threshold", ["resource", "utilization"],
      Object.entries(util).map(([k, v]) => ({ resource: k, utilization: v }))));
    return parts.join("\n\n");
  }

  function sensitivityCsv(report) {
    const d = report.data;
    const rows = d.rows || [];
    return [
      csvSection("Summary", ["field", "value"], [
        { field: "report", value: REPORT_TITLES.sensitivity },
        { field: "generated_at", value: report.storedAt },
        { field: "n50_baseline", value: d.n50_baseline },
        { field: "interpretation", value: d.elasticity_interpretation || "" },
      ]),
      csvSection("Sensitivity Rows", [
        "resource", "baseline_capacity", "added_capacity", "new_capacity",
        "n50_baseline", "n50_perturbed", "delta_n50", "elasticity",
      ], rows.map(r => ({
        resource: r.resource,
        baseline_capacity: r.baseline_capacity,
        added_capacity: r.added_capacity,
        new_capacity: r.new_capacity,
        n50_baseline: r.n50_baseline,
        n50_perturbed: r.n50_perturbed,
        delta_n50: r.delta_n50,
        elasticity: r.elasticity,
      }))),
    ].join("\n\n");
  }

  function timemodelCsv(report) {
    const d = report.data;
    const m = d.secondary_metrics || {};
    const parts = [
      csvSection("Summary", ["field", "value"], [
        { field: "report", value: REPORT_TITLES.timemodel },
        { field: "generated_at", value: report.storedAt },
        { field: "horizon_hours", value: d.horizon_hours },
        { field: "dt_hours", value: d.dt_hours },
        { field: "overflow_event_rate", value: m.overflow_event_rate },
        { field: "mean_overflow_duration", value: m.mean_overflow_duration },
        { field: "maximum_overflow_duration", value: m.maximum_overflow_duration },
        { field: "fraction_overflowed", value: m.fraction_of_patients_experiencing_overflow },
        { field: "fatigue_duration", value: m.fatigue_duration },
        { field: "banker_unsafe_timesteps", value: m.banker_unsafe_timesteps },
        { field: "last_banker_safe", value: d.last_snapshot?.banker_safe },
      ]),
      csvSection("Patient States", ["state", "count"],
        Object.entries(d.state_counts || {}).map(([k, v]) => ({ state: k, count: v }))),
      csvSection("Bottleneck Exposure Hours", ["resource", "hours"],
        Object.entries(m.resource_bottleneck_exposure_hours || {}).map(([k, v]) => ({ resource: k, hours: v }))),
    ];
    const traceRows = (d.example_trace || []).map(ev => ({
      t: ev.t,
      kind: ev.kind,
      detail: summarizeTrace(ev),
    }));
    parts.push(csvSection("Example Trace", ["t", "kind", "detail"], traceRows));
    return parts.join("\n\n");
  }

  function summarizeTrace(ev) {
    if (ev.kind === "capacity") return `C=[${(ev.C || []).join(",")}] W=[${(ev.W || []).join(",")}] m=${ev.staffing_multiplier}`;
    if (ev.kind === "overflow") return `${ev.patient || ""} ${ev.cause || ""} ${(ev.missing || []).join(",")}`;
    if (ev.kind === "admit") return `${ev.patient} -> ${ev.state}`;
    if (ev.kind === "complete") return `${ev.patient} completed`;
    return JSON.stringify(ev);
  }

  function phase3Csv(report) {
    const d = report.data;
    const cal = d.calibration || {};
    const summary = cal.calibration_summary || {};
    const models = d.models || {};
    const parts = [
      csvSection("Summary", ["field", "value"], [
        { field: "report", value: REPORT_TITLES.phase3 },
        { field: "generated_at", value: report.storedAt },
        { field: "availability", value: (cal.series_provenance || {}).availability_status },
        { field: "arrival_model", value: summary.arrival_model },
        { field: "arrival_mean", value: summary.arrival_mean },
        { field: "dispersion", value: summary.dispersion },
      ]),
      csvSection("Model Comparison", [
        "model", "n50", "p_collapse_at_max_n", "overflow_rate", "mean_overflow_hours", "fraction_overflowed",
      ], ["A", "B", "C"].map(k => {
        const m = models[k] || {};
        const ov = m.overflow || {};
        return {
          model: k,
          n50: m.n50,
          p_collapse_at_max_n: m.p_collapse_at_max_n,
          overflow_rate: ov.overflow_event_rate,
          mean_overflow_hours: ov.mean_overflow_duration,
          fraction_overflowed: ov.fraction_overflowed,
        };
      })),
    ];
    const sens = d.empirical_assumption_sensitivity || {};
    parts.push(csvSection("Empirical Assumption Sensitivity", [
      "parameter", "scale", "overflow_event_rate", "mean_overflow_duration",
    ], (sens.rows || []).map(r => ({
      parameter: r.parameter,
      scale: r.scale,
      overflow_event_rate: r.overflow_event_rate,
      mean_overflow_duration: r.mean_overflow_duration,
    }))));
    return parts.join("\n\n");
  }

  function experimentCsv(report) {
    const d = report.data;
    const exp = d.experiment || {};
    const rows = d.results || [];
    const parts = [
      csvSection("Experiment", ["field", "value"], [
        { field: "report", value: REPORT_TITLES.experiment },
        { field: "generated_at", value: report.storedAt },
        { field: "model", value: exp.model },
        { field: "seed", value: exp.seed },
        { field: "trials_per_load", value: exp.trials_per_load },
        { field: "patient_range", value: `${exp.patient_range?.min}-${exp.patient_range?.max}` },
        { field: "n50", value: d.n50 },
      ]),
      csvSection("Results", [
        "patient_count", "trials", "collapse_trials", "collapse_probability", "wilson_lower", "wilson_upper",
      ], rows.map(r => ({
        patient_count: r.patient_count,
        trials: r.trials,
        collapse_trials: r.collapse_trials,
        collapse_probability: r.collapse_probability,
        wilson_lower: r.wilson_lower,
        wilson_upper: r.wilson_upper,
      }))),
    ];
    return parts.join("\n\n");
  }

  const CSV_BUILDERS = {
    bankers: bankersCsv,
    mc: monteCarloCsv,
    sensitivity: sensitivityCsv,
    timemodel: timemodelCsv,
    phase3: phase3Csv,
    experiment: experimentCsv,
  };

  function downloadCsv(kind) {
    const report = reports[kind];
    if (!report) throw new Error("No results to export. Run the experiment first.");
    const builder = CSV_BUILDERS[kind];
    if (!builder) throw new Error(`Unknown report type: ${kind}`);
    downloadText(builder(report), `${kind}_report.csv`, "text/csv;charset=utf-8");
  }

  function requireJsPDF() {
    if (!window.jspdf?.jsPDF) throw new Error("PDF library failed to load. Refresh the page and try again.");
    return window.jspdf.jsPDF;
  }

  function pdfTable(doc, y, head, body, options = {}) {
    doc.autoTable({
      startY: y,
      head: [head],
      body,
      margin: { left: 14, right: 14 },
      styles: { fontSize: 8, cellPadding: 2 },
      headStyles: { fillColor: [122, 31, 46], textColor: 255 },
      ...options,
    });
    return doc.lastAutoTable.finalY + 6;
  }

  function pdfHeading(doc, y, text, size = 11) {
    const pageH = doc.internal.pageSize.getHeight();
    if (y > pageH - 20) {
      doc.addPage();
      y = 16;
    }
    doc.setFontSize(size);
    doc.setTextColor(122, 31, 46);
    doc.text(text, 14, y);
    doc.setTextColor(31, 31, 36);
    return y + size * 0.45 + 4;
  }

  function pdfMeta(doc, kind, report) {
    let y = 16;
    doc.setFontSize(15);
    doc.setTextColor(122, 31, 46);
    doc.text("Hospital Resource Stability Lab", 14, y);
    y += 8;
    doc.setFontSize(11);
    doc.setTextColor(31, 31, 36);
    doc.text(REPORT_TITLES[kind] || kind, 14, y);
    y += 6;
    doc.setFontSize(9);
    doc.setTextColor(90, 90, 102);
    doc.text(`Generated: ${new Date(report.storedAt).toLocaleString()}`, 14, y);
    y += 8;
    doc.setTextColor(31, 31, 36);
    return y;
  }

  async function plotlyImage(elementId, width = 760, height = 320) {
    const el = document.getElementById(elementId);
    if (!el || typeof Plotly === "undefined" || !el.data) return null;
    return Plotly.toImage(el, { format: "png", width, height });
  }

  function chartJsImage(chart) {
    if (!chart) return null;
    try {
      return chart.toBase64Image("image/png", 1);
    } catch {
      return null;
    }
  }

  function addPdfImage(doc, y, dataUrl, label) {
    if (!dataUrl) return y;
    const pageW = doc.internal.pageSize.getWidth();
    const pageH = doc.internal.pageSize.getHeight();
    const imgW = pageW - 28;
    const imgH = 72;
    if (y + imgH + 12 > pageH - 14) {
      doc.addPage();
      y = 16;
    }
    y = pdfHeading(doc, y, label, 10);
    doc.addImage(dataUrl, "PNG", 14, y, imgW, imgH);
    return y + imgH + 8;
  }

  function sensitivityChartImage(rows) {
    if (!rows.length) return null;
    const canvas = document.createElement("canvas");
    canvas.width = 720;
    canvas.height = 280;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const vals = rows.map(r => Math.abs(r.elasticity ?? 0));
    const maxV = Math.max(...vals, 0.001);
    const barW = Math.min(48, (canvas.width - 80) / rows.length - 8);
    const baseY = canvas.height - 40;
    rows.forEach((r, i) => {
      const v = Math.abs(r.elasticity ?? 0);
      const h = (v / maxV) * (canvas.height - 80);
      const x = 40 + i * (barW + 12);
      ctx.fillStyle = "#7a1f2e";
      ctx.fillRect(x, baseY - h, barW, h);
      ctx.fillStyle = "#5a5a66";
      ctx.font = "10px Segoe UI, sans-serif";
      ctx.save();
      ctx.translate(x + barW / 2, baseY + 14);
      ctx.rotate(-0.5);
      ctx.textAlign = "right";
      const label = (r.resource || "").replace(/_/g, " ").slice(0, 12);
      ctx.fillText(label, 0, 0);
      ctx.restore();
    });
    ctx.fillStyle = "#1f1f24";
    ctx.font = "12px Segoe UI, sans-serif";
    ctx.fillText("|epsilon_k| (discrete marginal sensitivity)", 14, 18);
    return canvas.toDataURL("image/png");
  }

  async function bankersPdf(report) {
    const JsPDF = requireJsPDF();
    const doc = new JsPDF();
    const d = report.data;
    let y = pdfMeta(doc, "bankers", report);

    y = pdfTable(doc, y, ["Field", "Value"], [
      ["SAFE", d.safe ? "Yes" : "No"],
      ["Admitted", `${d.patients_admitted} / ${d.patients_requested}`],
      ["Blocking resource", d.blocking_resource || "—"],
      ["Safe sequence", (d.safe_sequence || []).join(" → ") || "—"],
    ]);

    const names = d.resource_names || [];
    y = pdfHeading(doc, y, "Resource vectors");
    y = pdfTable(doc, y, ["Resource", "Total", "Available"], names.map((n, i) => [
      n.replace(/_/g, " "), d.total[i], d.available[i],
    ]));

    const pids = Object.keys(d.allocation || {});
    if (pids.length) {
      y = pdfHeading(doc, y, "Allocation matrix");
      const head = ["Patient", ...names.map(n => n.replace(/_/g, " "))];
      const body = pids.map(pid => [pid, ...(d.allocation[pid] || [])]);
      y = pdfTable(doc, y, head, body, { styles: { fontSize: 7 } });
    }

    const steps = (d.steps || []).slice(0, 40);
    if (steps.length) {
      y = pdfHeading(doc, y, "Safety trace (first 40 steps)");
      y = pdfTable(doc, y, ["Step", "Action", "Patient", "Message"], steps.map(s => [
        s.step, s.action, s.patient || "", (s.message || "").slice(0, 80),
      ]));
    }
    doc.save("bankers_report.pdf");
  }

  async function monteCarloPdf(report) {
    const JsPDF = requireJsPDF();
    const doc = new JsPDF();
    const d = report.data;
    const risk = d.risk_summary || {};
    let y = pdfMeta(doc, "mc", report);

    y = pdfTable(doc, y, ["Metric", "Value"], [
      ["10% collapse n", risk.threshold_10pct ?? "—"],
      ["50% collapse n", risk.threshold_50pct ?? "—"],
      ["70% collapse n", risk.threshold_70pct ?? "—"],
      ["Trials per n", report.inputs?.trials_per_n ?? "—"],
      ["Max patients", report.inputs?.max_patients ?? "—"],
      ["Seed", report.inputs?.seed ?? "—"],
    ]);

    const chartImg = chartJsImage(window.mcChart);
    y = addPdfImage(doc, y, chartImg, "Collapse probability curve");

    const curve = d.probability_curve || [];
    if (curve.length) {
      y = pdfHeading(doc, y, "Probability curve data");
      y = pdfTable(doc, y, ["n", "P(collapse)", "CI low", "CI high"], curve.map(row => [
        row.n,
        row.p_collapse?.toFixed(4),
        row.ci_lo?.toFixed(4),
        row.ci_hi?.toFixed(4),
      ]));
    }
    doc.save("monte_carlo_report.pdf");
  }

  async function sensitivityPdf(report) {
    const JsPDF = requireJsPDF();
    const doc = new JsPDF();
    const d = report.data;
    const rows = d.rows || [];
    let y = pdfMeta(doc, "sensitivity", report);

    y = pdfTable(doc, y, ["Field", "Value"], [
      ["Baseline n50", d.n50_baseline ?? "—"],
      ["Note", (d.elasticity_interpretation || "").slice(0, 120)],
    ]);

    const chartImg = sensitivityChartImage(rows);
    y = addPdfImage(doc, y, chartImg, "Discrete marginal sensitivity by resource");

    if (rows.length) {
      y = pdfHeading(doc, y, "Sensitivity table");
      pdfTable(doc, y, [
        "Resource", "Baseline C", "+Δc", "New C", "n50 base", "n50 pert", "Δn50", "ε_k",
      ], rows.map(r => [
        (r.resource || "").replace(/_/g, " "),
        r.baseline_capacity,
        `+${r.added_capacity}`,
        r.new_capacity,
        r.n50_baseline ?? "—",
        r.n50_perturbed ?? "—",
        r.delta_n50 ?? "—",
        r.elasticity != null ? r.elasticity.toFixed(3) : "—",
      ]));
    }
    doc.save("sensitivity_report.pdf");
  }

  async function timemodelPdf(report) {
    const JsPDF = requireJsPDF();
    const doc = new JsPDF();
    const d = report.data;
    const m = d.secondary_metrics || {};
    let y = pdfMeta(doc, "timemodel", report);

    y = pdfTable(doc, y, ["Metric", "Value"], [
      ["Horizon (h)", d.horizon_hours],
      ["Δt (h)", d.dt_hours],
      ["Overflow event rate", m.overflow_event_rate?.toFixed(3) ?? "—"],
      ["Mean overflow hours", m.mean_overflow_duration?.toFixed(2) ?? "—"],
      ["Max overflow hours", m.maximum_overflow_duration ?? "—"],
      ["Fraction overflowed", m.fraction_of_patients_experiencing_overflow?.toFixed(3) ?? "—"],
      ["Unsafe timesteps", m.banker_unsafe_timesteps ?? "—"],
      ["Last Banker's", d.last_snapshot?.banker_safe ? "SAFE" : "UNSAFE"],
    ]);

    y = pdfHeading(doc, y, "Patient states");
    y = pdfTable(doc, y, ["State", "Count"],
      Object.entries(d.state_counts || {}).map(([k, v]) => [k, v]));

    y = pdfHeading(doc, y, "Bottleneck exposure (hours)");
    y = pdfTable(doc, y, ["Resource", "Hours"],
      Object.entries(m.resource_bottleneck_exposure_hours || {}).map(([k, v]) => [k.replace(/_/g, " "), v]));

    const trace = (d.example_trace || []).slice(0, 25);
    if (trace.length) {
      y = pdfHeading(doc, y, "Example trace (first 25 events)");
      pdfTable(doc, y, ["t", "Kind", "Detail"], trace.map(ev => [
        ev.t, ev.kind, summarizeTrace(ev).slice(0, 90),
      ]));
    }
    doc.save("timemodel_report.pdf");
  }

  async function phase3Pdf(report) {
    const JsPDF = requireJsPDF();
    const doc = new JsPDF();
    const d = report.data;
    const cal = d.calibration || {};
    const summary = cal.calibration_summary || {};
    const models = d.models || {};
    let y = pdfMeta(doc, "phase3", report);

    y = pdfTable(doc, y, ["Calibration item", "Value"], [
      ["Availability", (cal.series_provenance || {}).availability_status || "—"],
      ["Arrival model", summary.arrival_model || "—"],
      ["Arrival mean", summary.arrival_mean?.toFixed(4) ?? "—"],
      ["Dispersion", summary.dispersion?.toFixed(4) ?? "—"],
      ["LOS method", summary.los_method || "—"],
    ]);

    y = pdfHeading(doc, y, "Model A vs B vs C");
    y = pdfTable(doc, y, [
      "Model", "n50", "P(collapse)", "Overflow rate", "Mean overflow h", "Frac. overflowed",
    ], ["A", "B", "C"].map(k => {
      const m = models[k] || {};
      const ov = m.overflow || {};
      return [
        k,
        m.n50 ?? "—",
        m.p_collapse_at_max_n != null ? m.p_collapse_at_max_n.toFixed(4) : "—",
        ov.overflow_event_rate?.toFixed(3) ?? "—",
        ov.mean_overflow_duration?.toFixed(2) ?? "—",
        ov.fraction_overflowed?.toFixed(3) ?? "—",
      ];
    }));

    const sens = d.empirical_assumption_sensitivity || {};
    const sensRows = sens.rows || [];
    if (sensRows.length) {
      y = pdfHeading(doc, y, "Empirical assumption sensitivity");
      pdfTable(doc, y, ["Parameter", "Scale", "Overflow rate", "Mean overflow h"], sensRows.map(r => [
        r.parameter,
        r.scale,
        r.overflow_event_rate?.toFixed(3) ?? "—",
        r.mean_overflow_duration?.toFixed(2) ?? "—",
      ]));
    }
    doc.save("phase3_report.pdf");
  }

  async function experimentPdf(report) {
    const JsPDF = requireJsPDF();
    const doc = new JsPDF();
    const d = report.data;
    const exp = d.experiment || {};
    let y = pdfMeta(doc, "experiment", report);

    y = pdfTable(doc, y, ["Field", "Value"], [
      ["Model", exp.model_label || exp.model || "—"],
      ["Seed", exp.seed ?? "—"],
      ["Trials per load", exp.trials_per_load ?? "—"],
      ["Patient range", `${exp.patient_range?.min ?? "—"}–${exp.patient_range?.max ?? "—"}`],
      ["n50", d.n50 ?? "not reached"],
      ["Data source", (d.provenance || {}).data_source || "—"],
    ]);

    const convImg = await plotlyImage("expConvPlot");
    y = addPdfImage(doc, y, convImg, "Running estimate at current n");

    const curveImg = await plotlyImage("expCurvePlot");
    y = addPdfImage(doc, y, curveImg, "Collapse-probability curve");

    const rows = d.results || [];
    if (rows.length) {
      y = pdfHeading(doc, y, "Results table");
      pdfTable(doc, y, ["n", "Trials", "K", "P(collapse)", "Wilson lo", "Wilson hi"], rows.map(r => [
        r.patient_count,
        r.trials,
        r.collapse_trials,
        r.collapse_probability?.toFixed(4),
        r.wilson_lower?.toFixed(4),
        r.wilson_upper?.toFixed(4),
      ]));
    }
    doc.save("mc_experiment_report.pdf");
  }

  const PDF_BUILDERS = {
    bankers: bankersPdf,
    mc: monteCarloPdf,
    sensitivity: sensitivityPdf,
    timemodel: timemodelPdf,
    phase3: phase3Pdf,
    experiment: experimentPdf,
  };

  async function downloadPdf(kind) {
    if (!reports[kind]) throw new Error("No results to export. Run the experiment first.");
    const builder = PDF_BUILDERS[kind];
    if (!builder) throw new Error(`Unknown report type: ${kind}`);
    await builder(reports[kind]);
  }

  async function download(kind, format) {
    if (format === "csv") {
      downloadCsv(kind);
      return;
    }
    if (format === "pdf") {
      await downloadPdf(kind);
      return;
    }
    throw new Error(`Unknown format: ${format}`);
  }

  function init() {
    document.querySelectorAll("[data-export-kind]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const kind = btn.getAttribute("data-export-kind");
        const format = btn.getAttribute("data-export-fmt");
        try {
          await download(kind, format);
        } catch (err) {
          const box = document.getElementById("errorBox");
          if (box) {
            box.textContent = err.message || String(err);
            box.classList.add("visible");
          } else {
            window.alert(err.message || String(err));
          }
        }
      });
    });
  }

  return { store, get, download, init };
})();

window.HSLabExport = HSLabExport;
