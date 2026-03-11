/* Autonomous Ad Engine — client-side logic */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let genRadarChart = null;
let libRadarChart = null;
let _libraryCache = [];

// ── SSE helpers ──────────────────────────────────────────────────────────

function parseSSEStream(reader, decoder, callback) {
  let buffer = "";
  return (async () => {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split("\n\n");
      buffer = parts.pop();

      for (const part of parts) {
        for (const line of part.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.slice(6));
            callback(data);
          } catch (e) {
            console.warn("SSE parse error:", e, line);
          }
        }
      }
    }
  })();
}

// ── Tab switching ────────────────────────────────────────────────────────

function switchTab(name) {
  $$(".tab-panel").forEach((p) => p.classList.remove("active"));
  $$("#tab-nav .tab").forEach((t) => t.classList.remove("tab-active"));
  const panel = $(`#tab-${name}`);
  if (panel) panel.classList.add("active");
  const btn = $(`#tab-nav [data-tab="${name}"]`);
  if (btn) btn.classList.add("tab-active");
}

$$("#tab-nav .tab").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// ── Generate (streaming) ─────────────────────────────────────────────────

function setGenStep(stepName) {
  const steps = $$("#gen-steps .step");
  let reached = false;
  const order = ["generate", "evaluate", "improve", "done"];
  const targetIdx = order.indexOf(stepName);

  steps.forEach((el, idx) => {
    if (idx <= targetIdx) {
      el.classList.add("step-primary");
    } else {
      el.classList.remove("step-primary");
    }
  });
}

async function generateAd() {
  const segment = $("#gen-segment").value;
  const goal = document.querySelector('input[name="gen-goal"]:checked').value;
  const tone = $("#gen-tone").value;
  const offer = $("#gen-offer").value;

  $("#gen-placeholder").classList.add("hidden");
  $("#gen-ad-card").classList.add("hidden");
  $("#gen-error").classList.add("hidden");
  $("#gen-streaming").classList.remove("hidden");
  $("#gen-btn").disabled = true;

  setGenStep("generate");
  $("#gen-status").textContent = "Starting pipeline...";

  const tbody = $("#gen-scores-body");
  tbody.innerHTML = "";
  const badge = $("#gen-score-badge");
  badge.textContent = "—";
  badge.className = "badge badge-lg font-mono";
  $("#gen-meta").textContent = "";

  let currentScores = {};

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        audience_segment: segment,
        campaign_goal: goal,
        tone: tone || null,
        specific_offer: offer || null,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || JSON.stringify(err));
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    await parseSSEStream(reader, decoder, (data) => {
      switch (data.type) {
        case "status":
          $("#gen-status").textContent = data.message;
          break;

        case "ad_copy":
          setGenStep("evaluate");
          $("#gen-status").textContent = "Ad generated — starting evaluation...";
          $("#gen-ad-card").classList.remove("hidden");
          $("#gen-primary-text").textContent = data.ad.primary_text;
          $("#gen-headline").textContent = data.ad.headline;
          $("#gen-description").textContent = data.ad.description;
          $("#gen-cta").textContent = data.ad.cta_button;
          if (data.cycle && data.cycle > 1) {
            setGenStep("improve");
            $("#gen-status").textContent = `Improved ad (cycle ${data.cycle}) — re-evaluating...`;
          }
          break;

        case "eval_start": {
          const msg = data.cycle
            ? `Re-evaluating ${data.label} (${data.index}/${data.total})...`
            : `Evaluating ${data.label} (${data.index}/${data.total})...`;
          $("#gen-status").textContent = msg;
          break;
        }

        case "eval_progress": {
          currentScores[data.dimension] = data.score;
          const tr = document.createElement("tr");
          tr.id = `gen-score-${data.dimension}`;
          tr.className = "fade-in";
          tr.innerHTML = `<td>${data.label}</td><td class="font-mono">${data.score.score}/10</td><td><span class="badge badge-sm badge-ghost">${data.score.confidence}</span></td>`;

          const existing = $(`#gen-score-${data.dimension}`);
          if (existing) {
            existing.replaceWith(tr);
          } else {
            tbody.appendChild(tr);
          }

          renderPartialRadar(currentScores);
          break;
        }

        case "improving":
          setGenStep("improve");
          $("#gen-status").textContent =
            `Improving — targeting ${data.weakest} (cycle ${data.cycle}, strategy: ${data.strategy})...`;
          currentScores = {};
          tbody.innerHTML = "";
          break;

        case "complete":
          setGenStep("done");
          $("#gen-streaming").classList.add("hidden");
          renderGenerateResult(data.record);
          break;

        case "error":
          $("#gen-streaming").classList.add("hidden");
          $("#gen-error").classList.remove("hidden");
          $("#gen-error-msg").textContent = data.message;
          break;
      }
    });
  } catch (err) {
    $("#gen-streaming").classList.add("hidden");
    $("#gen-error").classList.remove("hidden");
    $("#gen-error-msg").textContent = String(err.message || err);
  } finally {
    $("#gen-btn").disabled = false;
  }
}

function renderPartialRadar(scores) {
  const dims = CONFIG.dimensions;
  const labels = dims.map((d) => CONFIG.dimension_labels[d]);
  const data = dims.map((d) => (scores[d] ? scores[d].score : 0));

  if (genRadarChart) genRadarChart.destroy();

  const canvas = document.getElementById("gen-radar");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  genRadarChart = new Chart(ctx, {
    type: "radar",
    data: {
      labels,
      datasets: [
        {
          label: "Score",
          data,
          fill: true,
          backgroundColor: "rgba(75, 107, 251, 0.15)",
          borderColor: "rgb(75, 107, 251)",
          pointBackgroundColor: "rgb(75, 107, 251)",
          pointRadius: 4,
          borderWidth: 2,
        },
      ],
    },
    options: {
      scales: {
        r: {
          min: 0,
          max: 10,
          ticks: { stepSize: 2, backdropColor: "transparent", font: { size: 10 } },
          pointLabels: { font: { size: 11 } },
          grid: { color: "rgba(0,0,0,0.06)" },
          angleLines: { color: "rgba(0,0,0,0.06)" },
        },
      },
      plugins: { legend: { display: false } },
      responsive: false,
      animation: { duration: 300 },
    },
  });
}

function renderGenerateResult(record) {
  const card = $("#gen-ad-card");
  card.classList.remove("hidden");

  const ad = record.generated_ad;
  const ev = record.evaluation;

  $("#gen-primary-text").textContent = ad.primary_text;
  $("#gen-headline").textContent = ad.headline;
  $("#gen-description").textContent = ad.description;
  $("#gen-cta").textContent = ad.cta_button;

  const score = ev.aggregate_score;
  const badge = $("#gen-score-badge");
  badge.textContent = score.toFixed(2);
  badge.className = "badge badge-lg font-mono " + scoreBadgeClass(score);

  const cost = (record.generation_cost_usd + record.evaluation_cost_usd).toFixed(4);
  let meta = `Cycle ${record.iteration_cycle}`;
  if (record.improvement_strategy) meta += ` · ${record.improvement_strategy}`;
  meta += ` · $${cost}`;
  $("#gen-meta").textContent = meta;

  const tbody = $("#gen-scores-body");
  tbody.innerHTML = "";
  CONFIG.dimensions.forEach((d) => {
    const ds = ev[d];
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${CONFIG.dimension_labels[d]}</td><td class="font-mono">${ds.score}/10</td><td><span class="badge badge-sm badge-ghost">${ds.confidence}</span></td>`;
    tbody.appendChild(tr);
  });

  renderRadar("gen-radar", ev, (c) => (genRadarChart = c), genRadarChart);
}

// ── Batch (streaming with progressive stats) ─────────────────────────────

async function runBatch() {
  const num = parseInt($("#batch-num").value);
  $("#batch-btn").disabled = true;
  $("#batch-placeholder").classList.add("hidden");
  $("#batch-results").classList.add("hidden");
  const prog = $("#batch-progress");
  prog.classList.remove("hidden");
  const liveStats = $("#batch-live-stats");
  liveStats.classList.remove("hidden");

  $("#bl-total").textContent = "0";
  $("#bl-pass-rate").textContent = "—";
  $("#bl-avg-score").textContent = "—";
  $("#bl-cost").textContent = "—";

  try {
    const res = await fetch("/api/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ num_ads: num }),
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    await parseSSEStream(reader, decoder, (data) => {
      if (data.type === "progress") {
        const pct = Math.round((data.current / data.total) * 100);
        $("#batch-progress-bar").value = pct;
        $("#batch-progress-pct").textContent = pct + "%";
        $("#batch-progress-label").textContent =
          `Generating ${data.current + 1} of ${data.total} — ${data.label}`;
      }

      if (data.type === "ad_complete") {
        const s = data.summary;
        const pct = Math.round(((data.index + 1) / data.total) * 100);
        $("#batch-progress-bar").value = pct;
        $("#batch-progress-pct").textContent = pct + "%";

        $("#bl-total").textContent = s.total;
        $("#bl-pass-rate").textContent = s.pass_rate + "%";
        $("#bl-avg-score").textContent = s.avg_score.toFixed(2);
        $("#bl-cost").textContent = "$" + s.total_cost.toFixed(4);
      }

      if (data.type === "complete") {
        prog.classList.add("hidden");
        liveStats.classList.add("hidden");
        renderBatchResults(data.summary);
      }
    });
  } catch (err) {
    prog.classList.add("hidden");
    liveStats.classList.add("hidden");
    alert("Batch failed: " + err.message);
  } finally {
    $("#batch-btn").disabled = false;
  }
}

function renderBatchResults(s) {
  $("#batch-results").classList.remove("hidden");

  $("#bs-total").textContent = s.total;
  $("#bs-pass-rate").textContent = s.pass_rate + "%";
  $("#bs-avg-score").textContent = s.avg_score.toFixed(2);
  $("#bs-range").textContent = s.min_score.toFixed(2) + "–" + s.max_score.toFixed(2);
  $("#bs-cost").textContent = "$" + s.total_cost.toFixed(4);
  $("#bs-cost-per").textContent = "$" + s.cost_per_ad.toFixed(4);

  const segBody = $("#bs-seg-body");
  segBody.innerHTML = "";
  for (const [seg, data] of Object.entries(s.segments)) {
    const label = CONFIG.segment_labels[seg] || seg;
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${label}</td><td>${data.pass_rate}%</td><td>${data.count}</td>`;
    segBody.appendChild(tr);
  }

  const dimBody = $("#bs-dim-body");
  dimBody.innerHTML = "";
  for (const [dim, avg] of Object.entries(s.dimensions)) {
    const label = CONFIG.dimension_labels[dim] || dim;
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${label}</td><td class="font-mono">${avg}</td>`;
    dimBody.appendChild(tr);
  }

  if (s.errors && s.errors.length > 0) {
    $("#batch-errors").classList.remove("hidden");
    $("#batch-errors-msg").textContent = s.errors.join("; ");
  } else {
    $("#batch-errors").classList.add("hidden");
  }
}

// ── Library ──────────────────────────────────────────────────────────────

async function loadLibrary() {
  const segment = $("#lib-segment").value;
  const minScore = parseFloat($("#lib-min").value);

  const params = new URLSearchParams({ segment, min_score: minScore });
  const res = await fetch("/api/library?" + params);
  _libraryCache = await res.json();

  if (_libraryCache.length === 0) {
    $("#lib-placeholder").classList.remove("hidden");
    $("#lib-placeholder").innerHTML = "<p>No ads found. Run a batch first, or adjust filters.</p>";
    $("#lib-table-wrap").classList.add("hidden");
    $("#lib-detail").classList.add("hidden");
    return;
  }

  $("#lib-placeholder").classList.add("hidden");
  $("#lib-table-wrap").classList.remove("hidden");
  $("#lib-count").textContent = _libraryCache.length + " ads";

  const tbody = $("#lib-body");
  tbody.innerHTML = "";
  _libraryCache.forEach((r, idx) => {
    const tr = document.createElement("tr");
    tr.className = "cursor-pointer hover";
    tr.onclick = () => showLibDetail(idx);
    const segLabel = CONFIG.segment_labels[r.brief.audience_segment] || r.brief.audience_segment;
    tr.innerHTML = `
      <td class="font-mono text-xs">${r.ad_id.slice(0, 8)}</td>
      <td>${segLabel}</td>
      <td>${r.brief.campaign_goal}</td>
      <td class="max-w-xs truncate">${r.generated_ad.headline}</td>
      <td><span class="badge badge-sm font-mono ${scoreBadgeClass(r.evaluation.aggregate_score)}">${r.evaluation.aggregate_score.toFixed(2)}</span></td>
      <td>${r.iteration_cycle}</td>
    `;
    tbody.appendChild(tr);
  });
}

function showLibDetail(idx) {
  const record = _libraryCache[idx];
  if (!record) return;

  const panel = $("#lib-detail");
  panel.classList.remove("hidden");

  const ad = record.generated_ad;
  const ev = record.evaluation;

  $("#lib-primary-text").textContent = ad.primary_text;
  $("#lib-headline").textContent = ad.headline;
  $("#lib-description").textContent = ad.description;
  $("#lib-cta").textContent = ad.cta_button;

  const cost = (record.generation_cost_usd + record.evaluation_cost_usd).toFixed(4);
  let meta = `Score: <strong>${ev.aggregate_score.toFixed(2)}</strong> · Cycle ${record.iteration_cycle}`;
  if (record.improvement_strategy) meta += ` · ${record.improvement_strategy}`;
  meta += ` · $${cost}`;
  $("#lib-meta").innerHTML = meta;

  const tbody = $("#lib-scores-body");
  tbody.innerHTML = "";
  CONFIG.dimensions.forEach((d) => {
    const ds = ev[d];
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${CONFIG.dimension_labels[d]}</td>
      <td class="font-mono">${ds.score}/10</td>
      <td><span class="badge badge-sm badge-ghost">${ds.confidence}</span></td>
      <td class="text-xs max-w-md">${ds.rationale}</td>
    `;
    tbody.appendChild(tr);
  });

  renderRadar("lib-radar", ev, (c) => (libRadarChart = c), libRadarChart);
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function hideLibDetail() {
  $("#lib-detail").classList.add("hidden");
}

// ── Radar chart (Chart.js) ───────────────────────────────────────────────

function renderRadar(canvasId, evaluation, setter, existing) {
  if (existing) existing.destroy();

  const labels = CONFIG.dimensions.map((d) => CONFIG.dimension_labels[d]);
  const data = CONFIG.dimensions.map((d) => evaluation[d].score);

  const ctx = document.getElementById(canvasId).getContext("2d");
  const chart = new Chart(ctx, {
    type: "radar",
    data: {
      labels,
      datasets: [
        {
          label: "Score",
          data,
          fill: true,
          backgroundColor: "rgba(75, 107, 251, 0.15)",
          borderColor: "rgb(75, 107, 251)",
          pointBackgroundColor: "rgb(75, 107, 251)",
          pointRadius: 4,
          borderWidth: 2,
        },
      ],
    },
    options: {
      scales: {
        r: {
          min: 0,
          max: 10,
          ticks: { stepSize: 2, backdropColor: "transparent", font: { size: 10 } },
          pointLabels: { font: { size: 11 } },
          grid: { color: "rgba(0,0,0,0.06)" },
          angleLines: { color: "rgba(0,0,0,0.06)" },
        },
      },
      plugins: { legend: { display: false } },
      responsive: false,
    },
  });

  setter(chart);
}

// ── Utilities ────────────────────────────────────────────────────────────

function scoreBadgeClass(score) {
  if (score >= 8) return "badge-success";
  if (score >= 7) return "badge-info";
  if (score >= 5) return "badge-warning";
  return "badge-error";
}
