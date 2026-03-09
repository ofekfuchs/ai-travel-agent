const promptEl = document.getElementById("prompt");
const runBtn = document.getElementById("run-btn");
const btnText = runBtn.querySelector(".btn-text");
const btnSpinner = runBtn.querySelector(".btn-spinner");
const loadingEl = document.getElementById("loading");
const errorSection = document.getElementById("error-section");
const errorMessage = document.getElementById("error-message");
const packagesSection = document.getElementById("packages-section");
const packagesContainer = document.getElementById("packages-container");
const textResponseSection = document.getElementById("text-response-section");
const textResponseContent = document.getElementById("text-response-content");
const stepsSection = document.getElementById("steps-section");
const stepsContainer = document.getElementById("steps-container");
const stepCount = document.getElementById("step-count");
const toggleStepsBtn = document.getElementById("toggle-steps");

// Suggestion chips
document.querySelectorAll(".chip").forEach(chip => {
  chip.addEventListener("click", () => {
    promptEl.value = chip.dataset.prompt;
    promptEl.focus();
  });
});

// Toggle steps visibility
toggleStepsBtn.addEventListener("click", () => {
  stepsContainer.classList.toggle("hidden");
  const isOpen = !stepsContainer.classList.contains("hidden");
  toggleStepsBtn.textContent = isOpen
    ? `Hide Execution Trace (${stepCount.textContent} steps)`
    : `Show Execution Trace (${stepCount.textContent} steps)`;
  // re-add the span for the count
  toggleStepsBtn.innerHTML = isOpen
    ? `Hide Execution Trace (<span id="step-count">${stepsContainer.children.length}</span> steps)`
    : `Show Execution Trace (<span id="step-count">${stepsContainer.children.length}</span> steps)`;
});

// Main handler
runBtn.addEventListener("click", async () => {
  const prompt = promptEl.value.trim();
  if (!prompt) return;

  setLoading(true);
  hideAll();

  try {
    const res = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });

    const data = await res.json();

    if (data.status === "error") {
      showError(data.error || "Unknown error");
    } else {
      renderResponse(data.response);
    }

    renderSteps(data.steps || []);

  } catch (err) {
    showError(`Network error: ${err.message}`);
  } finally {
    setLoading(false);
  }
});

function setLoading(on) {
  runBtn.disabled = on;
  loadingEl.classList.toggle("hidden", !on);
  btnText.textContent = on ? "Working..." : "Plan My Trip";
  btnSpinner.classList.toggle("hidden", !on);
}

function hideAll() {
  errorSection.classList.add("hidden");
  packagesSection.classList.add("hidden");
  textResponseSection.classList.add("hidden");
  stepsSection.classList.add("hidden");
  packagesContainer.innerHTML = "";
  stepsContainer.innerHTML = "";
}

function showError(msg) {
  errorMessage.textContent = msg;
  errorSection.classList.remove("hidden");
}

// ── Response rendering ──────────────────────────────────────────────────

function renderResponse(responseStr) {
  if (!responseStr) {
    textResponseContent.textContent = "No response received.";
    textResponseSection.classList.remove("hidden");
    return;
  }

  let packages = null;
  let warning = null;
  try {
    const parsed = JSON.parse(responseStr);
    if (Array.isArray(parsed)) {
      packages = parsed;
    } else if (parsed.packages && Array.isArray(parsed.packages)) {
      packages = parsed.packages;
      if (parsed.status === "best_effort") {
        const issues = parsed.verifier_issues || [];
        const question = parsed.question || "";
        warning = { issues, question, category: parsed.repair_category || "" };
      }
    }
  } catch {
    // Not JSON -- show as text
  }

  if (packages && packages.length > 0 && packages[0].destination) {
    renderPackages(packages, warning);
  } else {
    textResponseContent.textContent = responseStr;
    textResponseSection.classList.remove("hidden");
  }
}

function renderPackages(packages, warning) {
  packagesContainer.innerHTML = "";

  if (warning) {
    const banner = document.createElement("div");
    banner.className = "warning-banner";
    let bannerHTML = `<div class="warning-icon">&#9888;</div>
      <div class="warning-body">
        <strong>Best-effort results</strong> — the quality checker flagged some issues:`;
    if (warning.issues && warning.issues.length) {
      bannerHTML += `<ul class="warning-issues">`;
      warning.issues.forEach(i => { bannerHTML += `<li>${esc(i)}</li>`; });
      bannerHTML += `</ul>`;
    }
    if (warning.question) {
      bannerHTML += `<p class="warning-question">${esc(warning.question)}</p>`;
    }
    bannerHTML += `</div>`;
    banner.innerHTML = bannerHTML;
    packagesContainer.appendChild(banner);
  }

  packages.forEach(pkg => {
    const card = document.createElement("div");
    card.className = "package-card";
    try {
      card.innerHTML = buildPackageHTML(pkg);
    } catch (e) {
      card.innerHTML = `<div class="package-header"><div><span class="package-label">${esc(pkg.label || pkg.destination || "Package")}</span></div></div>
        <div class="package-body"><pre>${esc(JSON.stringify(pkg, null, 2))}</pre></div>`;
    }
    packagesContainer.appendChild(card);
  });

  packagesSection.classList.remove("hidden");
}

function formatDateWindow(dw) {
  if (!dw) return "";
  if (typeof dw === "string") return dw;
  if (typeof dw === "object") {
    const start = dw.start || dw.start_date || dw.from || "";
    const end = dw.end || dw.end_date || dw.to || "";
    if (start && end) return `${start} to ${end}`;
    return start || end || JSON.stringify(dw);
  }
  return String(dw);
}

function buildPackageHTML(pkg) {
  const label = pkg.label || "Trip Package";
  const dest = pkg.destination || "Unknown";
  const dates = formatDateWindow(pkg.date_window);
  const total = getTotal(pkg);

  let html = `
    <div class="package-header">
      <div>
        <span class="package-label">${esc(label)}</span>
        <div class="package-dest">${esc(dest)}</div>
        <div class="package-dates">${esc(dates)}</div>
      </div>
      <div class="package-total">${total}</div>
    </div>
    <div class="package-body">
  `;

  // Detail grid: flights, hotel, weather, pois
  html += `<div class="detail-grid">`;
  html += buildFlightBox(pkg);
  html += buildHotelBox(pkg);
  html += buildWeatherBox(pkg);
  html += buildDataBox(pkg);
  html += `</div>`;

  // Itinerary
  if (pkg.itinerary && pkg.itinerary.length > 0) {
    html += buildItinerary(pkg.itinerary);
  }

  // Cost breakdown
  html += buildCostBreakdown(pkg);

  // Rationale
  if (pkg.rationale) {
    html += `<div class="rationale"><strong>Why this package:</strong> ${esc(pkg.rationale)}</div>`;
  }

  // Booking links -- try package-level first, then individual item URLs
  const links = pkg.booking_links || {};
  const flightLink = links.flights_search
    || (pkg.flights && pkg.flights.outbound && pkg.flights.outbound.booking_url)
    || "";
  const hotelLink = links.hotels_search
    || (pkg.hotel && pkg.hotel.booking_url)
    || "";
  if (flightLink || hotelLink) {
    html += `<div class="booking-links">`;
    if (flightLink) {
      html += `<a href="${esc(flightLink)}" target="_blank" rel="noopener" class="booking-btn flights-btn">Search Flights</a>`;
    }
    if (hotelLink) {
      html += `<a href="${esc(hotelLink)}" target="_blank" rel="noopener" class="booking-btn hotels-btn">Search Hotels</a>`;
    }
    html += `</div>`;
  }

  // Assumptions
  const assumptions = toArray(pkg.assumptions);
  if (assumptions.length > 0) {
    html += `<details class="assumptions"><summary>Notes & Assumptions (${assumptions.length})</summary><ul>`;
    assumptions.forEach(a => { html += `<li>${esc(a)}</li>`; });
    html += `</ul></details>`;
  }

  html += `</div>`;
  return html;
}

function buildFlightBox(pkg) {
  const f = pkg.flights || {};
  const out = f.outbound || {};
  const ret = f.return || f.return_flight || {};
  const totalCost = f.total_flight_cost || f.total_cost || 0;

  if (!out.origin && !out.routing && !totalCost) {
    return `<div class="detail-box"><h4>Flights</h4>
      <div class="detail-main">No flight data</div></div>`;
  }

  let html = `<div class="detail-box"><h4>Flights</h4>`;

  if (out.origin || out.routing) {
    const outRoute = out.routing || `${out.origin || "?"} → ${out.destination || "?"}`;
    let outSub = out.airline ? `${out.airline}` : "";
    if (out.departure) outSub += outSub ? ` · ${formatDateTime(out.departure)}` : formatDateTime(out.departure);
    if (out.stops !== undefined) outSub += ` · ${out.stops === 0 ? "Direct" : out.stops + " stop(s)"}`;
    html += `<div class="flight-leg">
      <div class="flight-leg-label">Outbound</div>
      <div class="detail-main">${esc(outRoute)}</div>
      <div class="detail-sub">${esc(outSub)}</div>
    </div>`;
  }

  if (ret.origin || ret.routing || ret.departure) {
    const retRoute = ret.routing || `${ret.origin || "?"} → ${ret.destination || "?"}`;
    let retSub = ret.airline ? `${ret.airline}` : "";
    if (ret.departure) retSub += retSub ? ` · ${formatDateTime(ret.departure)}` : formatDateTime(ret.departure);
    if (ret.stops !== undefined) retSub += ` · ${ret.stops === 0 ? "Direct" : ret.stops + " stop(s)"}`;
    html += `<div class="flight-leg">
      <div class="flight-leg-label">Return</div>
      <div class="detail-main">${esc(retRoute)}</div>
      <div class="detail-sub">${esc(retSub)}</div>
    </div>`;
  }

  if (totalCost) {
    html += `<div class="detail-sub" style="margin-top:0.5rem;font-weight:600">$${Math.round(totalCost)} roundtrip</div>`;
  }
  html += `</div>`;
  return html;
}

function buildHotelBox(pkg) {
  const h = pkg.hotel || {};
  const name = h.name || "No hotel data";
  const perNight = h.per_night || h.per_night_usd || h.price_per_night || 0;
  const totalCost = h.total_cost || h.total_cost_usd || h.total_price || 0;
  const nights = h.nights || "";
  const address = h.address || "";
  const checkIn = h.check_in || "";
  const checkOut = h.check_out || "";

  let sub = "";
  if (perNight) sub += `$${Math.round(perNight)}/night`;
  if (nights) sub += sub ? ` · ${nights} nights` : `${nights} nights`;
  if (totalCost) sub += sub ? ` · $${Math.round(totalCost)} total` : `$${Math.round(totalCost)} total`;
  if (h.rating && h.rating > 0) sub += sub ? ` · ${h.rating}/10` : `${h.rating}/10`;

  let extra = "";
  if (address) extra += `<div class="detail-sub">${esc(address)}</div>`;
  if (checkIn && checkOut) extra += `<div class="detail-sub">Check-in: ${esc(checkIn)} · Check-out: ${esc(checkOut)}</div>`;

  return `<div class="detail-box"><h4>Hotel</h4>
    <div class="detail-main">${esc(name)}</div>
    <div class="detail-sub">${esc(sub)}</div>
    ${extra}
  </div>`;
}

function buildWeatherBox(pkg) {
  const w = pkg.weather_summary || "No weather data";
  const short = typeof w === "string" ? w.slice(0, 120) + (w.length > 120 ? "..." : "") : "";

  return `<div class="detail-box"><h4>Weather</h4>
    <div class="detail-main">${esc(short)}</div>
  </div>`;
}

function buildDataBox(pkg) {
  const sources = [];
  if (pkg.flights && (pkg.flights.outbound || pkg.flights.total_flight_cost)) sources.push("Flights");
  if (pkg.hotel && pkg.hotel.name) sources.push("Hotels");
  if (pkg.weather_summary) sources.push("Weather");
  if (pkg.itinerary && pkg.itinerary.length) sources.push("Itinerary");

  return `<div class="detail-box"><h4>Data Sources</h4>
    <div class="detail-main">${sources.length} sources used</div>
    <div class="detail-sub">${sources.join(", ") || "None"}</div>
  </div>`;
}

function buildItinerary(days) {
  const dayList = toArray(days);
  if (!dayList.length) return "";
  let html = `<div class="itinerary"><h3>Day-by-Day Itinerary</h3>`;
  dayList.forEach(day => {
    if (!day || typeof day !== "object") return;
    const title = `Day ${day.day || "?"}` + (day.date ? ` — ${day.date}` : "");
    html += `<div class="day-card">
      <div class="day-title">${esc(title)}</div>`;
    const acts = toArray(day.activities);
    if (acts.length) {
      html += `<ul>`;
      acts.forEach(a => { html += `<li>${esc(typeof a === "object" ? (a.name || a.activity || JSON.stringify(a)) : a)}</li>`; });
      html += `</ul>`;
    }
    if (day.notes) {
      html += `<div class="detail-sub" style="margin-top:0.25rem;font-style:italic">${esc(day.notes)}</div>`;
    }
    html += `</div>`;
  });
  html += `</div>`;
  return html;
}

function buildCostBreakdown(pkg) {
  const c = pkg.cost_breakdown || {};
  const flights = c.flights || c.flights_usd || 0;
  const hotel = c.hotel || c.hotel_usd || 0;
  const daily = c.daily_expenses_estimate || c.daily_expenses_estimate_usd || 0;
  const total = c.total || c.total_usd || 0;

  if (!total && !flights && !hotel) return "";

  let html = `<div class="cost-breakdown"><h4>Cost Breakdown</h4>`;
  if (flights) html += `<div class="cost-row"><span>Flights</span><span>$${Math.round(flights)}</span></div>`;
  if (hotel) html += `<div class="cost-row"><span>Hotel</span><span>$${Math.round(hotel)}</span></div>`;
  if (daily) html += `<div class="cost-row"><span>Daily expenses (est.)</span><span>$${Math.round(daily)}</span></div>`;
  if (total) html += `<div class="cost-row total"><span>Total</span><span>$${Math.round(total)}</span></div>`;
  if (c.daily_expenses_notes) html += `<div class="detail-sub" style="margin-top:0.5rem">${esc(c.daily_expenses_notes)}</div>`;
  html += `</div>`;
  return html;
}

function getTotal(pkg) {
  const c = pkg.cost_breakdown || {};
  const t = c.total || c.total_usd || 0;
  return t ? `$${Math.round(t).toLocaleString()}` : "";
}

// ── Steps rendering ─────────────────────────────────────────────────────

function renderSteps(steps) {
  if (!steps || steps.length === 0) return;

  stepsContainer.innerHTML = "";

  steps.forEach((step, idx) => {
    const card = document.createElement("div");
    card.className = "step-card";

    const header = document.createElement("div");
    header.className = "step-header";
    header.innerHTML = `
      <span><span class="module-name">${esc(step.module)}</span> — Step ${idx + 1}</span>
      <span>&#9660;</span>
    `;

    const body = document.createElement("div");
    body.className = "step-body";
    body.innerHTML = `
      <h4>Prompt</h4>
      <pre>${esc(JSON.stringify(step.prompt, null, 2))}</pre>
      <h4>Response</h4>
      <pre>${esc(JSON.stringify(step.response, null, 2))}</pre>
    `;

    header.addEventListener("click", () => body.classList.toggle("open"));
    card.appendChild(header);
    card.appendChild(body);
    stepsContainer.appendChild(card);
  });

  toggleStepsBtn.innerHTML = `Show Execution Trace (<span id="step-count">${steps.length}</span> steps)`;
  stepsSection.classList.remove("hidden");
}

// ── Utilities ────────────────────────────────────────────────────────────

function esc(str) {
  if (typeof str !== "string") return String(str || "");
  const el = document.createElement("span");
  el.textContent = str;
  return el.innerHTML;
}

function toArray(val) {
  if (Array.isArray(val)) return val;
  if (typeof val === "string" && val) return [val];
  return [];
}

function formatDateTime(dt) {
  if (!dt) return "";
  try {
    const d = new Date(dt);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) +
      " " + d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return dt;
  }
}
