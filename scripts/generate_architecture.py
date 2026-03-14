"""Generate architecture.png — Supervisor-driven ReAct Agent diagram.

Module names match the step labels in the API trace exactly:
  Supervisor, Planner, Executor, Trip Synthesizer, Verifier

Run: python scripts/generate_architecture.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Circle
from pathlib import Path

fig, ax = plt.subplots(figsize=(20, 14))
ax.set_xlim(0, 20)
ax.set_ylim(0, 14)
ax.set_aspect("equal")
ax.axis("off")
fig.patch.set_facecolor("white")

# Colors
C_SUPER = "#7c3aed"   # purple - thought/decision
C_PLAN  = "#2563eb"   # blue - planning
C_EXEC  = "#059669"   # green - action/execution
C_SYNTH = "#0891b2"   # teal - synthesis
C_VERIF = "#d97706"   # amber - reflection/verification
C_TOOL  = "#64748b"   # gray - tools
C_STATE = "#475569"   # dark gray - state
C_USER  = "#1e40af"   # dark blue - user
C_DB    = "#7f1d1d"   # dark red - databases
C_RAG   = "#166534"   # dark green - RAG
C_GATE  = "#dc2626"   # red - gates


def draw_box(x, y, w, h, label, color, sublabel=None, alpha=0.15, fontsize=10):
    box = FancyBboxPatch((x, y), w, h,
                         boxstyle="round,pad=0.1",
                         facecolor=color, edgecolor=color,
                         alpha=alpha, linewidth=2)
    ax.add_patch(box)
    border = FancyBboxPatch((x, y), w, h,
                            boxstyle="round,pad=0.1",
                            facecolor="none", edgecolor=color,
                            linewidth=2)
    ax.add_patch(border)
    ax.text(x + w/2, y + h/2 + (0.12 if sublabel else 0), label,
            ha="center", va="center", fontsize=fontsize, fontweight="bold", color=color)
    if sublabel:
        ax.text(x + w/2, y + h/2 - 0.18, sublabel,
                ha="center", va="center", fontsize=7, color=color, alpha=0.8)


def draw_diamond(cx, cy, size, label, color, sublabel=None):
    pts = [(cx, cy+size), (cx+size, cy), (cx, cy-size), (cx-size, cy)]
    diamond = plt.Polygon(pts, facecolor=color, edgecolor=color, alpha=0.15, linewidth=2)
    ax.add_patch(diamond)
    border = plt.Polygon(pts, facecolor="none", edgecolor=color, linewidth=2)
    ax.add_patch(border)
    ax.text(cx, cy, label, ha="center", va="center", fontsize=9, fontweight="bold", color=color)
    if sublabel:
        ax.text(cx, cy - size - 0.2, sublabel, ha="center", fontsize=7,
                fontweight="bold", color=color, alpha=0.7)


def draw_cylinder(x, y, w, h, label, color, sublabel=None):
    ellipse_h = 0.15
    rect = Rectangle((x, y + ellipse_h), w, h - ellipse_h,
                      facecolor=color, edgecolor=color, alpha=0.15, linewidth=2)
    ax.add_patch(rect)
    from matplotlib.patches import Ellipse
    top = Ellipse((x + w/2, y + h), w, ellipse_h * 2,
                  facecolor=color, edgecolor=color, alpha=0.15, linewidth=2)
    ax.add_patch(top)
    bottom = Ellipse((x + w/2, y + ellipse_h), w, ellipse_h * 2,
                     facecolor=color, edgecolor=color, alpha=0.3, linewidth=2)
    ax.add_patch(bottom)
    ax.text(x + w/2, y + h/2 + 0.1, label,
            ha="center", va="center", fontsize=8, fontweight="bold", color=color)
    if sublabel:
        ax.text(x + w/2, y + h/2 - 0.15, sublabel,
                ha="center", va="center", fontsize=6, color=color, alpha=0.8)


def arrow(x1, y1, x2, y2, color="#334155", label="", style="->", lw=1.5, curve=0, label_offset=(0, 0)):
    arrowprops = dict(arrowstyle=style, color=color, lw=lw,
                      connectionstyle=f"arc3,rad={curve}" if curve else "arc3,rad=0")
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=arrowprops)
    if label:
        mx, my = (x1+x2)/2 + label_offset[0], (y1+y2)/2 + label_offset[1]
        if curve and not label_offset[0]:
            my += 0.35 * (1 if curve > 0 else -1)
        ax.text(mx, my, label, ha="center", va="center", fontsize=7,
                color=color, fontstyle="italic",
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none", alpha=0.92))


# ══════════════════════════════════════════════════════════════════
# Title
# ══════════════════════════════════════════════════════════════════

ax.text(10, 13.0, "AI Travel Agent — Supervisor-Driven ReAct Architecture",
        ha="center", va="center", fontsize=16, fontweight="bold", color="#1e293b")

ax.text(10, 12.4, "Course Project | Group 3_11 | Ofek Fuchs & Omri Lazover",
        ha="center", va="center", fontsize=10, color="#64748b")

# ══════════════════════════════════════════════════════════════════
# Layout - Main Components (spaced to avoid overlapping labels)
# ══════════════════════════════════════════════════════════════════

# User
draw_box(0.5, 8.2, 1.8, 1.0, "User", C_USER, "free-form prompt")

# Supervisor (diamond - decision point)
draw_diamond(5.0, 8.7, 0.7, "Supervisor", C_SUPER, "THOUGHT")

# Planner
draw_box(7.8, 8.2, 2.0, 1.0, "Planner", C_PLAN, "PLAN + RAG query")

# Executor
draw_box(11.2, 8.2, 2.0, 1.0, "Executor", C_EXEC, "ACTION (parallel)")

# Trip Synthesizer (uses RAG chunks from SharedState)
draw_box(7.8, 5.4, 2.2, 1.0, "Trip Synthesizer", C_SYNTH, "SYNTHESIS (RAG from state)")

# Verifier
draw_box(11.2, 5.4, 2.0, 1.0, "Verifier", C_VERIF, "REFLECTION")

# Gate B (budget check)
draw_box(4.2, 5.4, 2.4, 1.0, "Gate B", C_GATE, "budget feasibility")

# ══════════════════════════════════════════════════════════════════
# SharedState (center bottom)
# ══════════════════════════════════════════════════════════════════

draw_box(4.5, 2.2, 7.0, 1.4, "SharedState", C_STATE,
         "constraints, flights, hotels, weather, POIs, RAG chunks, drafts")

# ══════════════════════════════════════════════════════════════════
# Tools Box (right side)
# ══════════════════════════════════════════════════════════════════

draw_box(14.8, 6.8, 2.6, 3.6, "Tools", C_TOOL)
tools = [
    ("Flights API", "Booking.com"),
    ("Hotels API", "Booking.com"),
    ("Weather API", "Open-Meteo"),
    ("POI API", "OpenTripMap"),
]
for i, (t, src) in enumerate(tools):
    ax.text(16.1, 10.0 - i*0.7, t, ha="center", va="center",
            fontsize=8, fontweight="bold", color=C_TOOL)
    ax.text(16.1, 9.7 - i*0.7, f"({src})", ha="center", va="center",
            fontsize=6, color=C_TOOL, alpha=0.7)

# ══════════════════════════════════════════════════════════════════
# RAG Box (far right)
# ══════════════════════════════════════════════════════════════════

draw_box(14.8, 5.0, 2.6, 1.4, "RAG", C_RAG)
ax.text(16.1, 5.9, "Pinecone", ha="center", fontsize=8, fontweight="bold", color=C_RAG)
ax.text(16.1, 5.5, "(Wikivoyage)", ha="center", fontsize=6, color=C_RAG, alpha=0.7)

# ══════════════════════════════════════════════════════════════════
# Supabase (bottom right) — Cache, Trips, Sessions, Logs
# ══════════════════════════════════════════════════════════════════

draw_box(14.8, 2.4, 2.6, 2.0, "Supabase", C_DB)
ax.text(16.1, 3.9, "Cache", ha="center", fontsize=8, fontweight="bold", color=C_DB)
ax.text(16.1, 3.5, "Trips", ha="center", fontsize=8, fontweight="bold", color=C_DB)
ax.text(16.1, 3.1, "Sessions", ha="center", fontsize=8, fontweight="bold", color=C_DB)
ax.text(16.1, 2.7, "Logs", ha="center", fontsize=8, fontweight="bold", color=C_DB)

# ══════════════════════════════════════════════════════════════════
# LLM Box (top right)
# ══════════════════════════════════════════════════════════════════

draw_box(14.8, 11.4, 2.6, 0.6, "LLM", "#6366f1")
ax.text(16.1, 11.7, "LLMod.ai / GPT-4o", ha="center", fontsize=7, fontweight="bold", color="#6366f1")

# ══════════════════════════════════════════════════════════════════
# Arrows (main flow) — positions match new layout; short labels to avoid overlap
# ══════════════════════════════════════════════════════════════════

# User → Supervisor
arrow(2.3, 8.7, 4.3, 8.7, C_USER, "prompt")

# Supervisor → Planner (plan/replan)
arrow(5.7, 8.7, 7.8, 8.7, C_PLAN, "plan/replan")

# Planner → Executor
arrow(9.8, 8.7, 11.2, 8.7, C_EXEC, "tasks")

# Executor → Tools
arrow(13.2, 8.7, 14.8, 8.0, C_TOOL, "")

# Executor → Supervisor (observation) — short label, offset so it doesn’t overlap
arrow(12.2, 8.9, 5.7, 8.9, C_SUPER, "observe → next", curve=0.2, label_offset=(0, 0.5))

# Supervisor → Gate B (downward)
arrow(5.0, 8.0, 5.4, 6.4, C_GATE, "")

# Gate B → User (infeasible)
arrow(4.2, 5.9, 2.3, 8.2, C_GATE, "infeasible", curve=-0.12)

# Gate B → Synthesizer (feasible)
arrow(6.6, 5.9, 7.8, 5.9, C_SYNTH, "feasible")

# Supervisor → Synthesizer
arrow(5.0, 8.0, 7.8, 6.4, C_SYNTH, "synthesize", curve=-0.08)

# Synthesizer → Verifier
arrow(10.0, 5.9, 11.2, 5.9, C_VERIF, "audit")

# Verifier → Supervisor
arrow(12.2, 6.4, 5.7, 8.2, C_SUPER, "approve/reject", curve=-0.12, label_offset=(-0.8, 0))

# Supervisor → User (response)
arrow(4.3, 8.5, 2.3, 8.5, "#059669", "response", curve=-0.05)

# Planner → RAG
arrow(9.8, 8.5, 14.8, 5.7, C_RAG, "query", curve=-0.08)

# Tools / Executor → Supabase (cache)
arrow(15.0, 6.8, 15.0, 4.4, C_DB, "cache", curve=0.05)

# LLM connections (dashed)
ax.plot([14.8, 12.2], [11.7, 8.9], color="#6366f1", lw=1, ls="--", alpha=0.4)
ax.plot([14.8, 9.8], [11.7, 8.7], color="#6366f1", lw=1, ls="--", alpha=0.4)
ax.plot([14.8, 10.0], [11.7, 6.4], color="#6366f1", lw=1, ls="--", alpha=0.4)
ax.plot([14.8, 12.2], [11.7, 6.4], color="#6366f1", lw=1, ls="--", alpha=0.4)
ax.plot([14.8, 5.7], [11.7, 8.9], color="#6366f1", lw=1, ls="--", alpha=0.4)

# Agents → SharedState (dashed read/write)
for x, y_end in [(5.0, 7.2), (8.9, 7.5), (12.2, 7.5), (5.4, 5.4)]:
    ax.plot([x, x], [3.6, y_end], color="#94a3b8", lw=0.8, ls="--", alpha=0.5)

# ══════════════════════════════════════════════════════════════════
# ReAct Loop annotation
# ══════════════════════════════════════════════════════════════════

loop_box = FancyBboxPatch((3.2, 6.6), 11.0, 2.8,
                           boxstyle="round,pad=0.2",
                           facecolor="none", edgecolor=C_SUPER,
                           linewidth=1.5, linestyle="dashed", alpha=0.4)
ax.add_patch(loop_box)
ax.text(8.7, 9.2, "ReAct Loop (Thought → Action → Observation)",
        ha="center", fontsize=9, fontweight="bold", color=C_SUPER, alpha=0.7,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.9, pad=2))

# ══════════════════════════════════════════════════════════════════
# Legend / Key
# ══════════════════════════════════════════════════════════════════

legend_y = 1.0
ax.text(0.6, legend_y, "Module Names (match API steps):", fontsize=7, fontweight="bold", color="#1e293b")
modules = ["Supervisor", "Planner", "Trip Synthesizer", "Verifier"]
colors = [C_SUPER, C_PLAN, C_SYNTH, C_VERIF]
for i, (mod, col) in enumerate(zip(modules, colors)):
    ax.plot([2.8 + i*3.2, 3.0 + i*3.2], [legend_y, legend_y], color=col, lw=3)
    ax.text(3.2 + i*3.2, legend_y, mod, fontsize=7, color=col, va="center")

# LLM and data annotation
ax.text(0.6, 0.35, "LLM Budget: max 12 calls/request | Typical: 5-7 | Executor: 0 LLM. Data: Supabase (cache, trips, sessions, logs).",
        fontsize=7, color="#64748b")

plt.tight_layout(pad=0.5)

out_path = Path(__file__).resolve().parent.parent / "architecture.png"
plt.savefig(out_path, dpi=150, bbox_inches="tight",
            facecolor="white", edgecolor="none")
print(f"Saved {out_path}")
