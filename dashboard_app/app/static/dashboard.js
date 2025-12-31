// Price color mapping function
function getPriceState(priceCentsPerKwh) {
    if (priceCentsPerKwh < 0) {
        // Super cheap (negative pricing)
        return {
            label: "SUPER CHEAP",
            circleFill: "#70F8A8",
            textColor: "#000000",
            animation: "none"
        };
    } else if (priceCentsPerKwh < 10) {
        // Cheap: interpolate from mint green
        const ratio = priceCentsPerKwh / 10;
        const r = Math.round(112 + (248 - 112) * ratio); // 70 -> F8
        const g = Math.round(248 + (224 - 248) * ratio); // F8 -> E0
        const b = Math.round(168 + (72 - 168) * ratio); // A8 -> 48
        return {
            label: "CHEAP",
            circleFill: `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`,
            textColor: "#000000",
            animation: "none"
        };
    } else if (priceCentsPerKwh < 25) {
        // Normal: interpolate from yellow
        const ratio = (priceCentsPerKwh - 10) / 15;
        const r = Math.round(248 + (232 - 248) * ratio); // F8 -> E8
        const g = Math.round(224 + (96 - 224) * ratio); // E0 -> 60
        const b = Math.round(72 + (88 - 72) * ratio); // 48 -> 58
        return {
            label: "NORMAL",
            circleFill: `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`,
            textColor: "#000000",
            animation: "none"
        };
    } else if (priceCentsPerKwh < 300) {
        // Expensive: interpolate from yellow-red to red
        const ratio = (priceCentsPerKwh - 25) / 275;
        const r = Math.round(232 + (232 - 122) * ratio); // E8 -> 7A
        const g = Math.round(96 + (17 - 96) * ratio); // 60 -> 11
        const b = Math.round(88 + (17 - 88) * ratio); // 58 -> 11
        return {
            label: "EXPENSIVE",
            circleFill: `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`,
            textColor: "#ffffff",
            animation: "none"
        };
    } else {
        // Spike: ramp from red to dark red
        const spikeRatio = Math.min((priceCentsPerKwh - 300) / 1700, 1.0); // 300c to 2000c
        const r = Math.round(122 + (60 - 122) * spikeRatio); // 7A -> 3C
        const g = Math.round(17 + (0 - 17) * spikeRatio); // 11 -> 00
        const b = Math.round(17 + (0 - 17) * spikeRatio); // 11 -> 00
        return {
            label: "SPIKE",
            circleFill: `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`,
            textColor: "#ffffff",
            animation: "pulse"
        };
    }
}

// Freshness badge logic
function getPriceFreshness(ageSeconds) {
    if (ageSeconds === null || ageSeconds === undefined) return { status: "Unknown", class: "" };
    if (ageSeconds <= 900) return { status: "Fresh", class: "fresh" };
    return { status: "Stale", class: "stale" };
}

function getUsageFreshness(ageSeconds) {
    if (ageSeconds === null || ageSeconds === undefined) return { status: "Unknown", class: "" };
    if (ageSeconds <= 1800) return { status: "Fresh", class: "fresh" };
    if (ageSeconds <= 14400) return { status: "Lagging", class: "stale" };
    return { status: "Very stale", class: "very-stale" };
}

// Format time range
function formatTimeRange(startStr, endStr) {
    if (!startStr || !endStr) return "Current interval";
    try {
        const start = new Date(startStr);
        const end = new Date(endStr);
        const startTime = start.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false });
        const endTime = end.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false });
        return `${startTime} to ${endTime}`;
    } catch (e) {
        return "Current interval";
    }
}

// Format "as of" timestamp
function formatAsOf(timestampStr) {
    if (!timestampStr) return "As of --";
    try {
        const dt = new Date(timestampStr);
        return `As of ${dt.toLocaleDateString('en-AU', { weekday: 'short' })} ${dt.toLocaleTimeString('en-AU', { hour: 'numeric', minute: '2-digit', hour12: true })}`;
    } catch (e) {
        return "As of --";
    }
}

// Format minutes ago
function formatMinutesAgo(ageSeconds) {
    if (ageSeconds === null || ageSeconds === undefined) return "";
    const minutes = Math.floor(ageSeconds / 60);
    if (minutes === 0) return "Updated just now";
    if (minutes === 1) return "Updated 1 min ago";
    return `Updated ${minutes} mins ago`;
}

// Update UI from API data
function updateUI() {
    Promise.all([
        fetch('/api/price').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/health').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/totals').then(r => r.ok ? r.json() : null).catch(() => null)
    ]).then(([priceData, healthData, totalsData]) => {
        const emptyState = document.getElementById('empty-state');
        const heroContainer = document.querySelector('.hero-container');
        
        // Check if we have any data
        if (!priceData || priceData.error) {
            emptyState.style.display = 'block';
            heroContainer.style.display = 'none';
            document.querySelector('.totals-section').style.display = 'none';
            return;
        }
        
        emptyState.style.display = 'none';
        heroContainer.style.display = 'flex';
        document.querySelector('.totals-section').style.display = 'block';
        
        // Update price circle
        const priceCents = priceData.per_kwh || 0;
        const priceState = getPriceState(priceCents);
        const heroCircle = document.getElementById('hero-circle');
        
        heroCircle.style.backgroundColor = priceState.circleFill;
        heroCircle.className = 'hero-circle';
        if (priceState.animation === 'pulse') {
            heroCircle.classList.add('spike');
        }
        
        const circleContent = heroCircle.querySelector('.circle-content');
        if (circleContent) {
            circleContent.style.color = priceState.textColor;
        }
        
        document.getElementById('price-value').textContent = priceCents.toFixed(1);
        document.getElementById('circle-title').textContent = priceData.is_stale ? 'LAST CACHED PRICE' : 'LIVE 5 MIN PRICE';
        document.getElementById('circle-time').textContent = formatTimeRange(priceData.interval_start, priceData.interval_end);
        
        // Calculate age from fetched_at or interval_start
        let priceAgeSeconds = null;
        if (healthData && healthData.price_age_seconds !== null && healthData.price_age_seconds !== undefined) {
            priceAgeSeconds = healthData.price_age_seconds;
        } else if (priceData.interval_start) {
            const intervalStart = new Date(priceData.interval_start);
            priceAgeSeconds = Math.floor((Date.now() - intervalStart.getTime()) / 1000);
        }
        document.getElementById('circle-updated').textContent = formatMinutesAgo(priceAgeSeconds);
        
        // Update status badges
        if (healthData) {
            const priceFreshness = getPriceFreshness(healthData.price_age_seconds);
            const priceBadge = document.getElementById('price-badge');
            priceBadge.className = `badge ${priceFreshness.class}`;
            document.getElementById('price-status').textContent = priceFreshness.status;
            
            const usageFreshness = getUsageFreshness(healthData.usage_age_seconds);
            const usageBadge = document.getElementById('usage-badge');
            usageBadge.className = `badge ${usageFreshness.class}`;
            document.getElementById('usage-status').textContent = usageFreshness.status;
            
            // Mode badge (if data_source available)
            if (healthData.data_source) {
                const modeBadge = document.getElementById('mode-badge');
                modeBadge.style.display = 'inline-flex';
                document.getElementById('mode-status').textContent = healthData.data_source === 'live' ? 'Online' : 'Cache-only';
            }
        }
        
        // Update totals
        if (totalsData) {
            if (totalsData.month_to_date_cost_aud !== null) {
                document.getElementById('month-total').textContent = `$${totalsData.month_to_date_cost_aud.toFixed(2)}`;
                document.getElementById('totals-asof').textContent = formatAsOf(totalsData.as_of_interval_end);
                
                const totalsSection = document.querySelector('.totals-section');
                if (totalsData.is_delayed) {
                    totalsSection.classList.add('delayed');
                    document.getElementById('delayed-badge').style.display = 'inline-block';
                } else {
                    totalsSection.classList.remove('delayed');
                    document.getElementById('delayed-badge').style.display = 'none';
                }
            } else {
                document.getElementById('month-total').textContent = '--';
                document.getElementById('totals-asof').textContent = totalsData.message || 'As of --';
            }
        }
    });
}

// Initial load and periodic updates
updateUI();
setInterval(updateUI, 45000); // Update every 45 seconds

