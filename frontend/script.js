/* ── DOM refs ─────────────────────────────────────────────────────────── */
const promptEl  = document.getElementById("prompt");
const sendBtn   = document.getElementById("send-btn");
const chatArea  = document.getElementById("chat-area");
const newTripBtn = document.getElementById("new-trip-btn");

/* ── Session state ────────────────────────────────────────────────────── */
let currentSessionId = null;
let progressTimer = null;

/* ── Init ─────────────────────────────────────────────────────────────── */
showWelcome();

/* ── Auto-resize textarea ─────────────────────────────────────────────── */
promptEl.addEventListener("input", () => {
  promptEl.style.height = "auto";
  promptEl.style.height = Math.min(promptEl.scrollHeight, 120) + "px";
});

/* ── Enter to send ────────────────────────────────────────────────────── */
promptEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendBtn.click();
  }
});

/* ── New Trip ─────────────────────────────────────────────────────────── */
newTripBtn.addEventListener("click", () => {
  resetSession();
  chatArea.innerHTML = "";
  showWelcome();
  promptEl.value = "";
  promptEl.style.height = "auto";
  promptEl.focus();
});

/* ── Main send handler ────────────────────────────────────────────────── */
sendBtn.addEventListener("click", async () => {
  const prompt = promptEl.value.trim();
  if (!prompt || sendBtn.disabled) return;

  addUserMessage(prompt);
  promptEl.value = "";
  promptEl.style.height = "auto";
  sendBtn.disabled = true;
  startProgress(prompt);

  try {
    const body = { prompt };
    if (currentSessionId) body.session_id = currentSessionId;

    const res = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await res.json();
    stopProgress();

    if (data.session_id) currentSessionId = data.session_id;

    if (data.status === "error") {
      addAgentMessage(`<div class="error-text">${esc(data.error || "Unknown error")}</div>`);
    } else {
      renderResponse(data.response);
    }

    if (data.steps && data.steps.length > 0) {
      addStepsSection(data.steps, data.llm_calls_used, data.elapsed_seconds);
    }
  } catch (err) {
    stopProgress();
    addAgentMessage(`<div class="error-text">Network error: ${esc(err.message)}</div>`);
  } finally {
    sendBtn.disabled = false;
  }
});

/* ═══════════════════════════════════════════════════════════════════════
   CHAT MANAGEMENT
   ═══════════════════════════════════════════════════════════════════════ */

function showWelcome() {
  const msg = addAgentMessage(
    `<div class="welcome-title">Where to next?</div>
     <p class="welcome-sub">Tell me about your dream trip — destination, dates, budget, interests — and I'll find the best flights, hotels, and build a complete itinerary for you.</p>
     <div class="quick-actions">
       <button class="quick-chip" data-prompt="4 days in Paris in June, budget $1500, flying from New York. I love museums and good food.">🗼 Paris trip</button>
       <button class="quick-chip" data-prompt="A week in London in September, moderate budget around $2000. I'm interested in history and pubs.">🇬🇧 London week</button>
       <button class="quick-chip" data-prompt="Romantic getaway to Berlin for 3 days, budget $1000 flying from Paris. We like art and nightlife.">🎨 Berlin romantic</button>
       <button class="quick-chip" data-prompt="Beach vacation in June from New York, 1 week, best value for money">🏖️ Beach getaway</button>
     </div>`,
    "welcome-msg"
  );

  msg.querySelectorAll(".quick-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      resetSession();
      promptEl.value = chip.dataset.prompt;
      promptEl.focus();
    });
  });
}

function resetSession() {
  currentSessionId = null;
  promptEl.placeholder = "Where do you want to go? Tell me everything...";
}

function addUserMessage(text) {
  const msg = document.createElement("div");
  msg.className = "msg user-msg";
  msg.innerHTML = `
    <div class="msg-avatar">You</div>
    <div class="msg-content"><p>${esc(text)}</p></div>`;
  chatArea.appendChild(msg);
  scrollToBottom();
  return msg;
}

function addAgentMessage(html, extraClass) {
  const msg = document.createElement("div");
  msg.className = `msg agent-msg${extraClass ? " " + extraClass : ""}`;
  msg.innerHTML = `
    <div class="msg-avatar">&#9992;</div>
    <div class="msg-content">${html}</div>`;
  chatArea.appendChild(msg);
  scrollToBottom();
  return msg;
}

/* ═══════════════════════════════════════════════════════════════════════
   LIVE PROGRESS INDICATOR
   ═══════════════════════════════════════════════════════════════════════ */

function extractDestinationHint(prompt) {
  const lower = prompt.toLowerCase();
  const patterns = [
    /(?:to|in|visit|for)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)/,
    /(paris|london|berlin|rome|tokyo|barcelona|amsterdam|prague|vienna|lisbon|cancun|miami|bali|dubai|bangkok|new york|los angeles|san francisco)/i,
    /(europe|asia|caribbean|south america|africa|middle east|southeast asia)/i,
  ];
  for (const p of patterns) {
    const m = prompt.match(p);
    if (m) return m[1];
  }
  if (/beach|island|tropical/i.test(lower)) return "beach destinations";
  if (/mountain|hiking|ski/i.test(lower)) return "mountain destinations";
  if (/city|urban|culture/i.test(lower)) return "cities";
  return null;
}

function buildProgressPhases(prompt) {
  const dest = extractDestinationHint(prompt);
  const destLabel = dest ? ` for ${dest}` : "";
  return [
    { text: "Understanding your request...", phase: "Analyzing", pct: 5, delay: 0 },
    { text: `Searching destinations${destLabel}`, phase: "Planning", pct: 12, delay: 3000 },
    { text: `Looking up flights${destLabel}`, phase: "Flights", pct: 25, delay: 8000 },
    { text: "Comparing hotel options", phase: "Hotels", pct: 40, delay: 16000 },
    { text: "Checking weather forecasts", phase: "Weather", pct: 52, delay: 24000 },
    { text: "Finding points of interest", phase: "Attractions", pct: 60, delay: 32000 },
    { text: "Building trip packages", phase: "Assembling", pct: 75, delay: 50000 },
    { text: "Running quality checks", phase: "Verifying", pct: 88, delay: 70000 },
    { text: "Almost there...", phase: "Finishing", pct: 95, delay: 100000 },
  ];
}

function startProgress(prompt) {
  stopProgress();

  const phases = buildProgressPhases(prompt);
  let phaseIdx = 0;
  const startTime = Date.now();
  const completedSteps = [];

  const el = document.createElement("div");
  el.className = "msg agent-msg progress-msg";
  el.id = "progress-indicator";
  el.innerHTML = `
    <div class="msg-avatar">&#9992;</div>
    <div class="msg-content">
      <div class="progress-container">
        <div class="progress-status">
          <div class="progress-spinner"></div>
          <div>
            <div class="progress-text">${phases[0].text}</div>
            <div class="progress-phase">${phases[0].phase}</div>
          </div>
        </div>
        <div class="progress-bar-track"><div class="progress-bar-fill" style="width:${phases[0].pct}%"></div></div>
        <div class="progress-steps"></div>
      </div>
    </div>`;
  chatArea.appendChild(el);
  scrollToBottom();

  const textEl = el.querySelector(".progress-text");
  const phaseEl = el.querySelector(".progress-phase");
  const barEl = el.querySelector(".progress-bar-fill");
  const stepsEl = el.querySelector(".progress-steps");

  progressTimer = setInterval(() => {
    const elapsed = Date.now() - startTime;
    const nextIdx = phaseIdx + 1;

    if (nextIdx < phases.length && elapsed >= phases[nextIdx].delay) {
      if (phaseIdx > 0) {
        completedSteps.push(phases[phaseIdx].phase);
      }
      phaseIdx = nextIdx;
      const p = phases[phaseIdx];

      textEl.style.opacity = "0";
      setTimeout(() => {
        textEl.textContent = p.text;
        phaseEl.textContent = p.phase;
        textEl.style.opacity = "1";
      }, 200);

      barEl.style.width = p.pct + "%";

      stepsEl.innerHTML = completedSteps.map(s =>
        `<span class="progress-step done"><span class="step-icon">✓</span> ${s}</span>`
      ).join("") +
        `<span class="progress-step active"><span class="step-icon">●</span> ${p.phase}</span>`;

      scrollToBottom();
    }
  }, 500);
}

function stopProgress() {
  if (progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
  const el = document.getElementById("progress-indicator");
  if (el) el.remove();
}

function scrollToBottom() {
  requestAnimationFrame(() => { chatArea.scrollTop = chatArea.scrollHeight; });
}

/* ═══════════════════════════════════════════════════════════════════════
   RESPONSE RENDERING
   ═══════════════════════════════════════════════════════════════════════ */

function renderResponse(responseStr) {
  if (!responseStr) {
    addAgentMessage(`<p>No response received.</p>`);
    return;
  }

  let parsed = null;
  try { parsed = JSON.parse(responseStr); } catch { /* not JSON */ }

  if (!parsed) {
    addAgentMessage(`<p>${esc(responseStr)}</p>`);
    return;
  }

  if (parsed.type === "clarification") {
    currentSessionId = parsed.session_id || null;
    renderClarification(parsed.message || responseStr);
    return;
  }

  if (parsed.status === "budget_infeasible") {
    renderBudgetInfeasible(parsed);
    promptEl.placeholder = "Adjust your preferences to continue...";
    return;
  }

  if (parsed.status === "no_pricing_data") {
    renderNoPricingData(parsed);
    promptEl.placeholder = "Try different dates or destinations...";
    return;
  }

  let packages = null;
  let warning  = null;

  if (Array.isArray(parsed)) {
    packages = parsed;
  } else if (parsed.packages && Array.isArray(parsed.packages)) {
    packages = parsed.packages;
    if (parsed.status === "best_effort") {
      warning = {
        issues: parsed.verifier_issues || [],
        question: parsed.question || "",
        category: parsed.repair_category || "",
      };
    }
  }

  if (packages && packages.length > 0 && packages[0].destination) {
    renderPackages(packages, warning);
  } else {
    addAgentMessage(`<p>${esc(responseStr)}</p>`);
  }
}

/* ── Clarification ────────────────────────────────────────────────────── */

function renderClarification(message) {
  let html = `<p>${esc(message).replace(/\n/g, "<br>")}</p>`;

  const chips = detectClarificationChips(message);
  if (chips.length > 0) {
    html += `<div class="clarify-chips">`;
    chips.forEach(c => {
      html += `<button class="clarify-chip" data-value="${esc(c)}">${esc(c)}</button>`;
    });
    html += `</div>`;
  }

  const msg = addAgentMessage(html);

  msg.querySelectorAll(".clarify-chip").forEach(btn => {
    btn.addEventListener("click", () => {
      const cur = promptEl.value.trim();
      promptEl.value = cur ? cur + ", " + btn.dataset.value : btn.dataset.value;
      promptEl.focus();
    });
  });

  promptEl.placeholder = "Answer the question above to continue...";
}

function detectClarificationChips(message) {
  const lower = message.toLowerCase();
  const chips = [];
  if (/\b(origin|depart|flying from|airport|where.*from|city.*from)\b/.test(lower))
    chips.push("TLV", "NYC", "London", "Paris", "Berlin");
  if (/\b(destination|where.*go|country|region|which.*city)\b/.test(lower))
    chips.push("Europe", "Southeast Asia", "Caribbean", "Anywhere cheap");
  if (/\b(budget|how much|price|spend|cost)\b/.test(lower))
    chips.push("Under $1000", "$1000-2000", "$2000-3000", "No limit");
  if (/\b(how long|duration|days|week|nights)\b/.test(lower))
    chips.push("3-4 days", "1 week", "10 days", "2 weeks");
  if (/\b(interest|activit|style|prefer|must.see)\b/.test(lower))
    chips.push("Beaches", "Culture & Museums", "Food & Nightlife", "Adventure", "Relaxation");
  return chips;
}

/* ── Budget Infeasible ────────────────────────────────────────────────── */

function renderBudgetInfeasible(data) {
  const cb = data.cost_breakdown || {};
  const cheapFlights = data.cheapest_flights_found || [];
  const question = data.question || "";

  let html = `<div class="status-card budget-card">
    <div class="status-icon">💰</div>
    <h3>Budget Below Minimum</h3>
    <p class="status-message">${esc(data.message || "")}</p>
    <div class="cost-grid">
      <div class="cost-item">
        <span class="cost-label">Cheapest flights</span>
        <span class="cost-value">$${Math.round(cb.cheapest_roundtrip_flights || 0)}</span>
      </div>
      <div class="cost-item">
        <span class="cost-label">Cheapest hotel total</span>
        <span class="cost-value">$${Math.round(cb.cheapest_hotel_total || 0)}</span>
      </div>
      <div class="cost-item">
        <span class="cost-label">Daily expenses (est.)</span>
        <span class="cost-value">$${Math.round(cb.estimated_daily_expenses || 0)}</span>
      </div>
      <div class="cost-item total">
        <span class="cost-label">Minimum needed</span>
        <span class="cost-value">$${Math.round(cb.lower_bound_total || 0)}</span>
      </div>
      <div class="cost-item">
        <span class="cost-label">Your budget</span>
        <span class="cost-value">$${Math.round(cb.user_budget || 0)}</span>
      </div>
      <div class="cost-item">
        <span class="cost-label">Gap</span>
        <span class="cost-value gap">${cb.gap_percentage || 0}% over</span>
      </div>
    </div>`;

  if (cheapFlights.length) {
    html += `<div class="cheap-options"><h4>Cheapest flights found</h4><ul>`;
    cheapFlights.forEach(f => {
      html += `<li>${esc(f.airline || "?")} ${esc(f.origin || "")} → ${esc(f.destination || "")} — $${Math.round(f.price || 0)} RT</li>`;
    });
    html += `</ul></div>`;
  }

  if (question) {
    html += `<div class="status-question"><strong>What would you like to adjust?</strong><p>${esc(question).replace(/\n/g, "<br>")}</p></div>`;
  }

  html += `</div>`;
  addAgentMessage(html);
}

/* ── No Pricing Data ──────────────────────────────────────────────────── */

function renderNoPricingData(data) {
  const constraints = data.constraints_extracted || {};
  const ragCount = data.rag_knowledge_found || 0;
  const llmCalls = data.llm_calls_used || 0;

  let html = `<div class="status-card nodata-card">
    <div class="status-icon">🔍</div>
    <h3>No Pricing Data Found</h3>
    <p class="status-message">${esc(data.message || "Could not find flight or hotel pricing.")}</p>
    <div class="status-details">
      <p>LLM calls used: ${llmCalls}/8</p>
      ${ragCount ? `<p>Destination knowledge found: ${ragCount} chunks</p>` : ""}
      ${constraints.destinations ? `<p>Searched destinations: ${esc(constraints.destinations.join(", "))}</p>` : ""}
    </div>
  </div>`;

  addAgentMessage(html);
}

/* ── Packages ─────────────────────────────────────────────────────────── */

function renderPackages(packages, warning) {
  addAgentMessage(
    `<p>I found <strong>${packages.length} trip package${packages.length > 1 ? "s" : ""}</strong> for you! Compare the options below.</p>`
  );

  const wrapper = document.createElement("div");
  wrapper.className = "packages-wrapper";

  if (warning) {
    let wh = `<div class="warning-banner"><div class="warning-icon">⚠️</div><div class="warning-body"><strong>Best-effort results</strong> — the quality checker flagged some issues:`;
    if (warning.issues && warning.issues.length) {
      wh += `<ul class="warning-issues">`;
      warning.issues.forEach(i => { wh += `<li>${esc(i)}</li>`; });
      wh += `</ul>`;
    }
    if (warning.question) {
      wh += `<p class="warning-question">${esc(warning.question)}</p>`;
    }
    wh += `</div></div>`;
    wrapper.innerHTML += wh;
  }

  packages.forEach(pkg => {
    const card = document.createElement("div");
    card.className = "package-card " + getPackageTypeClass(pkg.label);
    try {
      card.innerHTML = buildPackageHTML(pkg);
    } catch (e) {
      card.innerHTML = `<div class="package-header"><div><span class="package-label">${esc(pkg.label || pkg.destination || "Package")}</span></div></div>
        <div class="package-body"><pre>${esc(JSON.stringify(pkg, null, 2))}</pre></div>`;
    }
    wrapper.appendChild(card);
  });

  chatArea.appendChild(wrapper);
  scrollToBottom();
}

/* ═══════════════════════════════════════════════════════════════════════
   PACKAGE CARD BUILDERS
   ═══════════════════════════════════════════════════════════════════════ */

function getPackageTypeClass(label) {
  if (!label) return "";
  const lower = label.toLowerCase();
  if (lower.includes("budget") || lower.includes("cheap")) return "budget";
  if (lower.includes("best value") || lower.includes("value")) return "best-value";
  if (lower.includes("premium") || lower.includes("luxury")) return "premium";
  return "";
}

function getPackageLabelIcon(label) {
  if (!label) return "✈️";
  const lower = label.toLowerCase();
  if (lower.includes("budget") || lower.includes("cheap")) return "💰";
  if (lower.includes("best value") || lower.includes("value")) return "⭐";
  if (lower.includes("premium") || lower.includes("luxury")) return "👑";
  return "✈️";
}

function buildPackageHTML(pkg) {
  const label = pkg.label || "Trip Package";
  const dest  = pkg.destination || "Unknown";
  const dates = formatDateWindow(pkg.date_window);
  const total = getTotal(pkg);
  const icon = getPackageLabelIcon(label);

  let html = `
    <div class="package-header">
      <div>
        <span class="package-label">${icon} ${esc(label)}</span>
        <div class="package-dest">${esc(dest)}</div>
        <div class="package-dates">${esc(dates)}</div>
      </div>
      <div class="package-total">${total}</div>
    </div>
    <div class="package-body">`;

  html += `<div class="detail-grid">`;
  html += buildFlightBox(pkg);
  html += buildHotelBox(pkg);
  html += buildWeatherBox(pkg);
  html += buildDataBox(pkg);
  html += `</div>`;

  if (pkg.itinerary && pkg.itinerary.length > 0) html += buildItinerary(pkg.itinerary);
  html += buildCostBreakdown(pkg);

  if (pkg.rationale)
    html += `<div class="rationale"><strong>Why this package:</strong> ${esc(pkg.rationale)}</div>`;

  const links = pkg.booking_links || {};
  const flightLink = links.flights_search || (pkg.flights && pkg.flights.outbound && pkg.flights.outbound.booking_url) || "";
  const hotelLink  = links.hotels_search  || (pkg.hotel && pkg.hotel.booking_url) || "";
  if (flightLink || hotelLink) {
    html += `<div class="booking-links">`;
    if (flightLink) html += `<a href="${esc(flightLink)}" target="_blank" rel="noopener" class="booking-btn flights-btn">✈ Search Flights</a>`;
    if (hotelLink)  html += `<a href="${esc(hotelLink)}" target="_blank" rel="noopener" class="booking-btn hotels-btn">🏨 Search Hotels</a>`;
    html += `</div>`;
  }

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

  if (!out.origin && !out.routing && !totalCost)
    return `<div class="detail-box"><h4>✈ Flights</h4><div class="detail-main">No flight data</div></div>`;

  let html = `<div class="detail-box"><h4>✈ Flights</h4>`;

  if (out.origin || out.routing) {
    const outRoute = out.routing || `${out.origin || "?"} → ${out.destination || "?"}`;
    let outSub = out.airline || "";
    if (out.departure) outSub += outSub ? ` · ${formatDateTime(out.departure)}` : formatDateTime(out.departure);
    if (out.stops !== undefined) outSub += ` · ${out.stops === 0 ? "Direct" : out.stops + " stop(s)"}`;
    html += `<div class="flight-leg">
      <div class="flight-leg-label">Outbound</div>
      <div class="detail-main">${esc(outRoute)}</div>
      <div class="detail-sub">${esc(outSub)}</div></div>`;
  }

  if (ret.origin || ret.routing || ret.departure) {
    const retRoute = ret.routing || `${ret.origin || "?"} → ${ret.destination || "?"}`;
    let retSub = ret.airline || "";
    if (ret.departure) retSub += retSub ? ` · ${formatDateTime(ret.departure)}` : formatDateTime(ret.departure);
    if (ret.stops !== undefined) retSub += ` · ${ret.stops === 0 ? "Direct" : ret.stops + " stop(s)"}`;
    html += `<div class="flight-leg">
      <div class="flight-leg-label">Return</div>
      <div class="detail-main">${esc(retRoute)}</div>
      <div class="detail-sub">${esc(retSub)}</div></div>`;
  }

  if (totalCost)
    html += `<div class="detail-sub" style="margin-top:0.5rem;font-weight:600">$${Math.round(totalCost)} roundtrip</div>`;

  html += `</div>`;
  return html;
}

function buildHotelBox(pkg) {
  const h = pkg.hotel || {};
  const name     = h.name || "No hotel data";
  const perNight = h.per_night || h.per_night_usd || h.price_per_night || 0;
  const totalC   = h.total_cost || h.total_cost_usd || h.total_price || 0;
  const nights   = h.nights || "";
  const address  = h.address || "";
  const checkIn  = h.check_in || "";
  const checkOut = h.check_out || "";

  let sub = "";
  if (perNight)  sub += `$${Math.round(perNight)}/night`;
  if (nights)    sub += sub ? ` · ${nights} nights` : `${nights} nights`;
  if (totalC)    sub += sub ? ` · $${Math.round(totalC)} total` : `$${Math.round(totalC)} total`;
  if (h.rating && h.rating > 0) sub += sub ? ` · ${h.rating}/10` : `${h.rating}/10`;

  let extra = "";
  if (address) extra += `<div class="detail-sub">${esc(address)}</div>`;
  if (checkIn && checkOut) extra += `<div class="detail-sub">Check-in: ${esc(checkIn)} · Check-out: ${esc(checkOut)}</div>`;

  return `<div class="detail-box"><h4>🏨 Hotel</h4>
    <div class="detail-main">${esc(name)}</div>
    <div class="detail-sub">${esc(sub)}</div>${extra}</div>`;
}

function buildWeatherBox(pkg) {
  const w = pkg.weather_summary || "No weather data";
  const short = typeof w === "string" ? w.slice(0, 120) + (w.length > 120 ? "..." : "") : "";
  return `<div class="detail-box"><h4>🌤 Weather</h4><div class="detail-main">${esc(short)}</div></div>`;
}

function buildDataBox(pkg) {
  const sources = [];
  if (pkg.flights && (pkg.flights.outbound || pkg.flights.total_flight_cost)) sources.push("Flights");
  if (pkg.hotel && pkg.hotel.name) sources.push("Hotels");
  if (pkg.weather_summary) sources.push("Weather");
  if (pkg.itinerary && pkg.itinerary.length) sources.push("Itinerary");
  return `<div class="detail-box"><h4>📊 Data Sources</h4>
    <div class="detail-main">${sources.length} sources used</div>
    <div class="detail-sub">${sources.join(", ") || "None"}</div></div>`;
}

function buildItinerary(days) {
  const dayList = toArray(days);
  if (!dayList.length) return "";
  let html = `<div class="itinerary"><h3>Day-by-Day Itinerary</h3>`;
  dayList.forEach(day => {
    if (!day || typeof day !== "object") return;
    const title = `Day ${day.day || "?"}` + (day.date ? ` — ${day.date}` : "");
    html += `<div class="day-card"><div class="day-title">${esc(title)}</div>`;
    const acts = toArray(day.activities);
    if (acts.length) {
      html += `<ul>`;
      acts.forEach(a => { html += `<li>${esc(typeof a === "object" ? (a.name || a.activity || JSON.stringify(a)) : a)}</li>`; });
      html += `</ul>`;
    }
    if (day.notes) html += `<div class="detail-sub" style="margin-top:0.25rem;font-style:italic">${esc(day.notes)}</div>`;
    html += `</div>`;
  });
  html += `</div>`;
  return html;
}

function buildCostBreakdown(pkg) {
  const c = pkg.cost_breakdown || {};
  const flights = c.flights || c.flights_usd || 0;
  const hotel   = c.hotel || c.hotel_usd || 0;
  const daily   = c.daily_expenses_estimate || c.daily_expenses_estimate_usd || 0;
  const total   = c.total || c.total_usd || 0;

  if (!total && !flights && !hotel) return "";

  let html = `<div class="cost-breakdown"><h4>Cost Breakdown</h4>`;
  if (flights) html += `<div class="cost-row"><span>✈ Flights</span><span>$${Math.round(flights)}</span></div>`;
  if (hotel)   html += `<div class="cost-row"><span>🏨 Hotel</span><span>$${Math.round(hotel)}</span></div>`;
  if (daily)   html += `<div class="cost-row"><span>🍽 Daily expenses (est.)</span><span>$${Math.round(daily)}</span></div>`;
  if (total)   html += `<div class="cost-row total"><span>Total</span><span>$${Math.round(total)}</span></div>`;
  if (c.daily_expenses_notes) html += `<div class="detail-sub" style="margin-top:0.5rem">${esc(c.daily_expenses_notes)}</div>`;
  html += `</div>`;
  return html;
}

function getTotal(pkg) {
  const c = pkg.cost_breakdown || {};
  const t = c.total || c.total_usd || 0;
  return t ? `$${Math.round(t).toLocaleString()}` : "";
}

function formatDateWindow(dw) {
  if (!dw) return "";
  if (typeof dw === "string") return dw;
  if (typeof dw === "object") {
    const start = dw.start || dw.start_date || dw.from || "";
    const end   = dw.end || dw.end_date || dw.to || "";
    if (start && end) return `${start} to ${end}`;
    return start || end || JSON.stringify(dw);
  }
  return String(dw);
}

/* ═══════════════════════════════════════════════════════════════════════
   EXECUTION TRACE (ReAct-style)
   ═══════════════════════════════════════════════════════════════════════ */

function addStepsSection(steps, llmCalls, elapsedSec) {
  const infos = steps.map(classifyStep);
  const supervisorCount = infos.filter(s => s.role === "thought").length;

  const metaParts = [`${steps.length} steps`, `${supervisorCount} reasoning cycles`];
  if (llmCalls != null) metaParts.push(`${llmCalls}/8 LLM calls`);
  if (elapsedSec != null) metaParts.push(`${elapsedSec}s`);

  const wrapper = document.createElement("div");
  wrapper.className = "trace-wrapper";

  let html = `<button class="trace-toggle">
    <span class="trace-toggle-icon">&#9660;</span>
    Execution Trace &mdash; ${metaParts.join(", ")}
  </button>`;

  html += `<div class="trace-body">`;
  steps.forEach((step, i) => {
    const si = infos[i];
    const rawContent = _getStepResponseContent(step);
    const parsed = tryParseJSON(rawContent);
    const mod = (step.module || "").toLowerCase();

    const obs = si.role === "thought" ? extractObservation(step) : null;
    const obsH = obs ? `<div class="step-observation">Observed: ${esc(obs)}</div>` : "";

    const tasksHtml = mod === "planner" ? formatPlannerTasks(parsed) : "";
    const reasoning = extractReasoning(step, parsed, mod);
    const reasoningHtml = reasoning
      ? `<div class="step-reasoning"><h4>Reasoning</h4><p class="reasoning-text">${reasoning.split("\n").map(esc).join("<br>")}</p></div>`
      : "";

    html += `<div class="step-card step-role-${si.role}">`;
    html += `<div class="step-header">
      <span>
        <span class="react-badge ${si.role}">${si.roleLabel}</span>
        <span class="module-name">${esc(si.module)}</span>
        ${si.summary ? `<span class="step-summary">${esc(si.summary)}</span>` : ""}
      </span>
      <span class="step-toggle-icon">&#9660;</span>
    </div>`;
    html += `<div class="step-body">
      ${obsH}
      ${tasksHtml}
      ${reasoningHtml}
      <h4>Prompt</h4>
      <pre>${esc(typeof step.prompt === "object" ? JSON.stringify(step.prompt, null, 2) : String(step.prompt))}</pre>
      <h4>Response</h4>
      <pre>${esc(typeof step.response === "object" ? JSON.stringify(step.response, null, 2) : String(step.response))}</pre>
    </div>`;
    html += `</div>`;
  });
  html += `</div>`;

  wrapper.innerHTML = html;

  const toggle = wrapper.querySelector(".trace-toggle");
  const body   = wrapper.querySelector(".trace-body");
  toggle.addEventListener("click", () => {
    body.classList.toggle("hidden");
    toggle.querySelector(".trace-toggle-icon").innerHTML =
      body.classList.contains("hidden") ? "&#9654;" : "&#9660;";
  });

  wrapper.querySelectorAll(".step-header").forEach(header => {
    header.addEventListener("click", () => {
      header.nextElementSibling.classList.toggle("open");
    });
  });

  chatArea.appendChild(wrapper);
  scrollToBottom();
}

/** Get raw response content from step (handles different shapes). */
function _getStepResponseContent(step) {
  if (!step || !step.response) return "";
  const r = step.response;
  if (typeof r === "string") return r;
  return r.content ?? r.text ?? r.message ?? "";
}

function classifyStep(step) {
  const mod = (step.module || "").toLowerCase();
  const parsed = tryParseJSON(_getStepResponseContent(step));

  if (mod === "supervisor") {
    const action = parsed ? parsed.next_action : "?";
    const reason = parsed ? parsed.reason : "";
    return { role: "thought", roleLabel: "THOUGHT", module: "Supervisor",
             summary: `${action}${reason ? " — " + reason : ""}` };
  }
  if (mod === "planner") {
    const tc = parsed && parsed.tasks ? parsed.tasks.length : 0;
    const dests = parsed && parsed.constraints && parsed.constraints.destinations
      ? parsed.constraints.destinations.join(", ") : "";
    const taskNames = parsed && Array.isArray(parsed.tasks)
      ? parsed.tasks.map(t => t.task || t.task_type || "?").filter(Boolean).join(", ")
      : "";
    let summary = `${tc} tasks${dests ? " for " + dests : ""}`;
    if (taskNames) summary += `: ${taskNames}`;
    return { role: "plan", roleLabel: "PLAN", module: "Planner", summary };
  }
  if (mod.includes("synthesizer") || mod.includes("trip")) {
    const pc = parsed && parsed.packages ? parsed.packages.length : (parsed ? 1 : 0);
    const rationale = parsed && Array.isArray(parsed.packages) && parsed.packages[0]?.rationale
      ? parsed.packages[0].rationale : null;
    let summary = `${pc} package(s) assembled`;
    if (rationale) summary += ` — ${rationale.slice(0, 80)}${rationale.length > 80 ? "…" : ""}`;
    return { role: "action", roleLabel: "SYNTHESIS", module: "Trip Synthesizer", summary };
  }
  if (mod === "verifier") {
    const dec = parsed ? parsed.decision : "?";
    const ic  = parsed && parsed.issues   ? parsed.issues.length   : 0;
    const wc  = parsed && parsed.warnings ? parsed.warnings.length : 0;
    let detail = dec;
    if (ic) detail += `, ${ic} issue(s)`;
    if (wc) detail += `, ${wc} warning(s)`;
    const reason = parsed?.quality_notes
      ? parsed.quality_notes
      : (parsed?.issues?.length || parsed?.warnings?.length)
        ? [].concat(parsed.issues || [], parsed.warnings || []).slice(0, 3).join("; ")
        : null;
    if (reason) detail += ` — ${reason.slice(0, 100)}${reason.length > 100 ? "…" : ""}`;
    return { role: "reflection", roleLabel: "REFLECTION", module: "Verifier", summary: detail };
  }
  return { role: "action", roleLabel: "ACTION", module: step.module || "Agent", summary: "" };
}

function extractObservation(step) {
  if (!step.prompt || !step.prompt.user) return null;
  const text = step.prompt.user;
  const m = text.match(/Data collected so far:\s*(\{[^}]+\})/);
  if (!m) return null;
  try {
    const d = JSON.parse(m[1]);
    const parts = [];
    if (d.flights)    parts.push(`${d.flights} flights`);
    if (d.hotels)     parts.push(`${d.hotels} hotels`);
    if (d.weather)    parts.push(`${d.weather} weather`);
    if (d.pois)       parts.push(`${d.pois} POIs`);
    if (d.rag_chunks) parts.push(`${d.rag_chunks} RAG chunks`);
    return parts.length ? parts.join(", ") : null;
  } catch { return null; }
}

/** Format planner tasks for display. Returns HTML string or "". */
function formatPlannerTasks(parsed) {
  if (!parsed || !Array.isArray(parsed.tasks) || parsed.tasks.length === 0) return "";
  const items = parsed.tasks.map((t, i) => {
    const taskType = t.task || t.task_type || "?";
    const dest = t.destination_group || t.destination || "";
    const params = t.params || {};
    const paramsStr = Object.keys(params).length
      ? Object.entries(params).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(", ")
      : "";
    const label = dest ? `${taskType} → ${dest}` : taskType;
    return `<li><span class="task-type">${esc(label)}</span>${paramsStr ? ` <span class="task-params">(${esc(paramsStr)})</span>` : ""}</li>`;
  });
  return `<h4>Tasks (${parsed.tasks.length})</h4><ul class="planner-tasks">${items.join("")}</ul>`;
}

/** Extract reasoning text for display. Returns string or null. */
function extractReasoning(step, parsed, mod) {
  if (!parsed || typeof parsed !== "object") return null;
  const m = (mod || "").toLowerCase();
  if (m === "supervisor" && parsed.reason) return parsed.reason;
  if (m === "verifier") {
    if (parsed.quality_notes) return parsed.quality_notes;
    const parts = [];
    if (parsed.decision) parts.push(`Decision: ${parsed.decision}`);
    if (parsed.issues?.length) parts.push(`Issues: ${parsed.issues.join("; ")}`);
    if (parsed.warnings?.length) parts.push(`Warnings: ${parsed.warnings.join("; ")}`);
    return parts.length ? parts.join("\n\n") : null;
  }
  if ((m.includes("synthesizer") || m.includes("trip")) && Array.isArray(parsed.packages) && parsed.packages.length > 0) {
    const rationales = parsed.packages.map(p => p.rationale).filter(Boolean);
    return rationales.length ? rationales.join("\n\n") : null;
  }
  return null;
}

/* ═══════════════════════════════════════════════════════════════════════
   UTILITIES
   ═══════════════════════════════════════════════════════════════════════ */

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
  } catch { return dt; }
}

function tryParseJSON(str) {
  if (!str || typeof str !== "string") return null;
  try { return JSON.parse(str); } catch { return null; }
}
