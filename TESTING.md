# Testing Checklist — AI Travel Agent

Use this file to systematically test every part of the system.
Run the server first: `uvicorn app.main:app --host 127.0.0.1 --port 8001`

---

## A. API Endpoint Tests (Quick Health Checks)

Open these URLs in your browser or use curl:

- [ ] `GET http://127.0.0.1:8001/health` → `{"status":"ok"}`
- [ ] `GET http://127.0.0.1:8001/api/team_info` → JSON with names, emails, group number
- [ ] `GET http://127.0.0.1:8001/api/agent_info` → JSON with description, purpose, examples, steps
- [ ] `GET http://127.0.0.1:8001/api/model_architecture` → PNG image downloads
- [ ] `GET http://127.0.0.1:8001/` → Frontend UI loads in browser

---

## B. Core Agentic Tests (Run in UI at http://127.0.0.1:8001)

For each test, type the prompt in the UI and click "Plan My Trip".
Check BOTH the UI result AND the terminal output.

### B1: Standard beach request
- **Prompt:** `Beach vacation in June from New York`
- **Expected UI:** 2-3 package cards (Budget Pick, Best Value, Premium)
- **Check in UI:**
  - [ ] Each card shows destination, dates, total price
  - [ ] Flight box shows outbound AND return details
  - [ ] Hotel box shows name, price/night, total, check-in/out
  - [ ] Weather summary is present
  - [ ] Day-by-day itinerary exists
  - [ ] Cost breakdown adds up (flights + hotel + daily = total)
  - [ ] "Search Flights" and "Search Hotels" buttons link to real URLs
  - [ ] Booking links open Kayak/Booking.com in new tab
  - [ ] Assumptions/Notes section is expandable
  - [ ] Execution Trace shows 5-6 steps (Supervisor, Planner, Supervisor, Supervisor, Synthesizer, Verifier)
- **Check in terminal:**
  - [ ] Supervisor Round 1: "plan"
  - [ ] Planner generates 8-12 tasks for 2-3 destinations
  - [ ] Executor Phase 1 runs first destination
  - [ ] Supervisor Round 2: "continue" (needs more destinations)
  - [ ] Executor Phase 2 runs second destination
  - [ ] Supervisor Round 3: "synthesize"
  - [ ] Verifier: "APPROVE" (or APPROVE with warnings)
  - [ ] Total LLM calls: 6 or fewer

### B2: Specific destination with budget
- **Prompt:** `4 days in September in Tbilisi, from TLV, budget $2000, culture and food`
- **Expected:** Package(s) for Tbilisi, prices within $2000
- **Check:**
  - [ ] Planner extracted: origin=TLV, destination=Tbilisi, budget=$2000
  - [ ] Packages are priced under $2000
  - [ ] Itinerary mentions culture/food activities
  - [ ] 4-day itinerary (not 7)

### B3: Vague region
- **Prompt:** `Europe in May, best value for money, 1 week`
- **Expected:** Planner picks 2-3 European cities
- **Check:**
  - [ ] RAG knowledge was fetched (check terminal for "RAG=5")
  - [ ] Planner chose specific European cities (not just "Europe")
  - [ ] Multiple destinations compared
  - [ ] Supervisor decided when enough data collected

### B4: Tight budget
- **Prompt:** `Weekend trip, $300 budget, from NYC to somewhere warm`
- **Expected:** Either budget_infeasible response OR 1 tight package
- **Check:**
  - [ ] If Gate B triggered: shows cheapest options found + suggestions
  - [ ] If package built: price is near $300
  - [ ] Supervisor reasoning mentions budget considerations

### B5: Super vague request (should ask for clarification)
- **Prompt:** `I want to go somewhere`
- **Expected:** Clarification question asking for origin
- **Check:**
  - [ ] Response is a text question, NOT packages
  - [ ] Only 1 LLM call used (Supervisor)
  - [ ] Question asks about departure city or travel details

### B6: Scope guard (non-travel request)
- **Prompt:** `Write me a Python script to sort a list`
- **Expected:** Polite refusal — "I'm an AI Travel Planning Agent"
- **Check:**
  - [ ] Response says it can only help with travel
  - [ ] Only 1 LLM call used
  - [ ] No tools were called

### B7: Another scope guard test
- **Prompt:** `What is the capital of France?`
- **Expected:** Polite refusal or redirect to travel
- **Check:**
  - [ ] Does NOT try to plan a trip to Paris
  - [ ] Explains its travel-only purpose

### B8: Romantic getaway
- **Prompt:** `Romantic getaway in Paris for Valentine's, $5000, from London`
- **Expected:** Paris packages with February dates, luxury options
- **Check:**
  - [ ] Dates are around Feb 14
  - [ ] Budget $5000 allows premium options
  - [ ] Itinerary has romantic activities

### B9: Multi-traveler
- **Prompt:** `Family vacation for 4 people, July, Southeast Asia, 10 days, $8000 from NYC`
- **Expected:** Asian city packages, 4 adults
- **Check:**
  - [ ] Hotel search used adults=4
  - [ ] Planner picked specific Asian cities
  - [ ] 10-day itinerary

---

## C. Agent Property Checks (verify in terminal for ANY test above)

These are what make it an AGENT, not a workflow:

- [ ] **Multi-round Supervisor**: Terminal shows "SUPERVISOR ROUND 2/6" and "ROUND 3/6"
- [ ] **Reasoning at each step**: Each Supervisor decision has a "reason:" line
- [ ] **Phased execution**: "Executor Phase 1: 'Miami'", "Executor Phase N: 'San Juan'"
- [ ] **Adaptive decisions**: Supervisor skips a destination or changes plan based on data
- [ ] **Constraint extraction**: "constraints: {...}" appears after Planner
- [ ] **RAG grounding**: "RAG=5" or similar in data summary
- [ ] **LLM budget managed**: "(LLM calls: X/8)" never exceeds 8
- [ ] **Verifier independence**: Verifier can produce warnings, not just rubber-stamp

---

## D. Edge Cases

- [ ] **Empty prompt:** `""` → Should handle gracefully (clarification or error)
- [ ] **Past dates:** `Trip to Paris last week from NYC` → Should pick future dates
- [ ] **Non-English city:** `Trip to 東京 from NYC in spring` → Should resolve or handle
- [ ] **Very long prompt:** 200+ words of detailed preferences → Should extract key constraints

---

## E. Frontend Visual Checks (in browser)

- [ ] Suggestion chips work (clicking fills prompt box)
- [ ] Loading spinner appears during processing
- [ ] No `[object Object]` anywhere in the output
- [ ] No JavaScript errors in browser console (F12 → Console tab)
- [ ] Flight box shows both outbound and return flights
- [ ] Hotel shows name, price, check-in/out dates
- [ ] Booking buttons are clickable and open real URLs
- [ ] Itinerary shows day-by-day with activities
- [ ] Cost breakdown totals are correct
- [ ] Execution Trace is collapsible
- [ ] Warning banner appears on best-effort responses

---

## F. Supabase Checks (after running test B1)

Go to your Supabase dashboard → Table Editor:

- [ ] `cache` table: has entries for flights/hotels/weather searches
- [ ] `trips` table: new row with prompt, packages JSON, status "approved"
- [ ] `execution_logs` table: 3+ rows (one per Supervisor round)
- [ ] `sessions` table: row with session_id

---

## G. Cost Tracking

After each test, note the terminal's LLM call count:

| Test | LLM Calls | Verdict | Notes |
|------|-----------|---------|-------|
| B1   |           |         |       |
| B2   |           |         |       |
| B3   |           |         |       |
| B4   |           |         |       |
| B5   |           |         |       |
| B6   |           |         |       |
| B7   |           |         |       |
| B8   |           |         |       |
| B9   |           |         |       |

---

## Estimated LLM Cost Per Test

Each LLM call costs approximately $0.01-0.05 depending on prompt size.
A typical 6-call test costs ~$0.10-0.20.
Scope guard tests (B6, B7) cost ~$0.01 (1 call).
Clarification tests (B5) cost ~$0.01 (1 call).

**Budget:** $13 total | **Spent so far:** ~$0.50 | **Each full test:** ~$0.15
