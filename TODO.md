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

- [ ] Add unit tests (`tests/` folder) for:
  - [ ] Planner JSON parsing (constraints + tasks extraction)
  - [ ] Verifier rule-based checks (missing fields, budget overflow)
  - [ ] Cache logic (make_cache_key, get/set)
  - [ ] Feasibility check (_feasibility_check, _is_budget_tight)
  - [ ] Response builders (_build_final_response, etc.)
  - [ ] Destination grouping (split_tasks_by_destination)
- [ ] Parallel tool execution (async within each destination group)
- [ ] Better execution trace in UI (show "Round 1: Supervisor decided X because Y")
- [ ] Frontend error handling for budget_infeasible and no_pricing_data statuses
- [ ] Multi-turn conversation (follow-up like "make it cheaper")
- [ ] Update architecture.png to reflect new Supervisor-driven loop

---

## Nice to Have (Differentiators, Do After Core Is Solid)

- [ ] Loading progress in UI — show "Searching flights for Miami..." in real-time
- [ ] Trip comparison view — side-by-side packages
- [ ] Export trip to PDF or email
- [ ] Rate limiting / input sanitization on API
- [ ] Cost tracking — show API budget used per request in UI
- [ ] Destination photos (Unsplash API or similar)
- [ ] Map visualization of itinerary
- [ ] User preferences memory (remember past trips)
- [ ] A/B testing different Supervisor prompt strategies

---

## Known Limitations

- No multi-turn conversation (each request is independent)
- Booking links are search URLs, not direct deeplinks to specific fares
- RAG only covers ~460 Wikivoyage chunks (popular destinations)
- Weather for far-future dates uses historical averages, not forecasts
- POI data from OpenTripMap can be sparse for some cities
- Hotel ratings are sometimes 0 (Booking.com doesn't always return scores)
