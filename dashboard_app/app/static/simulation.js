const FLOW_BINDINGS = {
  solar_to_home: { path: "path-solar-home", label: "flow-label-solar-home", value: "flow-value-solar-home" },
  solar_to_battery: { path: "path-solar-battery", label: "flow-label-solar-battery", value: "flow-value-solar-battery" },
  solar_to_grid: { path: "path-solar-grid", label: "flow-label-solar-grid", value: "flow-value-solar-grid" },
  battery_to_home: { path: "path-battery-home", label: "flow-label-battery-home", value: "flow-value-battery-home" },
  battery_to_grid: { path: "path-battery-grid", label: "flow-label-battery-grid", value: "flow-value-battery-grid" },
  grid_to_home: { path: "path-grid-home", label: "flow-label-grid-home", value: "flow-value-grid-home" },
  grid_to_battery: { path: "path-grid-battery", label: "flow-label-grid-battery", value: "flow-value-grid-battery" }
};

function num(value) {
  const parsed = Number(value);
  if (Number.isFinite(parsed)) {
    return parsed;
  }
  return 0;
}

function fmtCurrency(value) {
  return `$${num(value).toFixed(2)}`;
}

function fmtSignedCurrency(value) {
  const v = num(value);
  if (v >= 0) {
    return `+$${v.toFixed(2)}`;
  }
  return `-$${Math.abs(v).toFixed(2)}`;
}

function fmtKwh(value) {
  return `${num(value).toFixed(1)} kWh`;
}

function fmtKw(value) {
  return `${num(value).toFixed(1)} kW`;
}

function fmtTime(dt) {
  return new Intl.DateTimeFormat("en-AU", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: "Australia/Sydney"
  }).format(dt).replace("am", "AM").replace("pm", "PM");
}

function fmtDayTime(dt) {
  const day = new Intl.DateTimeFormat("en-AU", {
    weekday: "short",
    timeZone: "Australia/Sydney"
  }).format(dt);
  return `${day} ${fmtTime(dt)}`;
}

function fmtAsOf(ts) {
  if (!ts) {
    return "As of --";
  }
  const dt = new Date(ts);
  if (Number.isNaN(dt.getTime())) {
    return "As of --";
  }
  return `As of ${fmtDayTime(dt)}`;
}

function fmtInterval(startTs, endTs) {
  if (!startTs || !endTs) {
    return "Interval --";
  }
  const start = new Date(startTs);
  const end = new Date(endTs);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return "Interval --";
  }
  return `${fmtTime(start)} to ${fmtTime(end)} (Australia/Sydney)`;
}

function updateClock() {
  const el = document.getElementById("sim-clock");
  if (!el) {
    return;
  }
  el.textContent = fmtTime(new Date());
}

function setChipState(el, status) {
  if (!el) {
    return;
  }
  el.classList.remove("chip-ok", "chip-warn", "chip-bad");
  if (status === "ok") {
    el.classList.add("chip-ok");
  } else if (status === "warn") {
    el.classList.add("chip-warn");
  } else if (status === "bad") {
    el.classList.add("chip-bad");
  }
}

function setStatePill(el, status, text) {
  if (!el) {
    return;
  }
  el.className = "state-pill";
  if (status) {
    el.classList.add(status);
  }
  el.textContent = text;
}

function applyFlowStyles(flowsKw) {
  const values = Object.keys(FLOW_BINDINGS).map((key) => num(flowsKw?.[key]));
  const maxKw = Math.max(0.05, ...values);

  Object.entries(FLOW_BINDINGS).forEach(([key, mapping]) => {
    const kw = num(flowsKw?.[key]);
    const active = kw >= 0.03;

    const path = document.getElementById(mapping.path);
    const label = document.getElementById(mapping.label);
    const value = document.getElementById(mapping.value);

    if (path) {
      const width = active ? 2.4 + (kw / maxKw) * 6.2 : 1.6;
      path.style.strokeWidth = width.toFixed(2);
      path.classList.toggle("active", active);
      path.classList.toggle("inactive", !active);
    }

    if (label) {
      label.classList.toggle("visible", active);
    }

    if (value) {
      value.textContent = fmtKw(kw);
    }
  });
}

function updateNodeValues(flow, status) {
  const flows = flow?.flows_kw || {};

  const solarKw = num(flows.solar_to_home) + num(flows.solar_to_battery) + num(flows.solar_to_grid);
  const batteryOutKw = num(flows.battery_to_home) + num(flows.battery_to_grid);
  const batteryInKw = num(flows.solar_to_battery) + num(flows.grid_to_battery);
  const homeKw = num(flows.solar_to_home) + num(flows.battery_to_home) + num(flows.grid_to_home);
  const gridImportKw = num(flows.grid_to_home) + num(flows.grid_to_battery);
  const gridExportKw = num(flows.solar_to_grid) + num(flows.battery_to_grid);

  const solarEl = document.getElementById("node-solar-value");
  const batteryEl = document.getElementById("node-battery-value");
  const homeEl = document.getElementById("node-home-value");
  const gridEl = document.getElementById("node-grid-value");

  if (solarEl) {
    solarEl.textContent = fmtKw(solarKw);
  }

  if (batteryEl) {
    const soc = num(status?.current_battery_soc_kwh);
    if (soc > 0) {
      const direction = batteryOutKw > batteryInKw ? "discharging" : (batteryInKw > batteryOutKw ? "charging" : "idle");
      batteryEl.textContent = `${soc.toFixed(1)} kWh ${direction}`;
    } else {
      batteryEl.textContent = fmtKw(batteryOutKw);
    }
  }

  if (homeEl) {
    homeEl.textContent = fmtKw(homeKw);
  }

  if (gridEl) {
    if (gridExportKw > gridImportKw + 0.01) {
      gridEl.textContent = `Export ${fmtKw(gridExportKw - gridImportKw)}`;
    } else if (gridImportKw > gridExportKw + 0.01) {
      gridEl.textContent = `Import ${fmtKw(gridImportKw - gridExportKw)}`;
    } else {
      gridEl.textContent = "Balanced";
    }
  }
}

function describeFlowCondition(flow) {
  const flows = flow?.flows_kw || {};
  const solarHome = num(flows.solar_to_home);
  const solarBattery = num(flows.solar_to_battery);
  const solarGrid = num(flows.solar_to_grid);
  const batteryHome = num(flows.battery_to_home);
  const gridHome = num(flows.grid_to_home);
  const gridBattery = num(flows.grid_to_battery);

  if (solarHome > 0.2 && solarBattery > 0.2) {
    return "Solar-dominant interval: home load served first, surplus charging battery, remainder exported.";
  }
  if (batteryHome > 0.2 && gridHome < 0.15) {
    return "Peak-support interval: battery discharging to offset expensive grid import.";
  }
  if (gridBattery > 0.2) {
    return "Arbitrage-prep interval: charging battery from lower-price grid energy.";
  }
  if (solarGrid > 0.1) {
    return "Export interval: PV surplus flowing to grid after home and battery needs.";
  }
  return "Balanced interval: controller is allocating supply across home, battery, and grid.";
}

function updateFlowBoard(flow, status) {
  applyFlowStyles(flow?.flows_kw || {});
  updateNodeValues(flow, status);

  const flowStateEl = document.getElementById("flow-state");
  const flowIntervalEl = document.getElementById("flow-interval");
  const flowNoteEl = document.getElementById("flow-note");
  const staleBanner = document.getElementById("sim-stale-banner");

  const stale = !!flow?.is_stale || !!status?.is_stale;
  const missing = flow?.status === "missing";

  if (flowStateEl) {
    if (missing) {
      setStatePill(flowStateEl, "missing", "No data");
    } else if (stale) {
      setStatePill(flowStateEl, "stale", "Stale");
    } else {
      setStatePill(flowStateEl, "ok", "Live cache");
    }
  }

  if (flowIntervalEl) {
    flowIntervalEl.textContent = fmtInterval(flow?.interval_start, flow?.interval_end);
  }

  if (flowNoteEl) {
    if (missing) {
      flowNoteEl.textContent = "No cached simulation interval was found yet. Run the simulation job to populate flow details.";
    } else {
      flowNoteEl.textContent = describeFlowCondition(flow);
    }
  }

  if (staleBanner) {
    staleBanner.hidden = !stale;
  }
}

function updateMoneyCards(flow) {
  const money = flow?.money_aud_per_hour || {};

  const importCost = num(money.import_cost);
  const exportRevenue = num(money.export_revenue);
  const avoidedCost = num(money.avoided_grid_cost);
  const degradationCost = num(money.degradation_cost);
  const netCost = num(money.net_cost);
  const savings = num(money.savings_vs_baseline);

  const setText = (id, value, signed = false) => {
    const el = document.getElementById(id);
    if (!el) {
      return;
    }
    el.textContent = signed ? fmtSignedCurrency(value) : fmtCurrency(value);
    el.style.color = "";
    if (signed) {
      if (value > 0) {
        el.style.color = "#98f0ca";
      } else if (value < 0) {
        el.style.color = "#ffc4c2";
      }
    }
  };

  setText("money-import", importCost);
  setText("money-export", exportRevenue);
  setText("money-avoided", avoidedCost);
  setText("money-degradation", degradationCost);
  setText("money-net", netCost);
  setText("money-savings", savings, true);
}

function downsample(rows, maxPoints) {
  if (!Array.isArray(rows) || rows.length <= maxPoints) {
    return rows || [];
  }
  const stride = Math.ceil(rows.length / maxPoints);
  const out = [];
  for (let idx = 0; idx < rows.length; idx += stride) {
    out.push(rows[idx]);
  }
  return out;
}

function buildPolyline(points) {
  if (points.length === 0) {
    return "";
  }
  return points.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ");
}

function renderCostChart(intervalPayload) {
  const container = document.getElementById("interval-chart");
  if (!container) {
    return;
  }

  const rows = downsample(intervalPayload?.intervals || [], 168);
  if (!rows.length) {
    container.innerHTML = '<div class="chart-empty">No interval data available</div>';
    return;
  }

  const width = Math.max(container.clientWidth || 300, 300);
  const height = Math.max(container.clientHeight || 150, 150);
  const pad = { left: 32, right: 10, top: 10, bottom: 22 };
  const innerWidth = width - pad.left - pad.right;
  const innerHeight = height - pad.top - pad.bottom;

  const baselineSeries = rows.map((r) => num(r.baseline_cost_aud));
  const scenarioSeries = rows.map((r) => num(r.scenario_cost_aud));
  const savingsSeries = rows.map((r) => num(r.savings_aud));

  const yMax = Math.max(0.02, ...baselineSeries, ...scenarioSeries);
  const savingsMax = Math.max(0.0001, ...savingsSeries.map((s) => Math.abs(s)));

  const baselinePoints = [];
  const scenarioPoints = [];
  const savingsBars = [];

  rows.forEach((row, idx) => {
    const x = pad.left + (idx / Math.max(rows.length - 1, 1)) * innerWidth;
    const yBaseline = pad.top + (1 - baselineSeries[idx] / yMax) * innerHeight;
    const yScenario = pad.top + (1 - scenarioSeries[idx] / yMax) * innerHeight;

    baselinePoints.push({ x, y: yBaseline });
    scenarioPoints.push({ x, y: yScenario });

    const sv = savingsSeries[idx];
    if (Math.abs(sv) > 0.000001) {
      const magnitude = Math.max(2, (Math.abs(sv) / savingsMax) * 11);
      savingsBars.push({
        x,
        y: height - pad.bottom + (sv >= 0 ? -magnitude : 0),
        h: magnitude,
        positive: sv >= 0
      });
    }
  });

  const gridLines = [0.25, 0.5, 0.75].map((ratio) => {
    const y = pad.top + innerHeight * ratio;
    return `<line x1="${pad.left}" y1="${y.toFixed(2)}" x2="${(width - pad.right).toFixed(2)}" y2="${y.toFixed(2)}" stroke="rgba(128,160,218,0.18)" stroke-width="1" />`;
  }).join("");

  const baselinePolyline = buildPolyline(baselinePoints);
  const scenarioPolyline = buildPolyline(scenarioPoints);

  const savingsRects = savingsBars.map((bar) => {
    const color = bar.positive ? "rgba(255,188,95,0.78)" : "rgba(255,110,103,0.7)";
    return `<rect x="${(bar.x - 1.1).toFixed(2)}" y="${bar.y.toFixed(2)}" width="2.2" height="${bar.h.toFixed(2)}" fill="${color}" rx="1.1" />`;
  }).join("");

  const firstTs = rows[0]?.interval_start ? fmtTime(new Date(rows[0].interval_start)) : "--";
  const midTs = rows[Math.floor(rows.length / 2)]?.interval_start ? fmtTime(new Date(rows[Math.floor(rows.length / 2)].interval_start)) : "--";
  const lastTs = rows[rows.length - 1]?.interval_start ? fmtTime(new Date(rows[rows.length - 1].interval_start)) : "--";

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
      <rect x="0" y="0" width="${width}" height="${height}" fill="rgba(9,18,33,0.9)"></rect>
      ${gridLines}
      <polyline fill="none" stroke="#8eb5ff" stroke-width="2.1" points="${baselinePolyline}" />
      <polyline fill="none" stroke="#47d9a0" stroke-width="2.1" points="${scenarioPolyline}" />
      ${savingsRects}
      <text x="${pad.left}" y="${(height - 6).toFixed(2)}" fill="rgba(159,182,223,0.84)" font-size="9">${firstTs}</text>
      <text x="${(width / 2).toFixed(2)}" y="${(height - 6).toFixed(2)}" text-anchor="middle" fill="rgba(159,182,223,0.84)" font-size="9">${midTs}</text>
      <text x="${(width - pad.right).toFixed(2)}" y="${(height - 6).toFixed(2)}" text-anchor="end" fill="rgba(159,182,223,0.84)" font-size="9">${lastTs}</text>
    </svg>
  `;
}

function updateKpis(status) {
  const stale = !!status?.is_stale;
  const missing = status?.status === "missing";

  document.getElementById("today-savings").textContent = fmtCurrency(status?.today_savings_aud);
  document.getElementById("mtd-savings").textContent = fmtCurrency(status?.month_to_date_savings_aud);
  document.getElementById("battery-soc").textContent = fmtKwh(status?.current_battery_soc_kwh);
  document.getElementById("solar-today").textContent = fmtKwh(status?.today_solar_generation_kwh);
  document.getElementById("export-revenue").textContent = fmtCurrency(status?.today_export_revenue_aud);
  document.getElementById("forecast-savings").textContent = fmtCurrency(status?.next_24h_projected_savings_aud);

  const controllerChip = document.getElementById("sim-controller");
  if (controllerChip) {
    controllerChip.textContent = (status?.controller_mode || "optimizer").toUpperCase();
  }

  const freshnessChip = document.getElementById("sim-freshness");
  if (freshnessChip) {
    if (missing) {
      freshnessChip.textContent = "MISSING";
      setChipState(freshnessChip, "bad");
    } else if (stale) {
      freshnessChip.textContent = "STALE";
      setChipState(freshnessChip, "warn");
    } else {
      freshnessChip.textContent = "FRESH";
      setChipState(freshnessChip, "ok");
    }
  }

  const asOfChip = document.getElementById("sim-asof-chip");
  if (asOfChip) {
    asOfChip.textContent = fmtAsOf(status?.as_of);
  }

  const statusPill = document.getElementById("sim-status");
  if (missing) {
    setStatePill(statusPill, "missing", "No run");
  } else if (stale) {
    setStatePill(statusPill, "stale", "Stale cache");
  } else {
    setStatePill(statusPill, "ok", "Healthy");
  }
}

function updateFooter(status, flow) {
  const footer = document.getElementById("sim-footer-message");
  if (!footer) {
    return;
  }

  if (status?.status === "missing") {
    footer.textContent = "No simulation run cached yet. Live dashboards stay online with baseline cache until simulation fills.";
    return;
  }

  const stale = !!status?.is_stale || !!flow?.is_stale;
  const age = num(status?.as_of_age_seconds);
  if (stale) {
    const minutes = Math.floor(age / 60);
    footer.textContent = `Simulation data is stale (${minutes}m old). Display remains cache-first and non-blocking.`;
    return;
  }

  const netCost = num(flow?.money_aud_per_hour?.net_cost);
  const savings = num(flow?.money_aud_per_hour?.savings_vs_baseline);
  footer.textContent = `Controller online: scenario net ${fmtCurrency(netCost)}/h, savings ${fmtSignedCurrency(savings)}/h relative to baseline.`;
}

async function fetchJson(url) {
  try {
    const response = await fetch(url);
    if (!response.ok) {
      return null;
    }
    return await response.json();
  } catch (error) {
    return null;
  }
}

async function refreshSimulation() {
  const [status, intervals, flow] = await Promise.all([
    fetchJson("/api/simulation/status"),
    fetchJson("/api/simulation/intervals?window=today&limit=1200"),
    fetchJson("/api/simulation/flow")
  ]);

  const statusData = status || {};
  const intervalData = intervals || { intervals: [] };
  const flowData = flow || {};

  updateKpis(statusData);
  updateFlowBoard(flowData, statusData);
  updateMoneyCards(flowData);
  renderCostChart(intervalData);

  const chartState = document.getElementById("chart-state");
  if (chartState) {
    if (statusData?.status === "missing") {
      setStatePill(chartState, "missing", "No data");
    } else if (statusData?.is_stale) {
      setStatePill(chartState, "stale", "Stale");
    } else {
      setStatePill(chartState, "ok", "Fresh");
    }
  }

  updateFooter(statusData, flowData);
}

updateClock();
setInterval(updateClock, 1000);

refreshSimulation();
setInterval(refreshSimulation, 45000);

window.addEventListener("resize", () => {
  fetchJson("/api/simulation/intervals?window=today&limit=1200").then((payload) => {
    renderCostChart(payload || { intervals: [] });
  });
});
