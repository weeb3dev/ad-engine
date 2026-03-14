/* Autonomous Ad Engine — client-side logic */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let genRadarChart = null;
let genVisualRadarChart = null;
let genTextRadarMmChart = null;
let libRadarChart = null;
let libVisualRadarChart = null;
let _libraryCache = [];
let _libIsMultimodal = false;
let _lastGenAdId = null;
let _libDetailAdId = null;

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

function isMultimodalMode() {
  const toggle = $("#gen-multimodal");
  return toggle && toggle.checked;
}

$("#gen-multimodal").addEventListener("change", () => {
  const picker = $("#gen-style-picker");
  if (!picker) return;
  picker.classList.toggle("hidden", !isMultimodalMode());
});

const _batchMmToggle = $("#batch-multimodal");
if (_batchMmToggle) {
  _batchMmToggle.addEventListener("change", () => {
    const picker = $("#batch-style-picker");
    if (picker) picker.classList.toggle("hidden", !_batchMmToggle.checked);
  });
}

function setGenStep(stepName) {
  const isMMod = isMultimodalMode();
  const imagesStep = $("#gen-step-images");

  if (isMMod && imagesStep) {
    imagesStep.classList.remove("hidden");
  }

  const order = isMMod
    ? ["generate", "evaluate", "improve", "images", "done"]
    : ["generate", "evaluate", "improve", "done"];
  const targetIdx = order.indexOf(stepName);

  const steps = $$("#gen-steps .step");
  steps.forEach((el) => {
    const step = el.dataset.step;
    if (!isMMod && step === "images") return;
    const stepIdx = order.indexOf(step);
    if (stepIdx >= 0 && stepIdx <= targetIdx) {
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
  const multimodal = isMultimodalMode();

  $("#gen-placeholder").classList.add("hidden");
  $("#gen-ad-card").classList.add("hidden");
  $("#gen-images-section").classList.add("hidden");
  $("#gen-error").classList.add("hidden");
  $("#gen-streaming").classList.remove("hidden");
  $("#gen-btn").disabled = true;
  const dlWrap = $("#gen-download-wrap");
  if (dlWrap) dlWrap.classList.add("hidden");
  _lastGenAdId = null;

  const imagesStep = $("#gen-step-images");
  if (multimodal && imagesStep) {
    imagesStep.classList.remove("hidden");
  } else if (imagesStep) {
    imagesStep.classList.add("hidden");
  }

  setGenStep("generate");
  $("#gen-status").textContent = "Starting pipeline...";

  const tbody = $("#gen-scores-body");
  tbody.innerHTML = "";
  const badge = $("#gen-score-badge");
  badge.textContent = "—";
  badge.className = "badge badge-lg font-mono";
  $("#gen-meta").textContent = "";
  $("#gen-variants-grid").innerHTML = "";

  let currentScores = {};

  const endpoint = multimodal ? "/api/generate-multimodal" : "/api/generate";

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        audience_segment: segment,
        campaign_goal: goal,
        tone: tone || null,
        specific_offer: offer || null,
        style_approaches: multimodal
          ? [document.querySelector('input[name="gen-style"]:checked')?.value || "hero_photo"]
          : undefined,
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

        case "image_generating":
          setGenStep("images");
          $("#gen-status").textContent = data.message;
          $("#gen-images-section").classList.remove("hidden");
          break;

        case "image_variant": {
          const grid = $("#gen-variants-grid");
          const card = document.createElement("div");
          card.className = "variant-card bg-base-200/50 rounded-lg p-3 fade-in";
          card.id = `gen-variant-${data.index}`;
          const vs = data.visual_evaluation.visual_aggregate_score;
          card.innerHTML = `
            <img src="${data.image_url}" alt="${data.style} variant" class="rounded-md mb-2" loading="lazy">
            <div class="flex items-center justify-between">
              <span class="badge badge-sm badge-outline">${data.style}</span>
              <span class="badge badge-sm font-mono ${scoreBadgeClass(vs)}">${vs.toFixed(2)}</span>
            </div>
          `;
          grid.appendChild(card);
          $("#gen-status").textContent = `Image variant ${data.index + 1}/${data.total} (${data.style}) scored ${vs.toFixed(2)}`;
          break;
        }

        case "image_variant_error":
          $("#gen-status").textContent = `Image variant ${data.style} failed: ${data.message}`;
          break;

        case "image_selected": {
          const winCard = $(`#gen-variant-${data.winning_index}`);
          if (winCard) winCard.classList.add("winner");
          $("#gen-status").textContent = `Winner: ${data.style} (visual score: ${data.visual_aggregate_score.toFixed(2)})`;
          break;
        }

        case "complete":
          setGenStep("done");
          $("#gen-streaming").classList.add("hidden");
          if (multimodal && data.record.winning_variant) {
            renderMultimodalResult(data.record);
          } else {
            renderGenerateResult(data.record);
          }
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
      layout: { padding: 20 },
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
  _lastGenAdId = record.ad_id;
  const dlWrap = $("#gen-download-wrap");
  if (dlWrap) dlWrap.classList.remove("hidden");

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

function renderMultimodalResult(record) {
  _lastGenAdId = record.ad_id;
  const dlWrap = $("#gen-download-wrap");
  if (dlWrap) dlWrap.classList.remove("hidden");

  const textRec = record.text_record;
  const ad = textRec.generated_ad;
  const ev = textRec.evaluation;

  const card = $("#gen-ad-card");
  card.classList.remove("hidden");

  $("#gen-primary-text").textContent = ad.primary_text;
  $("#gen-headline").textContent = ad.headline;
  $("#gen-description").textContent = ad.description;
  $("#gen-cta").textContent = ad.cta_button;

  const textScore = ev.aggregate_score;
  const badge = $("#gen-score-badge");
  badge.textContent = textScore.toFixed(2);
  badge.className = "badge badge-lg font-mono " + scoreBadgeClass(textScore);

  const cost = record.total_cost_usd.toFixed(4);
  let meta = `Cycle ${textRec.iteration_cycle}`;
  if (textRec.improvement_strategy) meta += ` · ${textRec.improvement_strategy}`;
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

  const imgSection = $("#gen-images-section");
  imgSection.classList.remove("hidden");

  const combined = record.combined_score;
  const combinedBadge = $("#gen-combined-badge");
  combinedBadge.textContent = combined.toFixed(2);
  combinedBadge.className = "badge badge-lg font-mono " + scoreBadgeClass(combined);
  $("#gen-combined-meta").textContent = `Combined (0.6 text + 0.4 visual) · $${cost}`;

  const winnerVis = record.winning_variant.visual_evaluation;
  renderVisualRadar(
    "gen-visual-radar",
    winnerVis,
    (c) => (genVisualRadarChart = c),
    genVisualRadarChart
  );

  renderRadar(
    "gen-text-radar-mm",
    ev,
    (c) => (genTextRadarMmChart = c),
    genTextRadarMmChart
  );
}

// ── Batch (streaming with progressive stats) ─────────────────────────────

function _getCheckedValues(name) {
  return [...$$(`input[name="${name}"]:checked`)].map((el) => el.value);
}

async function runBatch() {
  const num = parseInt($("#batch-num").value);
  const mmToggle = $("#batch-multimodal");
  const multimodal = mmToggle && mmToggle.checked;

  const segments = _getCheckedValues("batch-segment");
  const goals = _getCheckedValues("batch-goal");
  const tones = _getCheckedValues("batch-tone");
  const offers = _getCheckedValues("batch-offer");
  const styles = multimodal ? _getCheckedValues("batch-style") : undefined;

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
      body: JSON.stringify({
        num_ads: num,
        segments: segments.length ? segments : null,
        goals: goals.length ? goals : null,
        tones: tones.length ? tones : null,
        offers: offers.length ? offers : null,
        multimodal,
        style_approaches: styles && styles.length ? styles : undefined,
      }),
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
  const mmToggle = $("#lib-multimodal");
  _libIsMultimodal = mmToggle && mmToggle.checked;

  const endpoint = _libIsMultimodal ? "/api/multimodal-library" : "/api/library";
  const params = new URLSearchParams({ segment, min_score: minScore });
  const res = await fetch(endpoint + "?" + params);
  _libraryCache = await res.json();

  if (_libraryCache.length === 0) {
    $("#lib-placeholder").classList.remove("hidden");
    $("#lib-placeholder").innerHTML = "<p>No ads found. Generate an ad or run a batch first, or adjust filters.</p>";
    $("#lib-table-wrap").classList.add("hidden");
    $("#lib-detail").classList.add("hidden");
    const expWrap = $("#lib-export-wrap");
    if (expWrap) expWrap.classList.add("hidden");
    return;
  }

  $("#lib-placeholder").classList.add("hidden");
  $("#lib-table-wrap").classList.remove("hidden");
  $("#lib-count").textContent = _libraryCache.length + " ads";
  const expWrap = $("#lib-export-wrap");
  if (expWrap) expWrap.classList.remove("hidden");

  const thead = $("#lib-thead");
  if (_libIsMultimodal) {
    thead.innerHTML = `<tr>
      <th></th><th>ID</th><th>Segment</th><th>Goal</th>
      <th>Headline</th><th>Combined</th><th>Text</th><th>Visual</th>
    </tr>`;
  } else {
    thead.innerHTML = `<tr>
      <th>ID</th><th>Segment</th><th>Goal</th>
      <th>Headline</th><th>Score</th><th>Cycles</th>
    </tr>`;
  }

  const tbody = $("#lib-body");
  tbody.innerHTML = "";
  _libraryCache.forEach((r, idx) => {
    const tr = document.createElement("tr");
    tr.className = "cursor-pointer hover";
    tr.onclick = () => showLibDetail(idx);
    const segLabel = CONFIG.segment_labels[r.brief.audience_segment] || r.brief.audience_segment;

    if (_libIsMultimodal) {
      const imgPath = _mmImageUrl(r.winning_variant);
      const ad = r.text_record.generated_ad;
      const textScore = r.text_record.evaluation.aggregate_score;
      const visScore = r.winning_variant.visual_evaluation.visual_aggregate_score;
      tr.innerHTML = `
        <td><img src="${imgPath}" class="w-10 h-10 rounded object-cover" alt=""></td>
        <td class="font-mono text-xs">${r.ad_id.slice(0, 8)}</td>
        <td>${segLabel}</td>
        <td>${r.brief.campaign_goal}</td>
        <td class="max-w-xs truncate">${ad.headline}</td>
        <td><span class="badge badge-sm font-mono ${scoreBadgeClass(r.combined_score)}">${r.combined_score.toFixed(2)}</span></td>
        <td class="font-mono text-xs">${textScore.toFixed(2)}</td>
        <td class="font-mono text-xs">${visScore.toFixed(2)}</td>
      `;
    } else {
      tr.innerHTML = `
        <td class="font-mono text-xs">${r.ad_id.slice(0, 8)}</td>
        <td>${segLabel}</td>
        <td>${r.brief.campaign_goal}</td>
        <td class="max-w-xs truncate">${r.generated_ad.headline}</td>
        <td><span class="badge badge-sm font-mono ${scoreBadgeClass(r.evaluation.aggregate_score)}">${r.evaluation.aggregate_score.toFixed(2)}</span></td>
        <td>${r.iteration_cycle}</td>
      `;
    }
    tbody.appendChild(tr);
  });
}

function _mmImageUrl(variant) {
  if (!variant || !variant.image_path) return "";
  const name = variant.image_path.split("/").pop();
  return "/images/" + name;
}

function showLibDetail(idx) {
  const record = _libraryCache[idx];
  if (!record) return;

  _libDetailAdId = record.ad_id;

  const panel = $("#lib-detail");
  panel.classList.remove("hidden");

  if (_libIsMultimodal) {
    _showMultimodalDetail(record);
  } else {
    _showTextDetail(record);
  }

  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function _showTextDetail(record) {
  const ad = record.generated_ad;
  const ev = record.evaluation;

  $("#lib-detail-image-wrap").classList.add("hidden");
  $("#lib-visual-scores-wrap").classList.add("hidden");
  $("#lib-visual-radar-wrap").classList.add("hidden");
  $("#lib-all-variants").classList.add("hidden");

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
}

function _showMultimodalDetail(record) {
  const textRec = record.text_record;
  const ad = textRec.generated_ad;
  const ev = textRec.evaluation;
  const winner = record.winning_variant;
  const winVis = winner.visual_evaluation;

  const imgWrap = $("#lib-detail-image-wrap");
  imgWrap.classList.remove("hidden");
  $("#lib-detail-image").src = _mmImageUrl(winner);
  $("#lib-detail-image-meta").textContent =
    `Style: ${winner.style} · Visual: ${winVis.visual_aggregate_score.toFixed(2)} · Combined: ${record.combined_score.toFixed(2)}`;

  $("#lib-primary-text").textContent = ad.primary_text;
  $("#lib-headline").textContent = ad.headline;
  $("#lib-description").textContent = ad.description;
  $("#lib-cta").textContent = ad.cta_button;

  let meta = `Combined: <strong>${record.combined_score.toFixed(2)}</strong>`;
  meta += ` · Text: ${ev.aggregate_score.toFixed(2)} · Visual: ${winVis.visual_aggregate_score.toFixed(2)}`;
  meta += ` · $${record.total_cost_usd.toFixed(4)}`;
  meta += ` · ${record.pipeline_time_s.toFixed(1)}s`;
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

  const visWrap = $("#lib-visual-scores-wrap");
  visWrap.classList.remove("hidden");
  const visBody = $("#lib-visual-scores-body");
  visBody.innerHTML = "";
  CONFIG.visual_dimensions.forEach((d) => {
    const ds = winVis[d];
    if (!ds) return;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${CONFIG.visual_dimension_labels[d]}</td>
      <td class="font-mono">${ds.score}/10</td>
      <td><span class="badge badge-sm badge-ghost">${ds.confidence}</span></td>
      <td class="text-xs max-w-md">${ds.rationale}</td>
    `;
    visBody.appendChild(tr);
  });

  renderRadar("lib-radar", ev, (c) => (libRadarChart = c), libRadarChart);

  const visRadarWrap = $("#lib-visual-radar-wrap");
  visRadarWrap.classList.remove("hidden");
  renderVisualRadar(
    "lib-visual-radar",
    winVis,
    (c) => (libVisualRadarChart = c),
    libVisualRadarChart
  );

  const allVariants = $("#lib-all-variants");
  const varGrid = $("#lib-variants-grid");
  if (record.all_variants && record.all_variants.length > 1) {
    allVariants.classList.remove("hidden");
    varGrid.innerHTML = "";
    record.all_variants.forEach((v, i) => {
      const isWinner = v.variant_id === winner.variant_id;
      const vs = v.visual_evaluation.visual_aggregate_score;
      const div = document.createElement("div");
      div.className = `variant-card bg-base-200/50 p-2 ${isWinner ? "winner" : ""}`;
      div.innerHTML = `
        <img src="${_mmImageUrl(v)}" alt="${v.style}" class="rounded-md mb-1" loading="lazy">
        <div class="flex items-center justify-between text-xs">
          <span class="badge badge-xs badge-outline">${v.style}</span>
          <span class="font-mono ${isWinner ? "font-bold" : ""}">${vs.toFixed(2)}</span>
        </div>
      `;
      varGrid.appendChild(div);
    });
  } else {
    allVariants.classList.add("hidden");
  }
}

function hideLibDetail() {
  $("#lib-detail").classList.add("hidden");
}

// ── Radar chart (Chart.js) ───────────────────────────────────────────────

function renderRadar(canvasId, evaluation, setter, existing) {
  if (existing) existing.destroy();

  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const labels = CONFIG.dimensions.map((d) => CONFIG.dimension_labels[d]);
  const data = CONFIG.dimensions.map((d) => evaluation[d].score);

  const ctx = canvas.getContext("2d");
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
      layout: { padding: 20 },
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

function renderVisualRadar(canvasId, visualEvaluation, setter, existing) {
  if (existing) existing.destroy();

  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const dims = CONFIG.visual_dimensions;
  const labels = dims.map((d) => CONFIG.visual_dimension_labels[d]);
  const data = dims.map((d) => (visualEvaluation[d] ? visualEvaluation[d].score : 0));

  const ctx = canvas.getContext("2d");
  const chart = new Chart(ctx, {
    type: "radar",
    data: {
      labels,
      datasets: [
        {
          label: "Visual Score",
          data,
          fill: true,
          backgroundColor: "rgba(34, 197, 94, 0.15)",
          borderColor: "rgb(34, 197, 94)",
          pointBackgroundColor: "rgb(34, 197, 94)",
          pointRadius: 4,
          borderWidth: 2,
        },
      ],
    },
    options: {
      layout: { padding: 20 },
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

// ── Downloads ────────────────────────────────────────────────────────────

function _triggerDownload(url) {
  const a = document.createElement("a");
  a.href = url;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function downloadGenAd(fmt) {
  if (!_lastGenAdId) return;
  _triggerDownload(`/api/download/ad/${_lastGenAdId}?format=${fmt}`);
}

function downloadLibAd(fmt) {
  if (!_libDetailAdId) return;
  _triggerDownload(`/api/download/ad/${_libDetailAdId}?format=${fmt}`);
}

function downloadLibrary(fmt) {
  const segment = $("#lib-segment").value;
  const minScore = parseFloat($("#lib-min").value);
  const params = new URLSearchParams({
    multimodal: _libIsMultimodal,
    segment,
    min_score: minScore,
    format: fmt,
  });
  _triggerDownload(`/api/download/library?${params}`);
}

// ── Utilities ────────────────────────────────────────────────────────────

function scoreBadgeClass(score) {
  if (score >= 8) return "badge-success";
  if (score >= 7) return "badge-info";
  if (score >= 5) return "badge-warning";
  return "badge-error";
}
