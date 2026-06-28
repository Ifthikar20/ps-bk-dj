"""Static rank config — mirrors kRanks in the Flutter app exactly."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Rank:
    name: str
    emoji: str
    threshold: int


# `emoji` is kept (blank) so the API shape is unchanged; clients render ranks
# with their own iconography rather than emoji.
RANKS = [
    Rank("Novice", "", 0),
    Rank("Explorer", "", 100),
    Rank("Scholar", "", 300),
    Rank("Strategist", "", 600),
    Rank("Sage", "", 1000),
    Rank("Master", "", 1500),
    Rank("Legend", "", 2200),
]


def rank_for(points: int):
    """Return (current_rank, next_rank_or_None) for a point total."""
    current = RANKS[0]
    nxt = None
    for i, rank in enumerate(RANKS):
        if points >= rank.threshold:
            current = rank
            nxt = RANKS[i + 1] if i + 1 < len(RANKS) else None
    return current, nxt


def rank_progress(points: int):
    current, nxt = rank_for(points)
    if nxt is None:
        return 1.0, 0
    span = nxt.threshold - current.threshold
    gained = points - current.threshold
    progress = gained / span if span else 1.0
    return round(progress, 4), nxt.threshold - points
