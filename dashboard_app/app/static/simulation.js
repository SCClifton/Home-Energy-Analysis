function fmtCurrency(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "$0.00";
  }
  return `$${Number(value).toFixed(2)}`;
}

function fmtKwh(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "0.0 kWh";
  }
  return `${Number(value).toFixed(1)} kWh`;
}

function fmtClock(dt) {
  return new Intl.DateTimeFormat("en-AU", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: "Australia/Sydney"
  }).format(dt).replace("am", "AM").replace("pm", "PM");
}

function fmtAsOf(ts) {
  if (!ts) return "As of --";
  const dt = new Date(ts);
  return `As of ${fmtClock(dt)}`;
}

function updateClock() {
  const el = document.getElementById("sim-clock");
  if (el) {
    el.textContent = fmtClock(new Date());
  }
}

function downsample(intervals, targetCount) {
  if (intervals.length <= targetCount) return intervals;
  const stride = Math.ceil(intervals.length / targetCount);
  const out = [];
  for (let i = 0; i < intervals.length; i += stride) {
    out.push(intervals[i]);
  }
  return out;
}

function renderIntervalChart(intervals) {
  const container = document.getElementById("interval-chart");
  if (!container) return;

  if (!intervals || intervals.length === 0) {
    container.innerHTML = '<div class="interval-empty">No interval data available</div>';
    return;
  }

  const sample = downsample(intervals, 90);
  const maxAbs = Math.max(...sample.map((x) => Math.abs(Number(x.savings_aud || 0))), 0.01);

  container.innerHTML = sample.map((row) => {
    const value = Number(row.savings_aud || 0);
    const pct = Math.max((Math.abs(value) / maxAbs) * 100, 2);
    const cls = value >= 0 ? "positive" : "negative";
    return `
      <div class="interval-bar-wrap" title="${value.toFixed(3)} AUD">
        <div class="interval-bar ${cls}" style="height:${pct}%;"></div>
      </div>
    `;
  }).join("");
}

function updateSimulationUI(status, series) {
  const stale = !!status?.is_stale;
  const mode = document.getElementById("sim-mode");
  const footer = document.getElementById("sim-footer-message");
  const state = document.getElementById("chart-state");

  if (mode) {
    mode.textContent = stale ? "STALE CACHE" : `${(status?.controller_mode || "optimizer").toUpperCase()}`;
    mode.classList.toggle("stale", stale);
  }

  document.getElementById("today-savings").textContent = fmtCurrency(status?.today_savings_aud);
  document.getElementById("mtd-savings").textContent = fmtCurrency(status?.month_to_date_savings_aud);
  document.getElementById("battery-soc").textContent = fmtKwh(status?.current_battery_soc_kwh);
  document.getElementById("solar-today").textContent = fmtKwh(status?.today_solar_generation_kwh);
  document.getElementById("export-revenue").textContent = fmtCurrency(status?.today_export_revenue_aud);
  document.getElementById("forecast-savings").textContent = fmtCurrency(status?.next_24h_projected_savings_aud);
  document.getElementById("sim-asof").textContent = fmtAsOf(status?.as_of);

  const simStatus = document.getElementById("sim-status");
  if (simStatus) {
    const statusLabel = status?.status ? status.status.toUpperCase() : "UNKNOWN";
    simStatus.textContent = `Status: ${statusLabel}`;
  }

  if (footer) {
    if (stale) {
      const reason = status?.stale_reason ? ` (${status.stale_reason})` : "";
      footer.textContent = `Simulation data is stale${reason}. Values may lag real conditions.`;
    } else {
      footer.textContent = "Simulation updated from cached/local data pipeline.";
    }
  }

  if (state) {
    state.textContent = stale ? "Stale" : "Fresh";
  }

  renderIntervalChart(series?.intervals || []);
}

async function fetchJson(url) {
  try {
    const response = await fetch(url);
    if (!response.ok) return null;
    return await response.json();
  } catch (e) {
    return null;
  }
}

async function refreshSimulation() {
  const [status, intervals] = await Promise.all([
    fetchJson("/api/simulation/status"),
    fetchJson("/api/simulation/intervals?window=today&limit=1200")
  ]);

  updateSimulationUI(status || {}, intervals || { intervals: [] });
}

updateClock();
setInterval(updateClock, 1000);

refreshSimulation();
setInterval(refreshSimulation, 60000);
