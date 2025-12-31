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

// Format time in 12-hour format with uppercase AM/PM
function fmtTime12h(date) {
    return new Intl.DateTimeFormat('en-AU', {
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
        timeZone: 'Australia/Sydney'
    }).format(date).replace('am', 'AM').replace('pm', 'PM');
}

// Format day and time in 12-hour format
function fmtDayTime12h(date) {
    const day = new Intl.DateTimeFormat('en-AU', { 
        weekday: 'short',
        timeZone: 'Australia/Sydney'
    }).format(date);
    return `${day} ${fmtTime12h(date)}`;
}

// Format time range (Sydney timezone) - 12-hour format
function formatTimeRange(startStr, endStr) {
    if (!startStr || !endStr) return "--:-- to --:--";
    try {
        const start = new Date(startStr);
        const end = new Date(endStr);
        
        const startTime = fmtTime12h(start);
        const endTime = fmtTime12h(end);
        return `${startTime} to ${endTime}`;
    } catch (e) {
        return "--:-- to --:--";
    }
}

// Format "as of" timestamp (Sydney timezone) - 12-hour format
function formatAsOf(timestampStr) {
    if (!timestampStr) return "Waiting for data";
    try {
        const dt = new Date(timestampStr);
        return `As of ${fmtDayTime12h(dt)}`;
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
        const timeStr = fmtTime12h(now);
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

// Forecast constants
const FORECAST_HOURS = 3;
const OFFSETS_MIN = [0, 30, 60, 90, 120, 150, 180];

// Downsample forecast intervals to 7 points at 30-min increments
function downsampleForecast(intervals) {
    if (!intervals || intervals.length === 0) {
        return null;
    }
    
    const now = new Date();
    const points = [];
    
    // Parse intervals with start/end times
    const parsedIntervals = intervals.map(interval => {
        try {
            const start = new Date(interval.start);
            const end = new Date(interval.end);
            return {
                start,
                end,
                per_kwh: interval.per_kwh || 0,
                spikeStatus: interval.spikeStatus,
                descriptor: interval.descriptor,
                price_max: interval.price_max || interval.per_kwh || 0
            };
        } catch (e) {
            return null;
        }
    }).filter(i => i !== null);
    
    if (parsedIntervals.length === 0) {
        return null;
    }
    
    // For each offset, find the matching interval
    for (const offsetMin of OFFSETS_MIN) {
        const target = new Date(now.getTime() + offsetMin * 60000);
        
        // Find interval where start <= target < end
        let matched = parsedIntervals.find(interval => 
            interval.start <= target && target < interval.end
        );
        
        // If no exact match, find closest future interval
        if (!matched) {
            const futureIntervals = parsedIntervals.filter(i => i.start > target);
            if (futureIntervals.length > 0) {
                matched = futureIntervals.reduce((closest, current) => 
                    current.start < closest.start ? current : closest
                );
            }
        }
        
        if (matched) {
            points.push({
                minutes_from_now: offsetMin,
                per_kwh: matched.per_kwh,
                price_max: matched.price_max,
                is_spike: matched.spikeStatus === 'spike' || matched.per_kwh >= 300,
                descriptor: matched.descriptor
            });
        } else {
            points.push(null);
        }
    }
    
    return points;
}

// Generate forecast insight message
function generateForecastInsight(points) {
    if (!points || points.length === 0) {
        return null;
    }
    
    // Filter out null points
    const validPoints = points.filter(p => p !== null);
    if (validPoints.length < 2) {
        return null;
    }
    
    const firstPrice = validPoints[0].per_kwh;
    const lastPrice = validPoints[validPoints.length - 1].per_kwh;
    
    // Rule 1: Check for spikes after "Now"
    for (let i = 1; i < points.length; i++) {
        const point = points[i];
        if (point && point.is_spike) {
            const spikeOffset = OFFSETS_MIN[i];
            return {
                message: `Spike expected in ~${spikeOffset}m, consider running appliances before then`,
                style: 'spike'
            };
        }
    }
    
    // Rule 2: Prices rising (last > first * 1.3)
    if (lastPrice > firstPrice * 1.3) {
        return {
            message: 'Prices rising, consider using appliances now',
            style: 'rising'
        };
    }
    
    // Rule 3: Prices dropping (last < first * 0.7)
    if (lastPrice < firstPrice * 0.7) {
        return {
            message: 'Prices dropping, wait for better rates',
            style: 'dropping'
        };
    }
    
    // No insight
    return null;
}

// Render forecast bars
function renderForecast(intervals) {
    const container = document.getElementById('forecast-bars');
    const insightEl = document.getElementById('forecast-insight');
    
    if (!container) return;
    
    // Downsample to 7 points
    const points = downsampleForecast(intervals);
    
    if (!points || points.every(p => p === null)) {
        container.innerHTML = '<div class="forecast-empty">No forecast data available</div>';
        if (insightEl) {
            insightEl.hidden = true;
        }
        return;
    }
    
    // Find max price for scaling (use price_max if available, else per_kwh)
    const maxPrice = Math.max(
        ...points.filter(p => p !== null).map(p => p.price_max || p.per_kwh || 0),
        1
    );
    
    // Render points
    container.innerHTML = points.map((point, index) => {
        if (point === null) {
            return `
                <div class="forecast-point">
                    <div class="forecast-price">--</div>
                    <div class="forecast-bar-wrap">
                        <div class="forecast-bar" style="height: 0;"></div>
                    </div>
                    <div class="forecast-label">${index === 0 ? 'Now' : `+${OFFSETS_MIN[index]}m`}</div>
                </div>
            `;
        }
        
        const price = point.per_kwh || 0;
        const priceMax = point.price_max || price;
        const barHeight = Math.max((price / maxPrice) * 40, 4); // Min 4px height
        const rangeHeight = priceMax > price ? Math.max((priceMax / maxPrice) * 40, 4) : 0;
        const isSpike = point.is_spike;
        const priceLevel = getPriceLevel(price);
        
        // Format price label (0 dp if >= 100, else 1 dp)
        const priceLabel = price >= 100 ? price.toFixed(0) : price.toFixed(1);
        
        // Label: "Now" for first point, "+30m" etc for others
        const label = index === 0 ? 'Now' : `+${OFFSETS_MIN[index]}m`;
        
        return `
            <div class="forecast-point">
                <div class="forecast-price">${priceLabel}¢</div>
                <div class="forecast-bar-wrap">
                    ${rangeHeight > barHeight ? `<div class="forecast-range" style="height: ${rangeHeight}px; background-color: ${priceLevel.orbBg};"></div>` : ''}
                    <div class="forecast-bar ${isSpike ? 'spike' : ''}" 
                         style="height: ${barHeight}px; background-color: ${priceLevel.orbBg};">
                    </div>
                    ${index === 0 ? '<div class="forecast-now"></div>' : ''}
                </div>
                <div class="forecast-label">${label}</div>
            </div>
        `;
    }).join('');
    
    // Update insight
    const insight = generateForecastInsight(points);
    if (insightEl) {
        if (insight) {
            insightEl.textContent = insight.message;
            insightEl.className = `forecast-insight ${insight.style}`;
            insightEl.hidden = false;
        } else {
            insightEl.hidden = true;
        }
    }
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
        fetch('/api/forecast?hours=3').then(r => r.ok ? r.json() : null).catch(() => null)
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
