import requests
import json
import time
import sys
from datetime import datetime

API_URL = "http://127.0.0.1:8000/api/execute"


def run_test(prompt: str, output_file: str = "agent_output.txt", expect_status: str | None = None):
    payload = {
        "prompt": prompt,
        "session_id": f"test-session-{int(time.time())}"  # Unique ID for each run
    }

    print("Sending request to the AI Travel Agent...")
    print("The agent is now thinking, fetching data from Booking.com API, and re-ranking (this might take 1-3 minutes)...")
    print("Meanwhile, check your server terminal to see the Supervisor's logs in real-time!\n")
    
    start_time = time.time()

    try:
        response = requests.post(API_URL, json=payload, timeout=300)
        response.raise_for_status()
        
        result = response.json()
        
        # --- Prepare text for saving ---
        output_lines = []
        output_lines.append(f"=== Agent Execution Report ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
        status = result.get("status")
        output_lines.append(f"Execution Time: {time.time() - start_time:.1f} seconds")
        output_lines.append(f"Final Status: {status}")
        output_lines.append("="*80)
        
        # --- Phase 1: Print Reasoning Steps ---
        output_lines.append("\nAgent's Reasoning Steps:")
        steps = result.get("steps", [])
        
        for i, step in enumerate(steps, 1):
            module = step.get("module", "Unknown")
            
            # Try to extract the model's response (JSON or text)
            step_resp = step.get("response", {})
            content = step_resp.get("content", str(step_resp))
            
            # Parse content as JSON for pretty printing if possible
            try:
                parsed_content = json.loads(content)
                content_str = json.dumps(parsed_content, indent=2, ensure_ascii=False)
            except:
                content_str = content # Fallback to raw text
                
            output_lines.append(f"\n[{i}] Module: {module}")
            output_lines.append(content_str)
            output_lines.append("-" * 40)
        
        # --- Phase 2: Add Final Response ---
        agent_response = result.get("response", "")

        # Pretty version (for readability)
        output_lines.append("\nFinal Response (Packages / Best Effort) - pretty JSON:")
        try:
            parsed_response = json.loads(agent_response)
            pretty_str = json.dumps(parsed_response, indent=2, ensure_ascii=False)
        except:
            pretty_str = agent_response
        output_lines.append(pretty_str)

        # Raw version (exact payload returned to the user)
        output_lines.append("\nFinal Response (raw JSON as returned by API):")
        output_lines.append(agent_response)
        
        # --- Save to Text File ---
        file_name = output_file
        with open(file_name, "w", encoding="utf-8") as f:
            f.write("\n".join(output_lines))

        if expect_status is not None and status != expect_status:
            print(f"WARNING: Expected status '{expect_status}' but got '{status}'")

        print(f"\nExecution completed successfully in {time.time() - start_time:.1f} seconds!")
        print(f"All output, including reasoning steps and final response, was saved to: {file_name}")
        
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to the server.")
        print("Is the server running? Make sure you ran 'uvicorn app.main:app --reload' in a separate terminal.")
    except requests.exceptions.Timeout:
        print("Error: Request timed out. The agent took too long to respond.")
    except Exception as e:
        print(f"Unexpected error: {e}")
        if 'response' in locals() and response.text:
            print(f"Server error details: {response.text}")

def run_simple_case():
    prompt = (
        "Plan a simple 3-night city break to Rome from TLV "
        "(May 10-13, 2026). Total budget: $900. One destination only."
    )
    run_test(prompt, output_file="agent_output_simple_single_destination.txt")


def run_family_trip_case():
    prompt = (
        "Plan a 7-night family beach holiday for 2 adults and 2 children, "
        "departing from TLV (Aug 1-8, 2026). Total budget: $3,500. "
        "Prefer an all-inclusive beachfront resort and kid-friendly activities."
    )
    run_test(prompt, output_file="agent_output_family_beach_holiday.txt")


def run_unclear_case():
    prompt = (
        "Plan a vacation from TLV with a total budget of $3,000. "
        "I haven't decided on dates or destination yet."
    )
    run_test(
        prompt,
        output_file="agent_output_unclear_no_dates.txt",
        expect_status="ask_clarification",
    )


def run_specific_request_case():
    prompt = (
        "Plan a 5-night trip to Barcelona from TLV (Sep 10-15, 2026) with a "
        "total budget of $2,500. I specifically want a hotel on the first line "
        "to the beach, with direct beachfront access."
    )
    run_test(prompt, output_file="agent_output_beach_first_line_hotel.txt")


if __name__ == "__main__":
    cases = {
        "simple": (run_simple_case, "Simple single-destination city break"),
        "family": (run_family_trip_case, "Family beach holiday"),
        "unclear": (run_unclear_case, "Unclear request (expect ask_clarification)"),
        "specific": (run_specific_request_case, "Specific beachfront hotel request"),
    }

    if len(sys.argv) < 2 or sys.argv[1] not in cases:
        print("Usage: python scripts/test_agent.py [simple|family|unclear|specific]")
        print("  simple  - Simple single-destination city break")
        print("  family  - Family beach holiday")
        print("  unclear - Unclear request that should trigger 'ask_clarification'")
        print("  specific- Specific request: hotel on the first line to the beach")
        sys.exit(1)

    key = sys.argv[1]
    func, description = cases[key]
    print(f"Running case '{key}': {description}")
    func()