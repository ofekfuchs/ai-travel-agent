## Extended Testing Scenarios — AI Travel Agent

This file adds deeper, scenario-based tests on top of `TESTING.md`, focusing on:

- Hotels & rooming semantics
- Session continuity and follow-up behavior
- Verifier vs Synthesizer interactions
- Scope guard and Azure content policy
- RAG usage
- Failure modes and recovery

Run the server as usual:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Then execute these tests through the UI at `http://127.0.0.1:8001` while watching the terminal logs.

---

## H. Hotels & Rooming (multi-traveler sanity)

These tests specifically stress the hotels tool, room calculation, and Synthesizer hotel boxes.

### H1 — 1 adult vs 2 adults (same dates/city)

- **Prompt 1:**  
  `Plan me a trip to Barcelona for 1 adult, from TLV, August 10-17 2026, budget $3000`
- **Prompt 2 (new trip):**  
  `Plan me a trip to Barcelona for 2 adults, from TLV, August 10-17 2026, budget $3000`

**Terminal expectations:**
- [ ] For Prompt 1, `search_hotels` params include `"adults": 1`, `"room_qty": "1"`.
- [ ] For Prompt 2, `search_hotels` params include `"adults": 2`, `"room_qty": "1"`.

**UI expectations:**
- [ ] Hotel box shows realistic per-night and total cost for 1 vs 2 adults (2 adults should be more expensive but still reasonable).

### H2 — 3 vs 5 adults (room splitting)

- **Prompt A:**  
  `Family trip to Barcelona, 3 adults, August 10-17 2026, budget $5000 from TLV`
- **Prompt B (new trip):**  
  `Family trip to Barcelona, 5 adults, August 10-17 2026, budget $7000 from TLV`

**Terminal expectations:**
- [ ] For 3 adults: `room_qty` logged as `"2"` (ceil(3/2)).
- [ ] For 5 adults: `room_qty` logged as `"3"`.

**UI expectations:**
- [ ] Hotel total cost for 5 adults is noticeably higher than for 3, but still within budget if packages are built.
- [ ] Hotel booking URLs end with `&group_adults=5&no_rooms=3`.

### H3 — Star rating and address presence

- **Prompt:**  
  `4 days in September in Tbilisi, from TLV, budget $2000, culture and food`

**UI expectations:**
- [ ] Hotel card shows a non-empty address (real address or area, not an internal wishlist label).
- [ ] Star rating (property class) appears somewhere in the hotel box or assumptions, if the Synthesizer surfaces it.

---

## I. Session Continuity & Follow-up Constraints

### I1 — Budget increase fixes Gate B

1. **First request:**  
   `Plan me a trip to Barcelona for 5 adults, from Tel Aviv, August 10-17 2026, budget $5000`
2. **Follow-up in same session:**  
   `and if I raise the budget to 6000$?`

**Terminal expectations:**
- [ ] First run: Gate B prints something like `GATE B: budget infeasible ($5724 > $5000)` and returns a budget card.
- [ ] `SESSION RESUMED` log appears for the follow-up.
- [ ] After the second Planner run, printed `constraints` include `"budget_total": 6000`.
- [ ] Gate B no longer prints `$5724 > $5000`; it treats the budget as feasible.

**UI expectations:**
- [ ] First response: “Budget Below Minimum” card (no packages).
- [ ] Second response: actual trip packages (Barcelona) instead of another infeasibility card.

### I2 — Follow-up WITHOUT changing constraints

1. Run **B1** from `TESTING.md` (Beach vacation in June from New York) until packages are shown.
2. In the **same session**, send:  
   `can you give me a cheaper option?`

**Checks:**
- [ ] Terminal logs show `SESSION RESUMED` and reuse of previous constraints.
- [ ] Origin, destination(s), and dates remain the same; only package selection/rationale changes.

---

## J. Verifier vs Synthesizer Regression Checks

These guard against replan loops and over-strict verifier behavior.

### J1 — Verifier approves with warnings when hotel data is slightly incomplete

- **Prompt:**  
  `3 nights in a cheap hotel in Budapest, from TLV, anytime in October, budget $800`

**Terminal expectations:**
- [ ] Verifier decision is `APPROVE` or `APPROVE_WITH_WARNINGS`, not `REJECT` solely because of minor hotel field omissions.
- [ ] Any hotel-related issues are listed under warnings, not fatal issues.

### J2 — No infinite replan loop at LLM cap

- Use a moderately complex prompt (e.g. **B9** family vacation from `TESTING.md`).

**Terminal expectations:**
- [ ] `LLM calls: X/8` never reaches 8 while Supervisor is still repeatedly choosing `replan`.
- [ ] If Verifier rejects once, Supervisor either:
  - Produces a best-effort package, or
  - Stops cleanly with a clear message (no 500s, no endless loop).

### J3 — Gate B vs Verifier ordering

- Reuse **B4** (tight budget) from `TESTING.md`.

**Checks:**
- [ ] When budget is obviously too low, Gate B runs and returns a budget card without invoking Synthesizer/Verifier.
- [ ] Verifier only runs when at least one package has been synthesized.

---

## K. Scope Guard & Azure Content Policy

Run these to confirm the updated Supervisor prompt no longer triggers Azure’s jailbreak filter while still enforcing scope.

### K1 — Pure coding request

- **Prompt:**  
  `Help me write a Python script to scrape a website`

**UI expectations:**
- [ ] Polite refusal explaining that the agent only does travel planning.
- [ ] Optionally nudges the user to describe a trip instead.

**Terminal expectations:**
- [ ] Single Supervisor round with action `ask_clarification` (or equivalent).
- [ ] No `BadRequestError` or `ResponsibleAIPolicyViolation` is logged.

### K2 — General knowledge question

- **Prompt:**  
  `What is the capital of France?`

**Checks:**
- [ ] Same behavior as K1: clarify or refuse, not plan a random trip.
- [ ] No Azure content-policy errors in the logs.

---

## L. RAG Regression Checks

These ensure RAG remains helpful and cost-effective.

### L1 — RAG actually influences destinations

- **Prompt:**  
  `Europe in May, best value for money, 1 week`

**Terminal expectations:**
- [ ] At least one RAG tool call (e.g. `rag_search`) appears in the Executor logs.
- [ ] Planner constraints include concrete European cities that exist in your Wikivoyage upload.

**UI expectations:**
- [ ] Chosen cities look reasonable for “best value in May” (e.g. not obviously off-season or irrelevant).

### L2 — RAG not overused for highly specific requests

- **Prompt:**  
  `4 days in Rome in September, budget $1500 from NYC`

**Checks:**
- [ ] Little or no RAG activity (no repeated `rag_search` calls).
- [ ] Planner doesn’t overwrite the explicit destination with other cities just because RAG has data.

---

## M. Failure Modes & Recovery

### M1 — Missing RAPIDAPI_KEY for flights/hotels

1. Temporarily unset or blank out `RAPIDAPI_KEY` in `app/config.py`.
2. Restart the server.
3. Run a simple B1/B2-style prompt.

**Terminal expectations:**
- [ ] Flights/hotels tools log `"... not configured"` once per tool.
- [ ] No server crash or stack trace from this condition alone.

**UI expectations:**
- [ ] User sees a graceful explanation (e.g. no pricing data) rather than a raw 500 error.

### M2 — Supabase cache table missing

1. Point `SUPABASE_URL` to a Supabase project without a `cache` table (or temporarily rename it).
2. Run **B1** once.

**Checks:**
- [ ] Cache lookups fail silently; logs may show at most a one-time connectivity/table error.
- [ ] The request still completes with packages or a clear “no data” response.

### M3 — LLM budget exhaustion is reported clearly

1. Temporarily lower `LLM_CALL_CAP` in `app/config.py` (e.g. from 8 to 2).
2. Run a complex multi-destination prompt (e.g. **B9**).

**Terminal expectations:**
- [ ] Supervisor prints a clear note when the LLM call cap is reached.

**UI expectations:**
- [ ] Response explicitly indicates best-effort / budget-exhausted status (not just a generic error).

