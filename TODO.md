# TODO — AI Travel Agent

## Status Legend
- [x] Done
- [ ] To do
- [~] In progress

---

## Completed

- [x] Supervisor-driven agentic loop (ReAct pattern)
- [x] Multi-round Supervisor with observe → reason → act cycle
- [x] Planner: merged constraint extraction + RAG in single LLM call
- [x] Executor: phased execution by destination group
- [x] Synthesizer: tiered packages (Budget/Best Value/Premium)
- [x] Verifier: pragmatic quality auditor (critical vs minor issues)
- [x] Scope guard (non-travel request refusal)
- [x] Fix ask_clarification logic (origin OR date, not AND)
- [x] Fix Gate B flight_cost*2 bug (flights already roundtrip)
- [x] Fix /api/agent_info placeholder with real example
- [x] Clean up legacy MAX_SUPERVISOR_ITERATIONS in config
- [x] Booking links for flights (Kayak) and hotels (Booking.com)
- [x] Session persistence to Supabase
- [x] Execution audit logs to Supabase
- [x] Two-level caching (memory + Supabase)
- [x] RAG with Pinecone/Wikivoyage
- [x] Frontend: package cards, itinerary, cost breakdown, booking buttons
- [x] README.md with setup instructions
- [x] TESTING.md with organized test checklist

---

## Should Do (High Value, No Extra Cost)

- [x] Add unit tests (`tests/test_deterministic.py`) — 27 tests covering:
  - [x] Destination grouping (split_tasks_by_destination, get_destination_groups)
  - [x] Cache logic (make_cache_key determinism, uniqueness, format)
  - [x] Feasibility check (_feasibility_check, _is_budget_tight)
  - [x] Rejection classification (_classify_rejection)
  - [x] SharedState LLM budget management (can_call_llm, remaining_calls, cap)
- [x] Parallel tool execution (ThreadPoolExecutor within each destination group)
- [x] ReAct-style execution trace in UI (THOUGHT/PLAN/SYNTHESIS/REFLECTION badges)
- [x] Frontend error handling for budget_infeasible and no_pricing_data statuses
- [x] Updated architecture.png with Supervisor-driven ReAct loop diagram
- [x] Per-destination observations in Supervisor context (richer reasoning)
- [x] Multi-turn conversation (session memory + follow-up context merging)
- [x] Interactive clarification chips (smart quick-reply buttons under questions)
- [x] Per-destination hotel tagging (destination_city field for Supervisor reasoning)
- [x] Chat-based UI/UX redesign (conversation history, message bubbles, typing indicator)
- [x] Fix Synthesizer cross-destination: group data per city so packages span multiple destinations
- [x] Input validation (empty prompt, max length, basic sanitization)
- [x] LLM call count + elapsed time metadata in API response and UI trace
- [x] POI destination tagging for proper cross-destination data grouping
- [x] Fix broken import in scripts/test_tools_dry.py (_resolve_entity_id → _resolve_flight_location)
- [x] Increase Planner destination exploration from 2-3 to 3-4 cities for more variety
- [x] Planner anti-hallucination rules (never fabricate prices, always generate all 4 task types per destination)
- [x] Verifier deterministic price cross-check (catches fabricated flight/hotel prices without LLM)
- [x] Supervisor budget-awareness guidance (prefer synthesize over continue when LLM budget is tight)
- [x] Unit tests for price cross-check (4 new tests, total 31)
- [x] Fix session continuity: frontend no longer resets session_id after packages arrive
- [x] Backend returns session_id in every ExecuteResponse (not just clarification)
- [x] Session memory now includes previously searched destinations and offered packages
- [x] Follow-up prompts ("give me different locations") now include full prior context
- [x] Synthesizer: filter out destinations with 0 flights (prevents fabricated drive/train packages)
- [x] "Different locations" detection: auto-exclude previously offered destinations on follow-up
- [x] Planner: only pick cities with major commercial airports (no tiny towns like Montauk/Nags Head)
- [x] Verifier: detect fabricated ground transport (drive/bus/train) and reject
- [x] Verifier: don't flag destination mismatch when user explicitly asks for alternatives
- [x] Unit tests for destination grouping, alternative detection, transport fabrication (38 total)

---

## Nice to Have (Differentiators, Do After Core Is Solid)

- [ ] Loading progress in UI — show "Searching flights for Miami..." in real-time (SSE/WebSocket)
- [ ] Trip comparison view — side-by-side packages
- [ ] Export trip to PDF or email
- [ ] Destination photos (Unsplash API or similar)
- [ ] Map visualization of itinerary
- [ ] User preferences memory (remember past trips)
- [ ] A/B testing different Supervisor prompt strategies

---

## Known Limitations

- Multi-turn memory is in-memory only (lost on server restart; Supabase persistence is a future option)
- Booking links are search URLs, not direct deeplinks to specific fares
- RAG only covers ~460 Wikivoyage chunks (popular destinations)
- Weather for far-future dates uses historical averages, not forecasts
- POI data from OpenTripMap can be sparse for some cities
- Hotel ratings are sometimes 0 (Booking.com doesn't always return scores)
