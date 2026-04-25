function num(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function money(value) {
  const v = num(value);
  return `$${Math.round(v).toLocaleString("en-AU")}`;
}

function one(value) {
  const v = Number(value);
  return Number.isFinite(v) ? v.toFixed(1) : "--";
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = value;
  }
}

function fetchJson(url) {
  return fetch(url).then((response) => response.ok ? response.json() : null).catch(() => null);
}

function renderRecommendation(payload) {
  const rec = payload?.recommendation;
  if (!rec) {
    setText("rec-title", "No cached annual analysis");
    setText("rec-copy", "Run scripts/run_annual_analysis.py to populate recommendations from your real interval data.");
    return;
  }

  setText("analysis-stamp", `Generated ${new Date(payload.generated_at).toLocaleString("en-AU", { timeZone: "Australia/Sydney" })}`);
  setText("rec-title", `${one(rec.solar_kw)} kW solar + ${one(rec.battery_kwh)} kWh battery`);
  setText(
    "rec-copy",
    `Conservative model: ${money(rec.installed_cost_after_rebates_aud)} installed after rebates, ${one(rec.grid_import_reduction_pct)}% grid import reduction, ${one(rec.self_supply_pct)}% self-supply.`
  );
  setText("kpi-saving", money(rec.year1_saving_aud));
  setText("kpi-payback", rec.payback_years == null ? "-- yrs" : `${one(rec.payback_years)} yrs`);
  setText("kpi-benefit", money(rec.lifetime_net_benefit_aud));
  setText("kpi-rate", rec.effective_rate_c_per_kwh == null ? "-- c/kWh" : `${one(rec.effective_rate_c_per_kwh)} c/kWh`);

  renderSensitivity(payload?.sensitivity || []);
  renderCashflow(rec.cashflow || []);
  renderMonthly(rec.monthly_energy_mix || []);
  renderBillImpact(rec);
}

function renderScenarios(payload) {
  const rows = (payload?.scenarios || [])
    .filter((row) => row.dispatch_mode === "base")
    .sort((a, b) => num(b.lifetime_net_benefit_aud) - num(a.lifetime_net_benefit_aud))
    .slice(0, 12);
  const tbody = document.getElementById("scenario-rows");
  if (!tbody) {
    return;
  }
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="6">No cached scenario rows</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map((row) => `
    <tr>
      <td>${one(row.solar_kw)} kW</td>
      <td>${one(row.battery_kwh)} kWh</td>
      <td>${money(row.year1_saving_aud)}</td>
      <td>${money(row.installed_cost_after_rebates_aud)}</td>
      <td>${row.payback_years == null ? "--" : one(row.payback_years)}</td>
      <td>${one(row.grid_import_reduction_pct)}%</td>
    </tr>
  `).join("");
}

function renderSensitivity(rows) {
  const el = document.getElementById("sensitivity-list");
  if (!el) {
    return;
  }
  if (!rows.length) {
    el.innerHTML = `<div class="list-row"><strong>No sensitivity data</strong><span>--</span></div>`;
    return;
  }
  el.innerHTML = rows.map((row) => `
    <div class="list-row">
      <div>
        <strong>${row.scenario}</strong>
        <span>${row.payback_years == null ? "Payback recalculation pending" : `${one(row.payback_years)} year payback`}</span>
      </div>
      <strong>${money(row.lifetime_benefit_aud)}</strong>
    </div>
  `).join("");
}

function renderCashflow(rows) {
  const el = document.getElementById("cashflow-chart");
  if (!el || !rows.length) {
    return;
  }
  const values = rows.map((row) => num(row.cumulative_cashflow_aud));
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 1);
  const width = 560;
  const height = 190;
  const pad = 18;
  const points = values.map((value, idx) => {
    const x = pad + (idx / Math.max(values.length - 1, 1)) * (width - pad * 2);
    const y = pad + (1 - ((value - min) / Math.max(max - min, 1))) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const zeroY = pad + (1 - ((0 - min) / Math.max(max - min, 1))) * (height - pad * 2);
  el.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img">
      <line x1="${pad}" y1="${zeroY}" x2="${width - pad}" y2="${zeroY}" stroke="#4a555b" stroke-width="1" />
      <polyline points="${points}" fill="none" stroke="#56d39c" stroke-width="3" />
      <text x="${pad}" y="16" fill="#9aa8ad" font-size="12">${money(max)}</text>
      <text x="${pad}" y="${height - 4}" fill="#9aa8ad" font-size="12">${money(min)}</text>
    </svg>
  `;
}

function renderMonthly(rows) {
  const el = document.getElementById("monthly-chart");
  if (!el) {
    return;
  }
  if (!rows.length) {
    el.innerHTML = `<div class="list-row"><strong>No monthly mix data</strong><span>--</span></div>`;
    return;
  }
  el.innerHTML = rows.map((row) => {
    const total = num(row.solar_direct_kwh) + num(row.battery_kwh) + num(row.grid_kwh);
    const solar = total ? (num(row.solar_direct_kwh) / total) * 100 : 0;
    const battery = total ? (num(row.battery_kwh) / total) * 100 : 0;
    const grid = Math.max(0, 100 - solar - battery);
    return `
      <div class="bar-month">
        <span>${row.month}</span>
        <div class="bar-stack">
          <i class="bar-seg solar" style="width:${solar}%"></i>
          <i class="bar-seg battery" style="width:${battery}%"></i>
          <i class="bar-seg grid" style="width:${grid}%"></i>
        </div>
        <span>${Math.round(total)} kWh</span>
      </div>
    `;
  }).join("");
}

function renderBillImpact(rec) {
  const el = document.getElementById("bill-impact");
  if (!el || !rec) {
    return;
  }
  const current = num(rec.baseline_cost_aud);
  const after = num(rec.scenario_cost_aud);
  const saving = num(rec.year1_saving_aud);
  el.innerHTML = `
    <div class="bill-card"><span>Current annual energy cost</span><strong>${money(current)}</strong></div>
    <div class="bill-card"><span>After modelled system</span><strong>${money(after)}</strong></div>
    <div class="bill-card"><span>Year 1 saving</span><strong class="${saving >= 0 ? "good" : "bad"}">${money(saving)}</strong></div>
    <div class="bill-card"><span>Export credit at conservative 2c/kWh</span><strong>${money(rec.export_revenue_aud)}</strong></div>
  `;
}

function renderLoadShift(payload) {
  const loadShift = payload?.load_shift || {};
  const opportunities = loadShift.opportunities || [];
  const el = document.getElementById("opportunity-list");
  if (!el) {
    return;
  }
  if (!opportunities.length) {
    el.innerHTML = `<div class="list-row"><strong>No opportunities cached</strong><span>--</span></div>`;
    return;
  }
  el.innerHTML = opportunities.map((item) => `
    <div class="list-row">
      <div>
        <strong>${item.title}</strong>
        <p>${item.evidence}</p>
        <span>Confidence: ${item.confidence}</span>
      </div>
      <strong>${item.estimated_annual_saving_aud == null ? "--" : money(item.estimated_annual_saving_aud)}</strong>
    </div>
  `).join("");
}

function renderQuality(payload) {
  const quality = payload?.data_quality || {};
  const checks = quality.checks || {};
  const chip = document.getElementById("quality-chip");
  if (chip) {
    chip.textContent = quality.ready ? "Ready" : "Needs data";
    chip.className = `panel-chip ${quality.ready ? "good" : "warn"}`;
  }
  const el = document.getElementById("quality-list");
  if (el) {
    el.innerHTML = Object.values(checks).map((check) => `
      <div class="quality-row">
        <span>${check.label}</span>
        <strong>${one(check.coverage_pct)}%</strong>
      </div>
    `).join("") || `<div class="quality-row"><span>No quality report</span><strong>--</strong></div>`;
  }
  setText("assumption-note", (quality.warnings || []).join(" "));
}

function refresh() {
  Promise.all([
    fetchJson("/api/analysis/recommendation?year=2025&goal=lowest_cost"),
    fetchJson("/api/analysis/scenarios?year=2025"),
    fetchJson("/api/analysis/load-shift?year=2025"),
    fetchJson("/api/analysis/data-quality?year=2025")
  ]).then(([recommendation, scenarios, loadShift, quality]) => {
    renderRecommendation(recommendation);
    renderScenarios(scenarios);
    renderLoadShift(loadShift);
    renderQuality(quality);
  });
}

refresh();
