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

fig, ax = plt.subplots(figsize=(16, 11))
ax.set_xlim(0, 16)
ax.set_ylim(0, 11)
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


def arrow(x1, y1, x2, y2, color="#334155", label="", style="->", lw=1.5, curve=0):
    arrowprops = dict(arrowstyle=style, color=color, lw=lw,
                      connectionstyle=f"arc3,rad={curve}" if curve else "arc3,rad=0")
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=arrowprops)
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        if curve:
            my += 0.25 * (1 if curve > 0 else -1)
        ax.text(mx, my, label, ha="center", va="center", fontsize=7,
                color=color, fontstyle="italic",
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none", alpha=0.9))


# ══════════════════════════════════════════════════════════════════
# Title
# ══════════════════════════════════════════════════════════════════

ax.text(8, 10.5, "AI Travel Agent — Supervisor-Driven ReAct Architecture",
        ha="center", va="center", fontsize=16, fontweight="bold", color="#1e293b")

ax.text(8, 10.0, "Course Project | Group 3_11 | Ofek Fuchs & Omri Lazover",
        ha="center", va="center", fontsize=10, color="#64748b")

# ══════════════════════════════════════════════════════════════════
# Layout - Main Components
# ══════════════════════════════════════════════════════════════════

# User
draw_box(0.3, 6.5, 1.8, 1.0, "User", C_USER, "free-form prompt")

# Supervisor (diamond - decision point)
draw_diamond(4.2, 7.0, 0.7, "Supervisor", C_SUPER, "THOUGHT")

# Planner
draw_box(6.5, 6.5, 2.0, 1.0, "Planner", C_PLAN, "PLAN + RAG")

# Executor
draw_box(9.8, 6.5, 2.0, 1.0, "Executor", C_EXEC, "ACTION (parallel)")

# Trip Synthesizer
draw_box(6.5, 4.0, 2.2, 1.0, "Trip Synthesizer", C_SYNTH, "SYNTHESIS")

# Verifier
draw_box(9.8, 4.0, 2.0, 1.0, "Verifier", C_VERIF, "REFLECTION")

# Gate B (budget check)
draw_box(3.5, 4.0, 2.2, 1.0, "Gate B", C_GATE, "budget feasibility")

# ══════════════════════════════════════════════════════════════════
# SharedState (center bottom)
# ══════════════════════════════════════════════════════════════════

draw_box(4.0, 1.5, 6.0, 1.4, "SharedState", C_STATE,
         "constraints, flights, hotels, weather, POIs, RAG chunks, drafts")

# ══════════════════════════════════════════════════════════════════
# Tools Box (right side)
# ══════════════════════════════════════════════════════════════════

draw_box(12.8, 5.5, 2.5, 3.5, "Tools", C_TOOL)
tools = [
    ("Flights API", "Booking.com"),
    ("Hotels API", "Booking.com"),
    ("Weather API", "Open-Meteo"),
    ("POI API", "OpenTripMap"),
]
for i, (t, src) in enumerate(tools):
    ax.text(14.05, 8.5 - i*0.65, t, ha="center", va="center",
            fontsize=8, fontweight="bold", color=C_TOOL)
    ax.text(14.05, 8.25 - i*0.65, f"({src})", ha="center", va="center",
            fontsize=6, color=C_TOOL, alpha=0.7)

# ══════════════════════════════════════════════════════════════════
# RAG Box (far right)
# ══════════════════════════════════════════════════════════════════

draw_box(12.8, 3.8, 2.5, 1.4, "RAG", C_RAG)
ax.text(14.05, 4.7, "Pinecone", ha="center", fontsize=8, fontweight="bold", color=C_RAG)
ax.text(14.05, 4.35, "(Wikivoyage)", ha="center", fontsize=6, color=C_RAG, alpha=0.7)

# ══════════════════════════════════════════════════════════════════
# Database Box (bottom right)
# ══════════════════════════════════════════════════════════════════

draw_box(12.8, 1.5, 2.5, 1.8, "Supabase", C_DB)
ax.text(14.05, 2.8, "Cache", ha="center", fontsize=8, fontweight="bold", color=C_DB)
ax.text(14.05, 2.5, "Trips", ha="center", fontsize=8, fontweight="bold", color=C_DB)
ax.text(14.05, 2.2, "Sessions", ha="center", fontsize=8, fontweight="bold", color=C_DB)
ax.text(14.05, 1.9, "Logs", ha="center", fontsize=8, fontweight="bold", color=C_DB)

# ══════════════════════════════════════════════════════════════════
# LLM Box (top right)
# ══════════════════════════════════════════════════════════════════

draw_box(12.8, 9.2, 2.5, 0.6, "LLM", "#6366f1")
ax.text(14.05, 9.5, "LLMod.ai / GPT-4o", ha="center", fontsize=7, fontweight="bold", color="#6366f1")

# ══════════════════════════════════════════════════════════════════
# Arrows (main flow)
# ══════════════════════════════════════════════════════════════════

# User → Supervisor
arrow(2.1, 7.0, 3.5, 7.0, C_USER, "prompt")

# Supervisor → Planner (plan/replan)
arrow(4.9, 7.0, 6.5, 7.0, C_PLAN, "plan/replan")

# Planner → Executor
arrow(8.5, 7.0, 9.8, 7.0, C_EXEC, "tasks")

# Executor → Tools
arrow(11.8, 7.0, 12.8, 7.2, C_TOOL, "")

# Executor → back to Supervisor (OBSERVATION loop)
arrow(10.8, 7.5, 4.9, 7.5, C_SUPER, "observe results → next decision", curve=0.2)

# Supervisor → Gate B (downward)
arrow(4.2, 6.3, 4.6, 5.0, C_GATE, "", curve=0)

# Gate B → User (infeasible)
arrow(3.5, 4.5, 2.1, 6.5, C_GATE, "infeasible", curve=-0.1)

# Gate B → Synthesize (feasible)
arrow(5.7, 4.5, 6.5, 4.5, C_SYNTH, "feasible", curve=0)

# Supervisor → Synthesize (direct)
arrow(4.2, 6.3, 6.5, 5.0, C_SYNTH, "synthesize", curve=-0.1)

# Synthesizer → Verifier
arrow(8.7, 4.5, 9.8, 4.5, C_VERIF, "audit")

# Verifier → Supervisor (approve/reject)
arrow(10.8, 5.0, 4.9, 6.5, C_SUPER, "approve / reject", curve=-0.15)

# Supervisor → User (response)
arrow(3.5, 6.7, 2.1, 6.7, "#059669", "response", curve=-0.05)

# Planner → RAG
arrow(8.5, 6.7, 12.8, 4.8, C_RAG, "query", curve=-0.1)

# Tools → Supabase (cache)
arrow(13.0, 5.5, 13.0, 3.3, C_DB, "", curve=0)

# LLM connections (dashed)
ax.plot([12.8, 10.8], [9.5, 7.5], color="#6366f1", lw=1, ls="--", alpha=0.4)
ax.plot([12.8, 8.5], [9.5, 7.0], color="#6366f1", lw=1, ls="--", alpha=0.4)
ax.plot([12.8, 8.7], [9.5, 5.0], color="#6366f1", lw=1, ls="--", alpha=0.4)
ax.plot([12.8, 10.8], [9.5, 5.0], color="#6366f1", lw=1, ls="--", alpha=0.4)
ax.plot([12.8, 4.9], [9.5, 7.5], color="#6366f1", lw=1, ls="--", alpha=0.4)

# All agents → SharedState (read/write dashed lines)
for x in [4.2, 7.5, 10.8, 7.6, 10.8, 4.6]:
    ax.plot([x, x], [2.9, 3.8], color="#94a3b8", lw=0.8, ls="--", alpha=0.5)

# ══════════════════════════════════════════════════════════════════
# ReAct Loop annotation
# ══════════════════════════════════════════════════════════════════

loop_box = FancyBboxPatch((2.8, 5.7), 9.5, 2.5,
                           boxstyle="round,pad=0.2",
                           facecolor="none", edgecolor=C_SUPER,
                           linewidth=1.5, linestyle="dashed", alpha=0.4)
ax.add_patch(loop_box)
ax.text(7.5, 8.4, "ReAct Loop (Thought → Action → Observation)",
        ha="center", fontsize=9, fontweight="bold", color=C_SUPER, alpha=0.7,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.9, pad=2))

# ══════════════════════════════════════════════════════════════════
# Legend / Key
# ══════════════════════════════════════════════════════════════════

legend_y = 0.6
ax.text(0.5, legend_y, "Module Names (match API steps):", fontsize=7, fontweight="bold", color="#1e293b")
modules = ["Supervisor", "Planner", "Trip Synthesizer", "Verifier"]
colors = [C_SUPER, C_PLAN, C_SYNTH, C_VERIF]
for i, (mod, col) in enumerate(zip(modules, colors)):
    ax.plot([2.5 + i*2.8, 2.7 + i*2.8], [legend_y, legend_y], color=col, lw=3)
    ax.text(2.8 + i*2.8, legend_y, mod, fontsize=7, color=col, va="center")

# LLM calls annotation
ax.text(0.5, 0.2, "LLM Budget: max 12 calls/request | Typical: 5-7 calls | Executor: 0 LLM (pure API)",
        fontsize=7, color="#64748b")

plt.tight_layout(pad=0.5)

out_path = Path(__file__).resolve().parent.parent / "architecture.png"
plt.savefig(out_path, dpi=150, bbox_inches="tight",
            facecolor="white", edgecolor="none")
print(f"Saved {out_path}")
