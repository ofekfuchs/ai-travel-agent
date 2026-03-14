"""Generate architecture.png — Supervisor-driven ReAct Agent diagram.

Clear, comprehensive layout: no overlapping labels; External APIs, LLM, and
data layer (RAG, Supabase) in distinct sections.

Run: python scripts/generate_architecture.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, Rectangle, Ellipse
from pathlib import Path

# Larger canvas for clarity
fig, ax = plt.subplots(figsize=(24, 16))
ax.set_xlim(0, 24)
ax.set_ylim(0, 16)
ax.set_aspect("equal")
ax.axis("off")
fig.patch.set_facecolor("white")

# Colors
C_SUPER = "#7c3aed"
C_PLAN  = "#2563eb"
C_EXEC  = "#059669"
C_SYNTH = "#0891b2"
C_VERIF = "#d97706"
C_TOOL  = "#64748b"
C_STATE = "#475569"
C_USER  = "#1e40af"
C_DB    = "#7f1d1d"
C_RAG   = "#166534"
C_GATE  = "#dc2626"
C_LLM   = "#6366f1"


def draw_box(x, y, w, h, label, color, sublabel=None, alpha=0.2, fontsize=10):
    box = FancyBboxPatch((x, y), w, h,
                         boxstyle="round,pad=0.08",
                         facecolor=color, edgecolor=color,
                         alpha=alpha, linewidth=2)
    ax.add_patch(box)
    border = FancyBboxPatch((x, y), w, h,
                            boxstyle="round,pad=0.08",
                            facecolor="none", edgecolor=color,
                            linewidth=2)
    ax.add_patch(border)
    ax.text(x + w/2, y + h/2 + (0.14 if sublabel else 0), label,
            ha="center", va="center", fontsize=fontsize, fontweight="bold", color=color)
    if sublabel:
        ax.text(x + w/2, y + h/2 - 0.2, sublabel,
                ha="center", va="center", fontsize=7, color=color, alpha=0.85)


def draw_diamond(cx, cy, size, label, color, sublabel=None):
    pts = [(cx, cy+size), (cx+size, cy), (cx, cy-size), (cx-size, cy)]
    diamond = plt.Polygon(pts, facecolor=color, edgecolor=color, alpha=0.2, linewidth=2)
    ax.add_patch(diamond)
    border = plt.Polygon(pts, facecolor="none", edgecolor=color, linewidth=2)
    ax.add_patch(border)
    ax.text(cx, cy, label, ha="center", va="center", fontsize=9, fontweight="bold", color=color)
    if sublabel:
        ax.text(cx, cy - size - 0.25, sublabel, ha="center", fontsize=7,
                fontweight="bold", color=color, alpha=0.8)


def arrow(x1, y1, x2, y2, color="#334155", label="", style="->", lw=1.5, curve=0, label_offset=(0, 0)):
    connection = f"arc3,rad={curve}" if curve else "arc3,rad=0"
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color, lw=lw, connectionstyle=connection))
    if label:
        mx = (x1 + x2) / 2 + label_offset[0]
        my = (y1 + y2) / 2 + label_offset[1]
        if curve and label_offset == (0, 0):
            my += 0.4 * (1 if curve > 0 else -1)
        ax.text(mx, my, label, ha="center", va="center", fontsize=7,
                color=color, fontstyle="italic",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="none", alpha=0.95))


# ═══════════════════════════════════════════════════════════════════
# Title
# ═══════════════════════════════════════════════════════════════════
ax.text(12, 15.4, "AI Travel Agent — Supervisor-Driven ReAct Architecture",
        ha="center", va="center", fontsize=18, fontweight="bold", color="#1e293b")
ax.text(12, 14.7, "Course Project · Group 3_11 · Ofek Fuchs & Omri Lazover",
        ha="center", va="center", fontsize=11, color="#64748b")

# ═══════════════════════════════════════════════════════════════════
# Main flow (left to right): User → Supervisor → Planner → Executor
# ═══════════════════════════════════════════════════════════════════
draw_box(0.8,  10.0, 1.9, 1.05, "User", C_USER, "free-form prompt")
draw_diamond(4.2, 10.25, 0.65, "Supervisor", C_SUPER, "THOUGHT")
draw_box(6.8,  10.0, 2.0, 1.05, "Planner", C_PLAN, "PLAN + RAG query")
draw_box(10.2, 10.0, 2.0, 1.05, "Executor", C_EXEC, "ACTION (parallel)")

# ═══════════════════════════════════════════════════════════════════
# Synthesis row: Gate B → Trip Synthesizer → Verifier
# ═══════════════════════════════════════════════════════════════════
draw_box(3.8,  6.8, 2.2, 1.05, "Gate B", C_GATE, "budget feasibility")
draw_box(7.4,  6.8, 2.4, 1.05, "Trip Synthesizer", C_SYNTH, "SYNTHESIS (RAG from state)")
draw_box(10.8, 6.8, 2.0, 1.05, "Verifier", C_VERIF, "REFLECTION")

# ═══════════════════════════════════════════════════════════════════
# SharedState (wide, center bottom)
# ═══════════════════════════════════════════════════════════════════
draw_box(2.5, 3.4, 11.0, 1.5, "SharedState", C_STATE,
         "constraints, flights, hotels, weather, POIs, RAG chunks, drafts")

# ═══════════════════════════════════════════════════════════════════
# Right column: LLM (top), then External APIs (section + 4 boxes), RAG, Supabase
# ═══════════════════════════════════════════════════════════════════
draw_box(18.5, 13.2, 3.2, 0.9, "LLM", C_LLM, "LLMod.ai · GPT-4o")

# Section label only — "External APIs" so it doesn’t sit on the API names
ax.text(20.1, 11.9, "External APIs", ha="center", va="center",
        fontsize=10, fontweight="bold", color=C_TOOL)

# Four separate API boxes (no single "Tools" box overlapping names)
apis = [
    ("Flights API", "Booking.com"),
    ("Hotels API", "Booking.com"),
    ("Weather API", "Open-Meteo"),
    ("POI API", "OpenTripMap"),
]
for i, (name, src) in enumerate(apis):
    draw_box(17.8, 9.8 - i * 1.35, 2.6, 1.0, name, C_TOOL, src)

# RAG and Supabase
draw_box(17.8, 4.0, 2.6, 1.2, "RAG", C_RAG)
ax.text(19.1, 4.85, "Pinecone", ha="center", fontsize=9, fontweight="bold", color=C_RAG)
ax.text(19.1, 4.45, "(Wikivoyage)", ha="center", fontsize=7, color=C_RAG, alpha=0.8)

draw_box(17.8, 1.8, 2.6, 1.6, "Supabase", C_DB)
ax.text(19.1, 3.0, "Cache", ha="center", fontsize=8, fontweight="bold", color=C_DB)
ax.text(19.1, 2.6, "Trips · Sessions · Logs", ha="center", fontsize=7, color=C_DB, alpha=0.9)

# ═══════════════════════════════════════════════════════════════════
# Arrows — main flow with labels offset to avoid overlap
# ═══════════════════════════════════════════════════════════════════
arrow(2.7, 10.52, 3.55, 10.52, C_USER, "prompt")
arrow(4.85, 10.52, 6.8, 10.52, C_PLAN, "plan/replan")
arrow(8.8, 10.52, 10.2, 10.52, C_EXEC, "tasks")

# Executor → External APIs (to first API box)
arrow(12.2, 10.52, 17.8, 10.3, C_TOOL, "calls", label_offset=(0.5, 0.3))

# Executor → Supervisor (observation loop)
arrow(11.2, 10.8, 4.85, 10.8, C_SUPER, "observe → next", curve=0.18, label_offset=(0, 0.6))

# Supervisor → Gate B
arrow(4.2, 9.6, 4.9, 7.85, C_GATE, "")

# Gate B → User (infeasible)
arrow(3.8, 7.6, 2.7, 10.0, C_GATE, "infeasible", curve=-0.1)

# Gate B → Synthesizer
arrow(6.0, 7.32, 7.4, 7.32, C_SYNTH, "feasible")

# Supervisor → Synthesizer
arrow(4.2, 9.6, 7.4, 7.85, C_SYNTH, "synthesize", curve=-0.06)

# Synthesizer → Verifier
arrow(9.8, 7.32, 10.8, 7.32, C_VERIF, "audit")

# Verifier → Supervisor
arrow(11.8, 7.6, 4.85, 9.9, C_SUPER, "approve/reject", curve=-0.1, label_offset=(-0.6, 0))

# Supervisor → User (response)
arrow(3.55, 10.2, 2.7, 10.2, "#059669", "response", curve=-0.04)

# Planner → RAG
arrow(8.8, 10.0, 17.8, 4.6, C_RAG, "query", curve=-0.06)

# Executor / tools → Supabase (cache)
arrow(19.1, 4.0, 19.1, 3.4, C_DB, "cache")

# Dashed: agents ↔ SharedState
for x, y_end in [(4.2, 8.5), (7.8, 8.5), (11.8, 8.5), (8.0, 6.8), (11.8, 6.8), (4.9, 6.8)]:
    ax.plot([x, x], [4.9, y_end], color="#94a3b8", lw=0.9, ls="--", alpha=0.5)

# Dashed: LLM used by Supervisor, Planner, Synthesizer, Verifier (Executor = 0 LLM)
ax.plot([18.5, 12], [13.65, 10.5], color=C_LLM, lw=1.1, ls="--", alpha=0.45)
ax.plot([18.5, 12], [13.65, 7.3], color=C_LLM, lw=1.1, ls="--", alpha=0.45)
ax.text(16.2, 12.0, "LLM", fontsize=6, color=C_LLM, alpha=0.9, fontstyle="italic")
ax.text(16.2, 10.2, "calls", fontsize=6, color=C_LLM, alpha=0.9, fontstyle="italic")

# ═══════════════════════════════════════════════════════════════════
# ReAct loop box
# ═══════════════════════════════════════════════════════════════════
loop = FancyBboxPatch((3.5, 9.2), 9.2, 2.0,
                      boxstyle="round,pad=0.15",
                      facecolor="none", edgecolor=C_SUPER,
                      linewidth=1.8, linestyle="dashed", alpha=0.5)
ax.add_patch(loop)
ax.text(8.1, 11.35, "ReAct Loop (Thought → Action → Observation)",
        ha="center", fontsize=10, fontweight="bold", color=C_SUPER, alpha=0.85,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.92, pad=3))

# ═══════════════════════════════════════════════════════════════════
# Legend
# ═══════════════════════════════════════════════════════════════════
ly = 0.85
ax.text(0.8, ly, "Agents (match API steps):", fontsize=8, fontweight="bold", color="#1e293b")
for i, (name, col) in enumerate([
    ("Supervisor", C_SUPER), ("Planner", C_PLAN),
    ("Trip Synthesizer", C_SYNTH), ("Verifier", C_VERIF), ("Executor", C_EXEC)
]):
    ax.plot([2.2 + i * 2.6, 2.45 + i * 2.6], [ly, ly], color=col, lw=3)
    ax.text(2.5 + i * 2.6, ly, name, fontsize=7, color=col, va="center")

ax.text(0.8, 0.35,
        "LLM: max 12 calls/request (typical 5–7). Executor: 0 LLM. Data: Supabase (cache, trips, sessions, logs).",
        fontsize=7, color="#64748b")

plt.tight_layout(pad=0.6)
out_path = Path(__file__).resolve().parent.parent / "architecture.png"
plt.savefig(out_path, dpi=160, bbox_inches="tight",
            facecolor="white", edgecolor="none")
print(f"Saved {out_path}")
