"""Brief matrix generator for batch ad production.

Produces a combinatorial set of AdBriefs across audience segments,
campaign goals, offers, and tones for systematic pipeline coverage.
"""

from __future__ import annotations

import itertools
import json
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.table import Table

from generate.models import AdBrief, Config

console = Console()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

OFFERS = [
    "Free SAT diagnostic test",
    "1-on-1 expert SAT tutoring",
    "SAT scholarship value calculator",
]

TONES = ["urgent", "empathetic", "confident"]

CAMPAIGN_GOALS = ["awareness", "conversion"]


DEFAULT_SEGMENTS = [
    "athlete_family",
    "suburban_optimizer",
    "immigrant_navigator",
    "cultural_investor",
    "system_optimizer",
    "neurodivergent_advocate",
    "burned_returner",
    "stressed_students",
    "comparison_shoppers",
]


def generate_brief_matrix(config: Config | None = None) -> list[AdBrief]:
    """Create a combinatorial matrix of AdBriefs.

    9 segments x 2 goals x 3 offers x 3 tones = 162 briefs (full matrix).
    If *config* is provided, audience segment IDs are read from it;
    otherwise the nine default segments are used.
    """
    if config is not None:
        segments = [seg.id for seg in config.brand.audience_segments]
    else:
        segments = list(DEFAULT_SEGMENTS)

    briefs = [
        AdBrief(
            audience_segment=seg,
            campaign_goal=goal,  # type: ignore[arg-type]
            specific_offer=offer,
            tone=tone,
        )
        for seg, goal, offer, tone in itertools.product(
            segments, CAMPAIGN_GOALS, OFFERS, TONES,
        )
    ]

    briefs.sort(key=lambda b: (b.audience_segment, b.campaign_goal))
    return briefs


def save_briefs(
    briefs: list[AdBrief],
    path: str | Path = "data/briefs.json",
) -> Path:
    """Serialize briefs to JSON and return the resolved path."""
    out = _PROJECT_ROOT / path
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump([b.model_dump() for b in briefs], f, indent=2)
    return out


def load_briefs(path: str | Path = "data/briefs.json") -> list[AdBrief]:
    """Load a previously saved brief list from JSON."""
    full = _PROJECT_ROOT / path
    with open(full) as f:
        raw = json.load(f)
    return [AdBrief.model_validate(item) for item in raw]


def _print_distribution(briefs: list[AdBrief]) -> None:
    """Print a summary table of the brief distribution."""
    table = Table(title=f"Brief Matrix — {len(briefs)} briefs", show_lines=True)
    table.add_column("Dimension", style="cyan")
    table.add_column("Value", style="white")
    table.add_column("Count", justify="right")

    for label, key in [
        ("Segment", "audience_segment"),
        ("Goal", "campaign_goal"),
        ("Offer", "specific_offer"),
        ("Tone", "tone"),
    ]:
        counts = Counter(getattr(b, key) for b in briefs)
        for value, count in sorted(counts.items()):
            table.add_row(label, str(value), str(count))
            label = ""  # only show the dimension name once per group

    console.print(table)


if __name__ == "__main__":
    from config.loader import get_config

    cfg = get_config()
    matrix = generate_brief_matrix(cfg)
    out_path = save_briefs(matrix)
    _print_distribution(matrix)
    console.print(f"\n[dim]Saved {len(matrix)} briefs to {out_path}[/dim]")
