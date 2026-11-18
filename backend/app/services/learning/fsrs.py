"""FSRS-4.5, as pure functions (no database, no clock). Formulas: docs/LEARNING.md 2.1.

A card has stability S (days until recall probability falls to 90%) and difficulty
D (1-10). Ratings: 1 forgot, 2 hard, 3 good, 4 easy.
"""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

W = (0.4072, 1.1829, 3.1262, 15.4722, 7.2102, 0.5316, 1.0651, 0.0234, 1.616, 0.1544, 1.0824,
     1.9813, 0.0953, 0.2975, 2.2042, 0.2407, 2.9466)
DECAY = -0.5
FACTOR = 19 / 81
MIN_INTERVAL, MAX_INTERVAL = 1, 365
RELEARN_MINUTES = 10
DEFAULT_RETENTION = 0.90


def clamp_difficulty(value: float) -> float:
    return min(10.0, max(1.0, value))


def retrievability(elapsed_days: float, stability: float) -> float:
    """R(t, S) = (1 + 19/81 * t / S) ^ -0.5"""
    return (1 + FACTOR * max(0.0, elapsed_days) / stability) ** DECAY


def interval(stability: float, retention: float = DEFAULT_RETENTION) -> int:
    """I = S * 81/19 * (r^-2 - 1), rounded, 1..365 days."""
    days = stability / FACTOR * (retention ** (1 / DECAY) - 1)
    return int(min(MAX_INTERVAL, max(MIN_INTERVAL, round(days))))


def init_stability(rating: int) -> float:
    return W[rating - 1]


def init_difficulty(rating: int) -> float:
    return clamp_difficulty(W[4] - (rating - 3) * W[5])


def next_difficulty(difficulty: float, rating: int) -> float:
    return clamp_difficulty(W[7] * W[4] + (1 - W[7]) * (difficulty - W[6] * (rating - 3)))


def recall_stability(difficulty: float, stability: float, r: float, rating: int) -> float:
    hard = W[15] if rating == 2 else 1.0
    easy = W[16] if rating == 4 else 1.0
    return stability * (1 + math.exp(W[8]) * (11 - difficulty) * stability ** (-W[9])
                        * (math.exp(W[10] * (1 - r)) - 1) * hard * easy)


def forget_stability(difficulty: float, stability: float, r: float) -> float:
    return min(stability, W[11] * difficulty ** (-W[12]) * ((stability + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r)))


@dataclass(frozen=True)
class Outcome:
    state: str              # learning / review / relearning
    stability: float
    difficulty: float
    due_at: datetime
    interval_days: int      # 0 = again within this session
    again_in_session: bool
    retrievability: float | None
    elapsed_days: float | None


def review(card: dict, rating: int, now: datetime, retention: float = DEFAULT_RETENTION,
           weight: float = 1.0) -> Outcome:
    """Next state of a card after one rating.

    card: {state, stability, difficulty, last_review_at (datetime | None)}.
    weight < 1 shrinks the stability gain (weaker evidence, e.g. a word used in chat).
    A card forgotten earlier today (learning / relearning) comes back after 10 minutes;
    getting it right again today does not change its stability.
    """
    if rating not in (1, 2, 3, 4):
        raise ValueError("rating must be 1-4")
    state = card.get("state") or "new"
    last = card.get("last_review_at")
    if state == "new" or card.get("stability") is None:
        s, d = init_stability(rating), init_difficulty(rating)
        r = elapsed = None
    else:
        s, d = float(card["stability"]), float(card["difficulty"])
        elapsed = max(0.0, (now - last).total_seconds() / 86400) if last else 0.0
        r = retrievability(elapsed, s)
        same_day_step = state in ("learning", "relearning") and last is not None and last.date() == now.date()
        if same_day_step:
            if rating == 1:
                return Outcome(state, s, d, now + timedelta(minutes=RELEARN_MINUTES), 0, True, r, elapsed)
            days = interval(s, retention)
            return Outcome("review", s, d, now + timedelta(days=days), days, False, r, elapsed)
        new_d = next_difficulty(d, rating)
        if rating == 1:
            s = forget_stability(d, s, r)
        else:
            grown = recall_stability(d, s, r, rating)
            s = s + (grown - s) * weight
        d = new_d
    if rating == 1:
        return Outcome("relearning" if state != "new" else "learning", s, d,
                       now + timedelta(minutes=RELEARN_MINUTES), 0, True, r, elapsed)
    days = interval(s, retention)
    return Outcome("review", s, d, now + timedelta(days=days), days, False, r, elapsed)


def preview(card: dict, now: datetime, retention: float = DEFAULT_RETENTION) -> dict[int, int]:
    """Interval in days for each rating (0 = 10 minutes), for the rating buttons."""
    return {rating: review(card, rating, now, retention).interval_days for rating in (1, 2, 3, 4)}
