(function sentinelFiControlRoom() {
  "use strict";

  var scriptTag = document.querySelector("script[data-api-base]");
  var config = {
    apiBase: scriptTag ? scriptTag.getAttribute("data-api-base") : "/v1",
    appName: scriptTag ? scriptTag.getAttribute("data-app-name") : "VittaAI",
  };
  const categories = ["business", "personal", "unknown"];
  const nodeOrder = ["ingest", "route", "ml", "slm", "llm", "gst", "cleanup"];
  const rupee = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });
  const number = new Intl.NumberFormat("en-IN");

  /* ─── State ─── */
  const state = {
    apiKey: window.sessionStorage.getItem("sentinelfi.apiKey") || "",
    latestAudit: null,
    latestTasks: [],
    latestDecisions: [],
    filteredDecisions: [],
    pipelineTick: 0,
    theme: window.localStorage.getItem("sentinelfi.theme") || "dark",
  };

  /* ─── Elements ─── */
  const el = {
    apiKeyInput:       byId("apiKeyInput"),
    saveApiKeyBtn:     byId("saveApiKeyBtn"),
    adminSettingsBtn:  byId("adminSettingsBtn"),
    adminSettingsPanel: byId("adminSettingsPanel"),
    adminSettingsJson: byId("adminSettingsJson"),
    adminSettingsRefreshBtn: byId("adminSettingsRefreshBtn"),
    adminSettingsSaveBtn: byId("adminSettingsSaveBtn"),
    adminSettingsResult: byId("adminSettingsResult"),
    darkModeToggle:    byId("darkModeToggle"),
    toast:             byId("toast"),
    uploadForm:        byId("uploadForm"),
    statementFile:     byId("statementFile"),
    uploadResult:      byId("uploadResult"),
    auditForm:         byId("auditForm"),
    sourceType:        byId("sourceType"),
    sourcePath:        byId("sourcePath"),
    sourceConfig:      byId("sourceConfig"),
    clientName:        byId("clientName"),
    reportPeriod:      byId("reportPeriod"),
    generatePdf:       byId("generatePdf"),
    generateMarkdown:  byId("generateMarkdown"),
    auditStatus:       byId("auditStatus"),
    auditProgress:     byId("auditProgress"),
    progressFill:      byId("progressFill"),
    pipeline:          byId("pipelineState"),
    runtimeStats:      byId("runtimeStats"),
    auditHistory:      byId("auditHistory"),
    summaryCards:       byId("summaryCards"),
    reportPaths:       byId("reportPaths"),
    exportBar:         byId("exportBar"),
    donutChart:        byId("donutChart"),
    donutCenter:       byId("donutCenter"),
    donutTotal:        byId("donutTotal"),
    donutLegend:       byId("donutLegend"),
    findingsBody:      byId("findingsBody"),
    gstBody:           byId("gstBody"),
    decisionCount:     byId("decisionCount"),
    decisionSearch:    byId("decisionSearch"),
    decisionFilter:    byId("decisionFilter"),
    decisionsBody:     byId("decisionsBody"),
    cleanupForm:       byId("cleanupForm"),
    cleanupTasks:      byId("cleanupTasks"),
    cleanupResult:     byId("cleanupResult"),
    feedbackForm:      byId("feedbackForm"),
    feedbackBody:      byId("feedbackBody"),
    feedbackResult:    byId("feedbackResult"),
    merchantForm:      byId("merchantForm"),
    merchantQuery:     byId("merchantQuery"),
    merchantResults:   byId("merchantResults"),
  };

  init();

  /* ═══════════ Initialisation ═══════════ */
  function init() {
    applyTheme(state.theme);
    el.apiKeyInput.value = state.apiKey;

    el.saveApiKeyBtn.addEventListener("click", onSaveApiKey);
    el.adminSettingsBtn.addEventListener("click", onToggleAdminSettings);
    el.adminSettingsRefreshBtn.addEventListener("click", onRefreshAdminSettings);
    el.adminSettingsSaveBtn.addEventListener("click", onSaveAdminSettings);
    el.darkModeToggle.addEventListener("click", onToggleTheme);
    el.uploadForm.addEventListener("submit", onUploadStatement);
    el.auditForm.addEventListener("submit", onLaunchAudit);
    el.cleanupForm.addEventListener("submit", onRunCleanup);
    el.feedbackForm.addEventListener("submit", onSubmitFeedback);
    el.merchantForm.addEventListener("submit", onMerchantSearch);
    el.auditHistory.addEventListener("click", onAuditHistoryClick);
    el.decisionSearch.addEventListener("input", onDecisionFilterChange);
    el.decisionFilter.addEventListener("change", onDecisionFilterChange);
    el.exportBar.addEventListener("click", onExportClick);

    resetPipeline("idle");
    renderEmptyStates();
    restoreLastAuditFromStorage();
    refreshRuntimeStats();
    refreshAuditHistory();
    window.setInterval(refreshRuntimeStats, 20000);
    window.setInterval(refreshAuditHistory, 30000);
  }

  function byId(id) {
    const element = document.getElementById(id);
    if (!element) throw new Error("Missing expected element: " + id);
    return element;
  }

  /* ═══════════ Theme Toggle ═══════════ */
  function applyTheme(theme) {
    state.theme = theme;
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem("sentinelfi.theme", theme);
  }

  function onToggleTheme() {
    applyTheme(state.theme === "dark" ? "light" : "dark");
  }

  /* ═══════════ API Key ═══════════ */
  function onSaveApiKey() {
    state.apiKey = el.apiKeyInput.value.trim();
    if (state.apiKey) {
      window.sessionStorage.setItem("sentinelfi.apiKey", state.apiKey);
      showToast("API key saved for this browser session.", false);
      if (!el.adminSettingsPanel.hidden) {
        onRefreshAdminSettings();
      }
    } else {
      window.sessionStorage.removeItem("sentinelfi.apiKey");
      showToast("API key cleared.", false);
      el.adminSettingsPanel.hidden = true;
    }
  }

  async function onToggleAdminSettings() {
    if (el.adminSettingsPanel.hidden) {
      el.adminSettingsPanel.hidden = false;
      await onRefreshAdminSettings();
      return;
    }
    el.adminSettingsPanel.hidden = true;
  }

  async function onRefreshAdminSettings() {
    setText(el.adminSettingsResult, "Loading admin settings...");
    try {
      const response = await apiFetch("/admin/settings");
      el.adminSettingsJson.value = JSON.stringify(response.settings || {}, null, 2);
      setText(el.adminSettingsResult, "Loaded admin settings.");
    } catch (error) {
      const msg = toErrorMessage(error);
      setText(el.adminSettingsResult, msg, true);
      if (msg.toLowerCase().includes("forbidden") || msg.toLowerCase().includes("unauthorized")) {
        el.adminSettingsPanel.hidden = true;
      }
      showToast(msg, true);
    }
  }

  async function onSaveAdminSettings() {
    var parsed;
    try {
      parsed = JSON.parse(el.adminSettingsJson.value || "{}");
    } catch (_error) {
      setText(el.adminSettingsResult, "Invalid JSON in admin settings editor.", true);
      return;
    }
    setText(el.adminSettingsResult, "Saving admin settings...");
    try {
      const response = await apiFetch("/admin/settings", {
        method: "PUT",
        body: JSON.stringify({ settings: parsed }),
      });
      el.adminSettingsJson.value = JSON.stringify(response.settings || {}, null, 2);
      setText(el.adminSettingsResult, "Admin settings saved.");
      showToast("Admin settings updated.", false);
    } catch (error) {
      const msg = toErrorMessage(error);
      setText(el.adminSettingsResult, msg, true);
      showToast(msg, true);
    }
  }

  /* ═══════════ Upload Statement ═══════════ */
  async function onUploadStatement(event) {
    event.preventDefault();
    const file = el.statementFile.files?.[0];
    if (!file) {
      setText(el.uploadResult, "Choose a CSV or PDF file to continue.", true);
      return;
    }

    disableBtn(el.uploadForm);
    setText(el.uploadResult, "Uploading statement...");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await apiFetch("/audit/upload", { method: "POST", body: formData });
      el.sourceType.value = response.type || "csv";
      el.sourcePath.value = response.path || "";
      setText(el.uploadResult,
        "Uploaded " + esc(response.original_filename) + " (" + number.format(response.size_bytes || 0) + " bytes).");
      showToast("Statement uploaded and source path autofilled.", false);
    } catch (error) {
      const msg = toErrorMessage(error);
      setText(el.uploadResult, msg, true);
      showToast(msg, true);
    } finally {
      enableBtn(el.uploadForm);
    }
  }

  /* ═══════════ Launch Audit ═══════════ */
  async function onLaunchAudit(event) {
    event.preventDefault();
    const parsedConfig = parseConfig(el.sourceConfig.value);
    if (parsedConfig.error) {
      setText(el.auditStatus, parsedConfig.error, true);
      return;
    }

    const payload = {
      source_type: el.sourceType.value,
      source_path: norm(el.sourcePath.value),
      source_config: parsedConfig.value,
      client_name: norm(el.clientName.value) || "Client",
      report_period: norm(el.reportPeriod.value) || "Last 90 days",
      generate_pdf: Boolean(el.generatePdf.checked),
      generate_markdown: Boolean(el.generateMarkdown.checked),
    };

    disableBtn(el.auditForm);
    setText(el.auditStatus, "Submitting audit job...");
    showProgress(true);
    resetPipeline("running");

    try {
      const submitResult = await apiFetch("/audit/submit", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await pollJob(submitResult.job_id);
    } catch (error) {
      const msg = toErrorMessage(error);
      setText(el.auditStatus, msg, true);
      showToast(msg, true);
      resetPipeline("failed");
    } finally {
      showProgress(false);
      enableBtn(el.auditForm);
    }
  }

  /* ═══════════ Poll Job ═══════════ */
  async function pollJob(jobId) {
    let attempts = 0;
    const maxAttempts = 120;

    while (attempts < maxAttempts) {
      attempts += 1;
      state.pipelineTick = (state.pipelineTick + 1) % nodeOrder.length;
      updatePipelineTick();

      // Approximate progress
      el.progressFill.style.width = Math.min(95, (attempts / maxAttempts) * 100).toFixed(0) + "%";

      try {
        const job = await apiFetch("/audit/jobs/" + jobId);
        setText(el.auditStatus,
          "Job " + jobId + ": " + job.status + (job.error ? " (" + job.error + ")" : ""),
          job.status === "failed");

        if (job.status === "succeeded" && job.result) {
          el.progressFill.style.width = "100%";
          resetPipeline("done");
          renderAuditResult(job.result);
          showToast("Audit " + (job.result.output?.summary?.audit_id || jobId) + " completed.", false);
          refreshAuditHistory();
          return;
        }

        if (job.status === "failed") {
          resetPipeline("failed");
          showToast("Audit job failed: " + (job.error || "Unknown error"), true);
          return;
        }
      } catch (error) {
        setText(el.auditStatus, toErrorMessage(error), true);
        showToast(toErrorMessage(error), true);
        return;
      }

      await sleep(1500);
    }

    resetPipeline("failed");
    setText(el.auditStatus, "Job polling timed out after 3 minutes.", true);
  }

  /* ═══════════ Audit History ═══════════ */
  async function refreshAuditHistory() {
    try {
      const audits = await apiFetch("/audits");
      if (!audits.length) {
        el.auditHistory.innerHTML = "<p class='muted'>No past audits found.</p>";
        return;
      }
      el.auditHistory.innerHTML = audits.slice(0, 10).map(function (a) {
        var dateStr = new Date(a.created_at).toLocaleDateString("en-IN", {
          day: "2-digit", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit"
        });
        return '<div class="audit-history-item" data-audit-id="' + esc(a.id) + '">' +
          '<div><span class="history-id">' + esc(a.id.slice(0, 8)) + '</span>' +
          '<span class="history-meta"> &middot; ' + esc(a.source_type) + ' &middot; ' +
          number.format(a.total_transactions) + ' txs</span></div>' +
          '<div><span class="history-meta">' + esc(dateStr) + '</span>' +
          (a.leak_count > 0 ? ' <span class="status-badge failed">' + a.leak_count + ' leaks</span>' :
            ' <span class="status-badge succeeded">clean</span>') + '</div></div>';
      }).join("");
      if (!state.latestAudit && audits.length) {
        loadAuditSnapshot(audits[0].id);
      }
    } catch (_error) {
      el.auditHistory.innerHTML = "<p class='muted'>Could not load history.</p>";
    }
  }

  async function onAuditHistoryClick(event) {
    var row = event.target.closest(".audit-history-item");
    if (!row) return;
    var auditId = row.getAttribute("data-audit-id");
    if (!auditId) return;
    await loadAuditSnapshot(auditId);
  }

  async function loadAuditSnapshot(auditId) {
    try {
      setText(el.auditStatus, "Loading snapshot for " + auditId + "...");
      var snapshot = await apiFetch("/audits/" + encodeURIComponent(auditId) + "/snapshot");
      renderAuditResult(snapshot);
      setText(el.auditStatus, "Loaded audit snapshot " + auditId + ".");
    } catch (error) {
      setText(el.auditStatus, toErrorMessage(error), true);
    }
  }

  /* ═══════════ Runtime Stats ═══════════ */
  async function refreshRuntimeStats() {
    try {
      const stats = await apiFetch("/runtime/stats");
      var cells = [
        statCell("Total Audits", number.format(stats.total_audits)),
        statCell("Avg Latency", number.format(Math.round(stats.avg_latency_ms)) + " ms"),
        statCell("Review Rate", (stats.avg_review_rate * 100).toFixed(1) + "%"),
        statCell("ML Samples", number.format(stats.ml_samples)),
        statCell("Drift Status", stats.ml_drift_status),
        statCell("Confidence PSI", stats.ml_confidence_psi.toFixed(3)),
      ];
      el.runtimeStats.innerHTML = cells.join("");
    } catch (error) {
      el.runtimeStats.innerHTML = '<div class="stat"><span class="label">Runtime</span>' +
        '<div class="value error">' + esc(toErrorMessage(error)) + '</div></div>';
    }
  }

  /* ═══════════ Render Audit Result ═══════════ */
  function renderAuditResult(result) {
    state.latestAudit = result;
    try {
      window.localStorage.setItem("sentinelfi.latestAuditResult", JSON.stringify(result));
    } catch (_error) {}
    state.latestTasks = result.output?.cleanup_tasks || [];
    state.latestDecisions = result.output?.classification_decisions || [];
    state.filteredDecisions = state.latestDecisions.slice();

    renderSummary(result.output?.summary, result.markdown_report_path, result.pdf_report_path);
    renderDonutChart(state.latestDecisions);
    renderFindings(result.output?.findings || []);
    renderGstFindings(result.output?.gst_findings || []);
    renderDecisionsTable(state.filteredDecisions);
    renderCleanupTasks(state.latestTasks);
    renderFeedbackTable(state.latestDecisions);

    // Show export bar
    el.exportBar.hidden = false;
  }

  function restoreLastAuditFromStorage() {
    try {
      var raw = window.localStorage.getItem("sentinelfi.latestAuditResult");
      if (!raw) return;
      var parsed = JSON.parse(raw);
      if (!parsed || !parsed.output || !parsed.output.summary) return;
      renderAuditResult(parsed);
      setText(el.auditStatus, "Restored latest audit from browser cache.");
    } catch (_error) {}
  }

  /* ─── Summary Cards ─── */
  function renderSummary(summary, markdownPath, pdfPath) {
    if (!summary) return;
    var cards = [
      summaryCard("Transactions", number.format(summary.total_transactions || 0), false),
      summaryCard("Leak Count", number.format(summary.leak_count || 0), (summary.leak_count || 0) > 0),
      summaryCard("Leak Impact", rupee.format(summary.total_leak_amount || 0), (summary.total_leak_amount || 0) > 0),
      summaryCard("Risk Score", number.format(summary.risk_score || 0), (summary.risk_score || 0) >= 70),
    ];
    // Missed ITC card
    if (summary.missed_itc !== undefined && summary.missed_itc !== null) {
      cards.push(summaryCard("Missed ITC", rupee.format(summary.missed_itc || 0), (summary.missed_itc || 0) > 0));
    }
    el.summaryCards.innerHTML = cards.join("");

    var paths = [];
    if (markdownPath) paths.push("MD: " + markdownPath);
    if (pdfPath) paths.push("PDF: " + pdfPath);
    el.reportPaths.textContent = paths.length ? paths.join(" | ") : "No reports generated.";
  }

  /* ─── Donut Chart ─── */
  function renderDonutChart(decisions) {
    if (!decisions.length) return;

    var counts = { business: 0, personal: 0, unknown: 0 };
    decisions.forEach(function (d) {
      var cat = (d.category || "unknown").toLowerCase();
      if (cat in counts) counts[cat] += 1;
      else counts.unknown += 1;
    });

    var total = decisions.length;
    el.donutTotal.textContent = number.format(total);

    var colors = {
      business: "var(--donut-biz)",
      personal: "var(--donut-personal)",
      unknown: "var(--donut-unknown)"
    };

    var segments = [];
    var cumulative = 0;
    var legendItems = [];

    Object.keys(counts).forEach(function (key) {
      var count = counts[key];
      if (count === 0) return;
      var pct = (count / total) * 100;
      var startDeg = (cumulative / total) * 360;
      var endDeg = ((cumulative + count) / total) * 360;
      segments.push(colors[key] + " " + startDeg.toFixed(1) + "deg " + endDeg.toFixed(1) + "deg");
      cumulative += count;

      legendItems.push(
        '<div class="legend-item">' +
        '<span class="legend-swatch" style="background:' + colors[key] + '"></span>' +
        '<span>' + capitalize(key) + '</span>' +
        '<span class="legend-count">' + number.format(count) + ' (' + pct.toFixed(1) + '%)</span>' +
        '</div>'
      );
    });

    if (segments.length) {
      el.donutChart.style.background = "conic-gradient(" + segments.join(", ") + ")";
    }
    el.donutLegend.innerHTML = legendItems.join("");
  }

  /* ─── Findings ─── */
  function renderFindings(findings) {
    if (!findings.length) {
      el.findingsBody.innerHTML = "<tr><td colspan='5' class='muted'>No leak findings.</td></tr>";
      return;
    }
    el.findingsBody.innerHTML = findings.map(function (f) {
      var sev = String(f.severity || "P3").toLowerCase();
      return "<tr>" +
        "<td>" + esc(f.leak_type || "-") + "</td>" +
        '<td><span class="severity ' + sev + '">' + esc(f.severity || "-") + "</span></td>" +
        "<td>" + rupee.format(f.amount_impact || 0) + "</td>" +
        "<td>" + ((f.confidence || 0) * 100).toFixed(1) + "%</td>" +
        "<td>" + esc(f.description || "-") + "</td>" +
        "</tr>";
    }).join("");
  }

  /* ─── GST Findings ─── */
  function renderGstFindings(items) {
    if (!items.length) {
      el.gstBody.innerHTML = "<tr><td colspan='3' class='muted'>No GST anomalies detected.</td></tr>";
      return;
    }
    el.gstBody.innerHTML = items.map(function (item) {
      return "<tr>" +
        '<td class="mono">' + esc(item.tx_id || "-") + "</td>" +
        "<td>" + esc(item.issue || "-") + "</td>" +
        "<td>" + rupee.format(item.potential_itc_amount || 0) + "</td>" +
        "</tr>";
    }).join("");
  }

  /* ─── Classification Decisions Table ─── */
  function renderDecisionsTable(decisions) {
    el.decisionCount.textContent = decisions.length;

    if (!decisions.length) {
      el.decisionsBody.innerHTML = "<tr><td colspan='6' class='muted'>Run an audit to see classification decisions.</td></tr>";
      return;
    }

    el.decisionsBody.innerHTML = decisions.slice(0, 200).map(function (d) {
      var conf = (d.confidence || 0);
      var confPct = (conf * 100).toFixed(1);
      var confClass = conf >= 0.8 ? "high" : conf >= 0.5 ? "medium" : "low";
      var catClass = (d.category || "unknown").toLowerCase();
      var review = d.requires_review;

      return "<tr>" +
        '<td class="mono" style="font-size:0.78rem">' + esc(d.tx_id || "-") + "</td>" +
        '<td><span class="category-badge ' + catClass + '">' + esc(d.category || "-") + "</span></td>" +
        "<td>" + esc(d.final_classifier || "-") + "</td>" +
        '<td class="confidence-bar-cell"><div class="confidence-bar">' +
        '<div class="confidence-track"><div class="confidence-fill ' + confClass + '" style="width:' + confPct + '%"></div></div>' +
        '<span class="confidence-text">' + confPct + '%</span></div></td>' +
        "<td>" + esc(d.route || d.classifier_route || "-") + "</td>" +
        '<td><span class="review-badge ' + (review ? "yes" : "no") + '">' +
        (review ? "Review" : "OK") + "</span></td>" +
        "</tr>";
    }).join("");
  }

  function onDecisionFilterChange() {
    var searchText = (el.decisionSearch.value || "").toLowerCase().trim();
    var filterVal = el.decisionFilter.value;

    state.filteredDecisions = state.latestDecisions.filter(function (d) {
      // Category filter
      if (filterVal === "review" && !d.requires_review) return false;
      if (filterVal === "business" && (d.category || "").toLowerCase() !== "business") return false;
      if (filterVal === "personal" && (d.category || "").toLowerCase() !== "personal") return false;

      // Text search
      if (searchText) {
        var haystack = [d.tx_id, d.category, d.final_classifier, d.route, d.classifier_route].join(" ").toLowerCase();
        if (haystack.indexOf(searchText) === -1) return false;
      }

      return true;
    });

    renderDecisionsTable(state.filteredDecisions);
  }

  /* ─── Cleanup Tasks ─── */
  function renderCleanupTasks(tasks) {
    if (!tasks.length) {
      el.cleanupTasks.innerHTML = "<p class='muted'>No cleanup tasks for this audit.</p>";
      return;
    }
    el.cleanupTasks.innerHTML = tasks.map(function (task, idx) {
      var checked = idx < 3 ? "checked" : "";
      var taskType = task.task_type || "unknown";
      var payload = JSON.stringify(task.payload || {});
      return '<label class="cleanup-item">' +
        '<div class="cleanup-head">' +
        '<span class="cleanup-title">' + esc(task.title || task.task_id) + '</span>' +
        '<input type="checkbox" value="' + esc(task.task_id) + '" ' + checked + ' />' +
        '</div>' +
        '<p class="cleanup-meta">' + esc(taskType) + ' | ' + esc(payload) + '</p>' +
        '</label>';
    }).join("");
  }

  /* ─── Feedback Table ─── */
  function renderFeedbackTable(decisions) {
    var reviewRows = decisions.filter(function (item) { return item.requires_review; }).slice(0, 40);
    if (!reviewRows.length) {
      el.feedbackBody.innerHTML = "<tr><td colspan='4' class='muted'>No review-required decisions in this audit.</td></tr>";
      return;
    }

    el.feedbackBody.innerHTML = reviewRows.map(function (d) {
      var options = '<option value="">No correction</option>' +
        categories.map(function (c) { return '<option value="' + c + '">' + c + '</option>'; }).join("");
      return '<tr data-tx-id="' + esc(d.tx_id) + '">' +
        '<td class="mono">' + esc(d.tx_id) + '</td>' +
        '<td>' + esc(d.category || "-") + ' (' + esc(d.final_classifier || "-") + ')</td>' +
        '<td>' + ((d.confidence || 0) * 100).toFixed(1) + '%</td>' +
        '<td><select>' + options + '</select></td>' +
        '</tr>';
    }).join("");
  }

  /* ═══════════ Cleanup Execution ═══════════ */
  async function onRunCleanup(event) {
    event.preventDefault();
    if (!state.latestAudit) {
      setText(el.cleanupResult, "Run an audit first to generate cleanup tasks.", true);
      return;
    }

    var selectedIds = Array.from(
      el.cleanupTasks.querySelectorAll("input[type='checkbox']:checked")
    ).map(function (cb) { return cb.value; });

    if (!selectedIds.length) {
      setText(el.cleanupResult, "Select at least one task.", true);
      return;
    }

    setText(el.cleanupResult, "Executing cleanup workflow...");
    try {
      var result = await apiFetch("/cleanup/run", {
        method: "POST",
        body: JSON.stringify({
          audit_id: state.latestAudit.output.summary.audit_id,
          approved_task_ids: selectedIds,
        }),
      });
      setText(el.cleanupResult,
        "Executed " + result.executed.length + " tasks, skipped " + result.skipped.length + ".", false);
      showToast("Cleanup run completed.", false);
    } catch (error) {
      var msg = toErrorMessage(error);
      setText(el.cleanupResult, msg, true);
      showToast(msg, true);
    }
  }

  /* ═══════════ Feedback Submission ═══════════ */
  async function onSubmitFeedback(event) {
    event.preventDefault();
    if (!state.latestAudit) {
      setText(el.feedbackResult, "Run an audit first to submit corrections.", true);
      return;
    }

    var corrections = [];
    el.feedbackBody.querySelectorAll("tr[data-tx-id]").forEach(function (row) {
      var txId = row.getAttribute("data-tx-id");
      var select = row.querySelector("select");
      var corrected = select ? select.value : "";
      if (txId && corrected) {
        corrections.push({ tx_id: txId, corrected_category: corrected });
      }
    });

    if (!corrections.length) {
      setText(el.feedbackResult, "Choose at least one corrected category.", true);
      return;
    }

    setText(el.feedbackResult, "Submitting feedback...");
    try {
      var result = await apiFetch("/ml/feedback", {
        method: "POST",
        body: JSON.stringify({
          audit_id: state.latestAudit.output.summary.audit_id,
          corrections: corrections,
          auto_retrain: true,
          source: "control_room",
        }),
      });
      setText(el.feedbackResult,
        "Accepted " + result.accepted_count + " corrections. Pending queue: " + result.pending_feedback_count + ".");
      showToast("Feedback submitted for active learning.", false);
    } catch (error) {
      var msg = toErrorMessage(error);
      setText(el.feedbackResult, msg, true);
      showToast(msg, true);
    }
  }

  /* ═══════════ Export ═══════════ */
  async function onExportClick(event) {
    var btn = event.target.closest("[data-export]");
    if (!btn || !state.latestAudit) return;

    var format = btn.getAttribute("data-export");
    var auditId = state.latestAudit.output?.summary?.audit_id;
    if (!auditId) {
      showToast("No audit ID available for export.", true);
      return;
    }

    btn.disabled = true;
    btn.textContent = "...";
    try {
      var response = await fetch(config.apiBase + "/export", {
        method: "POST",
        headers: buildHeaders(true),
        body: JSON.stringify({ audit_id: auditId, format: format, include_explanations: true }),
      });

      if (!response.ok) {
        var detail = response.status + " " + response.statusText;
        try {
          var errBody = await response.json();
          if (errBody.detail) detail = errBody.detail;
        } catch (_e) { /* ignore */ }
        throw new Error(detail);
      }

      var blob = await response.blob();
      var ext = format === "json" ? "json" : format === "quickbooks_iif" ? "iif" : "csv";
      var filename = "audit_" + auditId.slice(0, 8) + "." + ext;
      downloadBlob(blob, filename);
      showToast("Exported " + format + " file.", false);
    } catch (error) {
      showToast("Export failed: " + toErrorMessage(error), true);
    } finally {
      btn.disabled = false;
      var labels = { csv: "CSV", quickbooks_iif: "QuickBooks", xero_csv: "Xero", json: "JSON" };
      btn.textContent = labels[format] || format;
    }
  }

  /* ═══════════ Merchant Lookup ═══════════ */
  async function onMerchantSearch(event) {
    event.preventDefault();
    var query = (el.merchantQuery.value || "").trim();
    if (!query) {
      el.merchantResults.innerHTML = "<p class='muted'>Enter transaction text to search.</p>";
      return;
    }

    el.merchantResults.innerHTML = "<p class='muted'>Searching...</p>";
    try {
      var results = await apiFetch("/merchant/resolve", {
        method: "POST",
        body: JSON.stringify({ text: query, threshold: 0.5, top_k: 5 }),
      });

      if (!results.length) {
        el.merchantResults.innerHTML = "<p class='muted'>No merchants found matching &ldquo;" + esc(query) + "&rdquo;.</p>";
        return;
      }

      el.merchantResults.innerHTML = results.map(function (m) {
        return '<div class="merchant-card">' +
          '<div>' +
          '<div class="merchant-name">' + esc(m.canonical_name) + '</div>' +
          '<div class="merchant-category">' + esc(m.category) +
          (m.subcategory ? ' / ' + esc(m.subcategory) : '') + '</div>' +
          '</div>' +
          '<div style="text-align:right">' +
          '<div class="merchant-score">' + (m.similarity_score * 100).toFixed(0) + '%</div>' +
          '<div class="match-type">' + esc(m.match_type) + '</div>' +
          '</div>' +
          '</div>';
      }).join("");
    } catch (error) {
      el.merchantResults.innerHTML = "<p class='error'>" + esc(toErrorMessage(error)) + "</p>";
    }
  }

  /* ═══════════ Pipeline ═══════════ */
  function resetPipeline(mode) {
    var nodes = el.pipeline.querySelectorAll(".node");
    nodes.forEach(function (node) {
      node.classList.remove("pending", "running", "done", "failed");
      if (mode === "done") node.classList.add("done");
      else if (mode === "failed") node.classList.add("failed");
      else node.classList.add("pending");
    });
    if (mode === "running") updatePipelineTick();
  }

  function updatePipelineTick() {
    var nodes = el.pipeline.querySelectorAll(".node");
    var tick = state.pipelineTick;
    nodes.forEach(function (node, index) {
      node.classList.remove("pending", "running", "done");
      if (index < tick) node.classList.add("done");
      else if (index === tick) node.classList.add("running");
      else node.classList.add("pending");
    });
  }

  /* ═══════════ Progress Bar ═══════════ */
  function showProgress(show) {
    el.auditProgress.hidden = !show;
    if (show) {
      el.auditProgress.classList.add("indeterminate");
      el.progressFill.style.width = "0%";
    } else {
      el.auditProgress.classList.remove("indeterminate");
    }
  }

  /* ═══════════ Empty States ═══════════ */
  function renderEmptyStates() {
    el.summaryCards.innerHTML = [
      summaryCard("Transactions", "0", false),
      summaryCard("Leak Count", "0", false),
      summaryCard("Leak Impact", rupee.format(0), false),
      summaryCard("Risk Score", "0", false),
    ].join("");
    el.findingsBody.innerHTML = "<tr><td colspan='5' class='muted'>Run an audit to load findings.</td></tr>";
    el.gstBody.innerHTML = "<tr><td colspan='3' class='muted'>Run an audit to load GST checks.</td></tr>";
    el.decisionsBody.innerHTML = "<tr><td colspan='6' class='muted'>Run an audit to see classification decisions.</td></tr>";
    el.cleanupTasks.innerHTML = "<p class='muted'>Run an audit to generate cleanup tasks.</p>";
    el.feedbackBody.innerHTML = "<tr><td colspan='4' class='muted'>Run an audit to review classifications.</td></tr>";
    el.reportPaths.textContent = "No reports generated yet.";
    el.merchantResults.innerHTML = "<p class='muted'>Enter a transaction description to search merchants.</p>";
  }

  /* ═══════════ Helpers ═══════════ */
  function summaryCard(label, value, warning) {
    return '<div class="card ' + (warning ? "warn" : "") + '">' +
      '<span class="card-label">' + esc(label) + '</span>' +
      '<strong>' + esc(value) + '</strong></div>';
  }

  function statCell(label, value) {
    return '<div class="stat"><span class="label">' + esc(label) + '</span>' +
      '<div class="value">' + esc(value) + '</div></div>';
  }

  function buildHeaders(json) {
    var h = { accept: "application/json" };
    if (state.apiKey) h["x-api-key"] = state.apiKey;
    if (json) h["content-type"] = "application/json";
    return h;
  }

  async function apiFetch(path, options) {
    options = options || {};
    var requestInit = Object.assign({ method: "GET" }, options);
    var headers = new Headers(requestInit.headers || {});
    headers.set("accept", "application/json");
    if (state.apiKey) headers.set("x-api-key", state.apiKey);

    var hasJsonBody = typeof requestInit.body === "string" && !(requestInit.body instanceof FormData);
    if (hasJsonBody) headers.set("content-type", "application/json");
    requestInit.headers = headers;

    var response = await fetch(config.apiBase + path, requestInit);
    if (!response.ok) {
      var detail = response.status + " " + response.statusText;
      try {
        var payload = await response.json();
        if (payload && typeof payload.detail === "string") detail = payload.detail;
      } catch (_error) { /* ignore */ }
      throw new Error(detail);
    }
    return response.json();
  }

  function setText(element, text, isError) {
    element.textContent = text;
    element.classList.toggle("error", Boolean(isError));
    element.classList.toggle("success", !isError);
  }

  function showToast(message, isError) {
    setText(el.toast, message, isError);
  }

  function disableBtn(form) {
    var btn = form.querySelector("button[type='submit'], button.btn-primary");
    if (btn) btn.disabled = true;
  }

  function enableBtn(form) {
    var btn = form.querySelector("button[type='submit'], button.btn-primary");
    if (btn) btn.disabled = false;
  }

  function parseConfig(raw) {
    var text = norm(raw);
    if (!text) return { value: {} };
    try {
      var parsed = JSON.parse(text);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return { value: parsed };
      return { error: "Source config must be a JSON object." };
    } catch (_error) {
      return { error: "Invalid JSON in Source Config." };
    }
  }

  function norm(value) {
    if (typeof value !== "string") return null;
    var trimmed = value.trim();
    return trimmed || null;
  }

  function toErrorMessage(error) {
    return error instanceof Error ? error.message : "Unexpected error";
  }

  function sleep(ms) {
    return new Promise(function (resolve) { window.setTimeout(resolve, ms); });
  }

  function esc(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function capitalize(s) {
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function downloadBlob(blob, filename) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
})();
