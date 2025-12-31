// Price level determination
function getPriceLevel(priceCents) {
    if (priceCents >= 300) {
        return {
            level: "critical",
            orbBg: "#991B1B",
            glowBg: "rgba(153, 27, 27, 0.50)",
            textColor: "#FEF2F2",
            ringColor: "#DC2626",
            showSpike: true
        };
    } else if (priceCents >= 25) {
        return {
            level: "high",
            orbBg: "#EF4444",
            glowBg: "rgba(239, 68, 68, 0.30)",
            textColor: "#7F1D1D",
            ringColor: "#F87171",
            showSpike: false
        };
    } else if (priceCents >= 10) {
        return {
            level: "moderate",
            orbBg: "#F59E0B",
            glowBg: "rgba(245, 158, 11, 0.30)",
            textColor: "#78350F",
            ringColor: "#FBBF24",
            showSpike: false
        };
    } else {
        return {
            level: "optimal",
            orbBg: "#10B981",
            glowBg: "rgba(16, 185, 129, 0.30)",
            textColor: "#064E3B",
            ringColor: "#34D399",
            showSpike: false
        };
    }
}

// Format time range (Sydney timezone)
function formatTimeRange(startStr, endStr) {
    if (!startStr || !endStr) return "--:-- to --:--";
    try {
        const start = new Date(startStr);
        const end = new Date(endStr);
        
        const startTime = start.toLocaleTimeString('en-AU', { 
            hour: '2-digit', 
            minute: '2-digit', 
            hour12: false,
            timeZone: 'Australia/Sydney'
        });
        const endTime = end.toLocaleTimeString('en-AU', { 
            hour: '2-digit', 
            minute: '2-digit', 
            hour12: false,
            timeZone: 'Australia/Sydney'
        });
        return `${startTime} to ${endTime}`;
    } catch (e) {
        return "--:-- to --:--";
    }
}

// Format "as of" timestamp (Sydney timezone)
function formatAsOf(timestampStr) {
    if (!timestampStr) return "Waiting for data";
    try {
        const dt = new Date(timestampStr);
        const dateStr = dt.toLocaleDateString('en-AU', { 
            weekday: 'short',
            timeZone: 'Australia/Sydney'
        });
        const timeStr = dt.toLocaleTimeString('en-AU', { 
            hour: 'numeric', 
            minute: '2-digit', 
            hour12: true,
            timeZone: 'Australia/Sydney'
        });
        return `As of ${dateStr} ${timeStr}`;
    } catch (e) {
        return "Waiting for data";
    }
}

// Format minutes ago
function formatMinutesAgo(ageSeconds) {
    if (ageSeconds === null || ageSeconds === undefined) return "Updated -- ago";
    const minutes = Math.floor(ageSeconds / 60);
    if (minutes === 0) return "Updated just now";
    if (minutes === 1) return "Updated 1 min ago";
    return `Updated ${minutes} mins ago`;
}

// Get price freshness status
function getPriceStatus(ageSeconds) {
    if (ageSeconds === null || ageSeconds === undefined) return { text: "Unknown", class: "" };
    if (ageSeconds <= 900) return { text: "Fresh", class: "fresh" };
    return { text: "Stale", class: "stale" };
}

// Get usage freshness status
function getUsageStatus(ageSeconds) {
    if (ageSeconds === null || ageSeconds === undefined) return { text: "Unknown", class: "" };
    if (ageSeconds <= 1800) return { text: "Fresh", class: "fresh" };
    if (ageSeconds <= 14400) return { text: "Lagging", class: "stale" };
    return { text: "Very stale", class: "very-stale" };
}

// Update clock
function updateClock() {
    const clockEl = document.getElementById('clock');
    if (clockEl) {
        const now = new Date();
        const timeStr = now.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: true });
        clockEl.textContent = timeStr;
    }
}

// Get footer message based on price level
function getFooterMessage(priceLevel, intervalLabel) {
    if (priceLevel === "critical") {
        return "Consider reducing energy usage during this spike period";
    } else if (priceLevel === "optimal") {
        return "Great time to use high-energy appliances";
    } else {
        return `Monitoring energy prices • ${intervalLabel || "Current interval"}`;
    }
}

// Render forecast bars
function renderForecast(intervals) {
    const container = document.getElementById('forecast-bars');
    if (!container) return;
    
    if (!intervals || intervals.length === 0) {
        container.innerHTML = '<div class="forecast-empty">No forecast data available</div>';
        return;
    }
    
    // Find max price for scaling
    const maxPrice = Math.max(...intervals.map(i => i.per_kwh || 0), 1);
    
    container.innerHTML = intervals.map(interval => {
        const price = interval.per_kwh || 0;
        const heightPercent = Math.min((price / maxPrice) * 100, 100);
        const isSpike = interval.spikeStatus === 'spike' || price >= 300;
        const priceLevel = getPriceLevel(price);
        
        // Format time (just hour:minute)
        let timeLabel = '--:--';
        try {
            const start = new Date(interval.start);
            timeLabel = start.toLocaleTimeString('en-AU', {
                hour: '2-digit',
                minute: '2-digit',
                hour12: false,
                timeZone: 'Australia/Sydney'
            });
        } catch (e) {
            // Keep default
        }
        
        return `
            <div class="forecast-bar-wrapper" title="${timeLabel} - ${price.toFixed(1)}¢/kWh">
                <div class="forecast-bar ${isSpike ? 'spike' : ''}" 
                     style="height: ${heightPercent}%; background-color: ${priceLevel.orbBg};"
                     data-price="${price.toFixed(1)}">
                </div>
                <div class="forecast-label">${timeLabel}</div>
            </div>
        `;
    }).join('');
}

// Update UI from API data
function updateUI() {
    Promise.all([
        fetch('/api/price').then(async r => {
            const data = r.ok ? await r.json() : null;
            const dataSource = r.headers.get('X-Data-Source');
            return { data, dataSource };
        }).catch(() => ({ data: null, dataSource: null })),
        fetch('/api/health').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/totals').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/forecast').then(r => r.ok ? r.json() : null).catch(() => null)
    ]).then(([priceResponse, healthData, totalsData, forecastData]) => {
        const priceData = priceResponse.data;
        const priceDataSource = priceResponse.dataSource;
        
        // Update mode pill based on /api/price X-Data-Source header
        const modePill = document.getElementById('mode-pill');
        const modeDot = document.getElementById('mode-dot');
        const modeText = document.getElementById('mode-text');
        
        if (priceDataSource === 'live') {
            modeDot.className = 'pill-dot live';
            modeText.textContent = 'LIVE';
        } else {
            modeDot.className = 'pill-dot cached';
            modeText.textContent = 'CACHED';
        }
        
        // Check if we have price data
        if (!priceData || priceData.error) {
            // Empty state
            document.getElementById('orb-label').textContent = 'NO DATA YET';
            document.getElementById('orb-interval').textContent = '--:-- to --:--';
            document.getElementById('price-value').textContent = '--';
            document.getElementById('orb-level').textContent = '--';
            document.getElementById('price-updated').textContent = 'Updated -- ago';
            document.getElementById('orb').style.opacity = '0.5';
            document.getElementById('renewables-value').textContent = '--';
            document.getElementById('renewables-bar').style.width = '0%';
            document.getElementById('mtd-value').textContent = '—';
            document.getElementById('mtd-asof').textContent = 'Waiting for data';
            return;
        }
        
        // Update orb
        const priceCents = priceData.per_kwh || 0;
        const priceLevel = getPriceLevel(priceCents);
        const orb = document.getElementById('orb');
        const orbGlow = document.getElementById('orb-glow');
        const orbRing = document.getElementById('orb-ring');
        const orbSpike = document.getElementById('orb-spike');
        
        orb.style.backgroundColor = priceLevel.orbBg;
        orb.style.color = priceLevel.textColor;
        orbGlow.style.backgroundColor = priceLevel.glowBg;
        orbRing.style.borderColor = priceLevel.ringColor;
        
        // Show/hide spike badge and animations
        if (priceLevel.showSpike) {
            orbSpike.hidden = false;
            orbGlow.classList.add('pulse');
            orbRing.classList.add('ping');
        } else {
            orbSpike.hidden = true;
            orbGlow.classList.remove('pulse');
            orbRing.classList.remove('ping');
        }
        
        // Update orb content
        document.getElementById('price-value').textContent = priceCents.toFixed(1);
        document.getElementById('orb-level').textContent = priceLevel.level;
        
        // Update label and interval
        const priceAgeSeconds = healthData?.price_age_seconds;
        const isStale = priceAgeSeconds !== null && priceAgeSeconds !== undefined && priceAgeSeconds > 900;
        
        if (isStale) {
            document.getElementById('orb-label').textContent = 'CACHED PRICE';
            orb.classList.add('stale');
        } else {
            document.getElementById('orb-label').textContent = 'CURRENT RATE';
            orb.classList.remove('stale');
        }
        
        const intervalLabel = formatTimeRange(priceData.interval_start, priceData.interval_end);
        document.getElementById('orb-interval').textContent = intervalLabel;
        document.getElementById('price-updated').textContent = formatMinutesAgo(priceAgeSeconds);
        
        // Update renewables card
        const renewables = priceData.renewables;
        if (renewables !== null && renewables !== undefined) {
            document.getElementById('renewables-value').textContent = renewables.toFixed(0);
            document.getElementById('renewables-bar').style.width = `${Math.min(renewables, 100)}%`;
        } else {
            document.getElementById('renewables-value').textContent = '--';
            document.getElementById('renewables-bar').style.width = '0%';
        }
        
        // Update totals card
        if (totalsData && totalsData.month_to_date_cost_aud !== null) {
            document.getElementById('mtd-value').textContent = totalsData.month_to_date_cost_aud.toFixed(2);
            document.getElementById('mtd-asof').textContent = formatAsOf(totalsData.as_of_interval_end);
            
            const delayedBadge = document.getElementById('totals-delayed');
            if (totalsData.is_delayed) {
                delayedBadge.hidden = false;
            } else {
                delayedBadge.hidden = true;
            }
        } else {
            document.getElementById('mtd-value').textContent = '—';
            document.getElementById('mtd-asof').textContent = totalsData?.message || 'Waiting for data';
            document.getElementById('totals-delayed').hidden = true;
        }
        
        // Update status pills
        if (healthData) {
            const priceStatus = getPriceStatus(healthData.price_age_seconds);
            const priceStatusEl = document.getElementById('price-status');
            priceStatusEl.textContent = priceStatus.text;
            priceStatusEl.className = `status-pill ${priceStatus.class}`;
            
            const usageStatus = getUsageStatus(healthData.usage_age_seconds);
            const usageStatusEl = document.getElementById('usage-status');
            usageStatusEl.textContent = usageStatus.text;
            usageStatusEl.className = `status-pill ${usageStatus.class}`;
        }
        
        // Update footer message
        const footerMessage = getFooterMessage(priceLevel.level, intervalLabel);
        document.getElementById('footer-message').textContent = footerMessage;
        
        // Update forecast
        if (forecastData && forecastData.intervals) {
            renderForecast(forecastData.intervals);
        } else {
            const container = document.getElementById('forecast-bars');
            if (container) {
                container.innerHTML = '<div class="forecast-empty">No forecast data available</div>';
            }
        }
    });
}

// Initialize clock and update every second
updateClock();
setInterval(updateClock, 1000);

// Initial load and periodic updates
updateUI();
setInterval(updateUI, 45000); // Update every 45 seconds
