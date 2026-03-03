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

  // Try to parse as JSON (trip packages)
  let packages = null;
  try {
    const parsed = JSON.parse(responseStr);
    if (Array.isArray(parsed)) {
      packages = parsed;
    } else if (parsed.packages && Array.isArray(parsed.packages)) {
      packages = parsed.packages;
    }
  } catch {
    // Not JSON -- show as text
  }

  if (packages && packages.length > 0 && packages[0].destination) {
    renderPackages(packages);
  } else {
    textResponseContent.textContent = responseStr;
    textResponseSection.classList.remove("hidden");
  }
}

function renderPackages(packages) {
  packagesContainer.innerHTML = "";

  packages.forEach(pkg => {
    const card = document.createElement("div");
    card.className = "package-card";
    card.innerHTML = buildPackageHTML(pkg);
    packagesContainer.appendChild(card);
  });

  packagesSection.classList.remove("hidden");
}

function buildPackageHTML(pkg) {
  const label = pkg.label || "Trip Package";
  const dest = pkg.destination || "Unknown";
  const dates = pkg.date_window || "";
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

  // Booking links
  const links = pkg.booking_links || {};
  if (links.flights_search || links.hotels_search) {
    html += `<div class="booking-links">`;
    if (links.flights_search) {
      html += `<a href="${esc(links.flights_search)}" target="_blank" rel="noopener" class="booking-btn flights-btn">Search Flights</a>`;
    }
    if (links.hotels_search) {
      html += `<a href="${esc(links.hotels_search)}" target="_blank" rel="noopener" class="booking-btn hotels-btn">Search Hotels</a>`;
    }
    html += `</div>`;
  }

  // Assumptions
  if (pkg.assumptions && pkg.assumptions.length > 0) {
    html += `<details class="assumptions"><summary>Notes & Assumptions (${pkg.assumptions.length})</summary><ul>`;
    pkg.assumptions.forEach(a => { html += `<li>${esc(a)}</li>`; });
    html += `</ul></details>`;
  }

  html += `</div>`;
  return html;
}

function buildFlightBox(pkg) {
  const f = pkg.flights || {};
  const out = f.outbound || {};
  const ret = f.return || {};
  const totalCost = f.total_flight_cost || f.total_cost || 0;

  let main = "No flight data";
  let sub = "";

  if (out.origin || out.routing) {
    main = out.routing || `${out.origin || "?"} → ${out.destination || "?"}`;
    sub = out.airline ? `${out.airline}` : "";
    if (out.departure) sub += sub ? ` · ${formatDateTime(out.departure)}` : formatDateTime(out.departure);
    if (totalCost) sub += ` · $${Math.round(totalCost)} total`;
  } else if (totalCost) {
    main = `$${Math.round(totalCost)} estimated`;
    sub = out.notes || "See assumptions for details";
  }

  return `<div class="detail-box"><h4>Flights</h4>
    <div class="detail-main">${esc(main)}</div>
    <div class="detail-sub">${esc(sub)}</div>
  </div>`;
}

function buildHotelBox(pkg) {
  const h = pkg.hotel || {};
  const name = h.name || "No hotel data";
  const perNight = h.per_night || h.per_night_usd || h.price_per_night || 0;
  const totalCost = h.total_cost || h.total_cost_usd || h.total_price || 0;
  const nights = h.nights || "";

  let sub = "";
  if (perNight) sub += `$${Math.round(perNight)}/night`;
  if (nights) sub += sub ? ` · ${nights} nights` : `${nights} nights`;
  if (totalCost) sub += sub ? ` · $${Math.round(totalCost)} total` : `$${Math.round(totalCost)} total`;
  if (h.rating) sub += sub ? ` · ${h.rating}/10` : `${h.rating}/10`;

  return `<div class="detail-box"><h4>Hotel</h4>
    <div class="detail-main">${esc(name)}</div>
    <div class="detail-sub">${esc(sub)}</div>
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
  let html = `<div class="itinerary"><h3>Day-by-Day Itinerary</h3>`;
  days.forEach(day => {
    const title = `Day ${day.day}` + (day.date ? ` — ${day.date}` : "");
    html += `<div class="day-card">
      <div class="day-title">${esc(title)}</div>`;
    if (day.activities && day.activities.length) {
      html += `<ul>`;
      day.activities.forEach(a => { html += `<li>${esc(a)}</li>`; });
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
