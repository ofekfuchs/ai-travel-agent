"""Generate architecture.png — Supervisor-driven ReAct Agent diagram.

Module names match the step labels in the API trace exactly:
  Supervisor, Planner, Executor, Trip Synthesizer, Verifier

Run: python generate_architecture.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(figsize=(14, 9))
ax.set_xlim(0, 14)
ax.set_ylim(0, 9)
ax.set_aspect("equal")
ax.axis("off")
fig.patch.set_facecolor("white")

# Colors
C_SUPER = "#7c3aed"  # purple - thought
C_PLAN  = "#2563eb"  # blue - plan
C_EXEC  = "#059669"  # green - action
C_SYNTH = "#0891b2"  # teal
C_VERIF = "#d97706"  # amber - reflection
C_TOOL  = "#64748b"  # gray
C_STATE = "#e2e8f0"  # light gray
C_USER  = "#1e40af"  # dark blue
C_BG    = "#f8fafc"

def draw_box(x, y, w, h, label, color, sublabel=None, alpha=0.15):
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
            ha="center", va="center", fontsize=10, fontweight="bold", color=color)
    if sublabel:
        ax.text(x + w/2, y + h/2 - 0.18, sublabel,
                ha="center", va="center", fontsize=7, color=color, alpha=0.8)

def draw_diamond(cx, cy, size, label, color):
    pts = [(cx, cy+size), (cx+size, cy), (cx, cy-size), (cx-size, cy)]
    diamond = plt.Polygon(pts, facecolor=color, edgecolor=color, alpha=0.15, linewidth=2)
    ax.add_patch(diamond)
    border = plt.Polygon(pts, facecolor="none", edgecolor=color, linewidth=2)
    ax.add_patch(border)
    ax.text(cx, cy, label, ha="center", va="center", fontsize=9, fontweight="bold", color=color)

def arrow(x1, y1, x2, y2, color="#334155", label="", style="->", lw=1.5, curve=0):
    arrowprops = dict(arrowstyle=style, color=color, lw=lw,
                      connectionstyle=f"arc3,rad={curve}" if curve else "arc3,rad=0")
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=arrowprops)
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        if curve:
            my += 0.2 * (1 if curve > 0 else -1)
        ax.text(mx, my, label, ha="center", va="center", fontsize=7,
                color=color, fontstyle="italic",
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none", alpha=0.9))

# ══════════════════════════════════════════════════════════════════
# Layout
# ══════════════════════════════════════════════════════════════════

# Title
ax.text(7, 8.6, "AI Travel Agent — Supervisor-Driven ReAct Architecture",
        ha="center", va="center", fontsize=14, fontweight="bold", color="#1e293b")

# User
draw_box(0.3, 5.5, 1.6, 0.9, "User", C_USER, "free-form prompt")

# Supervisor (diamond - decision point)
draw_diamond(4.0, 5.95, 0.65, "Supervisor", C_SUPER)
ax.text(4.0, 5.15, "THOUGHT", ha="center", fontsize=7, fontweight="bold",
        color=C_SUPER, alpha=0.7)

# Planner
draw_box(6.2, 5.5, 1.8, 0.9, "Planner", C_PLAN, "PLAN")

# Executor
draw_box(9.2, 5.5, 1.8, 0.9, "Executor", C_EXEC, "ACTION (parallel)")

# Synthesizer
draw_box(6.2, 3.2, 2.2, 0.9, "Trip Synthesizer", C_SYNTH, "SYNTHESIS")

# Verifier
draw_box(9.5, 3.2, 1.8, 0.9, "Verifier", C_VERIF, "REFLECTION")

# SharedState (central)
draw_box(4.8, 1.2, 4.4, 1.2, "SharedState", "#475569",
         "constraints, flights, hotels, weather, POIs, RAG, drafts")

# Tools box
draw_box(11.5, 4.8, 2.0, 3.2, "Tools & Data", C_TOOL)
tools = ["Flights API", "Hotels API", "Weather API", "POI API", "RAG (Pinecone)", "Cache (Supabase)"]
for i, t in enumerate(tools):
    ax.text(12.5, 7.6 - i*0.45, t, ha="center", va="center",
            fontsize=7, color=C_TOOL)

# Gate B
draw_box(3.5, 3.2, 2.0, 0.9, "Gate B", "#dc2626", "budget check")

# ══════════════════════════════════════════════════════════════════
# Arrows (flow)
# ══════════════════════════════════════════════════════════════════

# User → Supervisor
arrow(1.9, 5.95, 3.35, 5.95, C_USER, "prompt")

# Supervisor → Planner (plan/replan)
arrow(4.65, 5.95, 6.2, 5.95, C_PLAN, "plan/replan")

# Planner → Executor
arrow(8.0, 5.95, 9.2, 5.95, C_EXEC, "tasks")

# Executor → Tools
arrow(11.0, 5.95, 11.5, 6.2, C_TOOL, "")

# Executor → back to Supervisor (OBSERVATION loop)
arrow(10.1, 6.4, 4.65, 6.4, C_SUPER, "observe results → next decision", curve=0.25)

# Supervisor → Synthesize (downward)
arrow(4.0, 5.3, 6.2, 3.65, C_SYNTH, "synthesize", curve=-0.15)

# Synthesizer → Verifier
arrow(8.4, 3.65, 9.5, 3.65, C_VERIF, "audit")

# Verifier APPROVE → User (via Supervisor)
arrow(10.4, 4.1, 4.65, 5.5, C_SUPER, "approve / reject → decide", curve=-0.2)

# Supervisor → User (response)
arrow(3.35, 5.7, 1.9, 5.7, "#059669", "response", curve=-0.1)

# Supervisor → Gate B (before synthesize)
arrow(4.0, 5.3, 4.5, 4.1, "#dc2626", "", curve=0)

# Gate B → User (infeasible)
arrow(3.5, 3.65, 1.9, 5.5, "#dc2626", "infeasible", curve=-0.15)

# All agents → SharedState (read/write)
for x in [4.0, 7.1, 10.1, 7.3, 10.4]:
    ax.plot([x, x], [2.4, 3.0], color="#94a3b8", lw=0.8, ls="--", alpha=0.5)

# ReAct Loop annotation
loop_box = FancyBboxPatch((2.8, 4.6), 9.0, 2.5,
                           boxstyle="round,pad=0.2",
                           facecolor="none", edgecolor=C_SUPER,
                           linewidth=1.5, linestyle="dashed", alpha=0.4)
ax.add_patch(loop_box)
ax.text(7.3, 7.25, "ReAct Loop (Thought → Action → Observation)",
        ha="center", fontsize=8, fontweight="bold", color=C_SUPER, alpha=0.6,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.9, pad=2))

# Max rounds annotation
ax.text(2.9, 4.7, "max 6 rounds\n8 LLM calls",
        fontsize=6, color=C_SUPER, alpha=0.5, va="bottom")

plt.tight_layout(pad=0.5)
plt.savefig("architecture.png", dpi=150, bbox_inches="tight",
            facecolor="white", edgecolor="none")
print("Saved architecture.png")
