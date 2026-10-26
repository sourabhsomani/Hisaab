"""Split engine: every split resolves to exact paise per member that sum to the total.

Functions are pure and keyed by any hashable member key (usually a member id). Dict order
is the member order, which decides who receives leftover paise.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from fractions import Fraction
from typing import TypeVar

from hisaab.core.models import SplitType

K = TypeVar("K", bound=Hashable)


class SplitError(ValueError):
    """Raised when split inputs cannot produce a valid split."""


def _check_total(total_paise: int) -> None:
    if not isinstance(total_paise, int) or isinstance(total_paise, bool):
        raise SplitError("total must be an integer number of paise")
    if total_paise <= 0:
        raise SplitError("total must be positive")


def largest_remainder(total_paise: int, weights: Mapping[K, float | int | str]) -> dict[K, int]:
    """Distribute ``total_paise`` proportionally to ``weights`` using the largest-remainder method.

    Leftover paise go to the largest fractional parts; ties go to the earlier member.
    """
    if not weights:
        raise SplitError("no participants")
    fracs = {k: Fraction(str(w)) for k, w in weights.items()}
    if any(f < 0 for f in fracs.values()):
        raise SplitError("weights cannot be negative")
    weight_sum = sum(fracs.values())
    if weight_sum == 0:
        raise SplitError("weights sum to zero")
    exact = {k: total_paise * f / weight_sum for k, f in fracs.items()}
    result = {k: int(v.numerator // v.denominator) for k, v in exact.items()}
    leftover = total_paise - sum(result.values())
    order = list(weights)
    ranked = sorted(order, key=lambda k: (-(exact[k] - result[k]), order.index(k)))
    for k in ranked[:leftover]:
        result[k] += 1
    return result


def split_equal(total_paise: int, members: Sequence[K]) -> dict[K, int]:
    """``total ÷ n``; leftover paise go to the first members in order."""
    _check_total(total_paise)
    if not members:
        raise SplitError("no participants")
    if len(set(members)) != len(members):
        raise SplitError("duplicate participants")
    base, extra = divmod(total_paise, len(members))
    return {m: base + (1 if i < extra else 0) for i, m in enumerate(members)}


def split_exact(total_paise: int, amounts: Mapping[K, int]) -> dict[K, int]:
    """Exact paise per member; must sum to the total."""
    _check_total(total_paise)
    if not amounts:
        raise SplitError("no participants")
    if any(a < 0 for a in amounts.values()):
        raise SplitError("amounts cannot be negative")
    if sum(amounts.values()) != total_paise:
        raise SplitError(
            f"exact amounts sum to {sum(amounts.values())} paise, expected {total_paise}"
        )
    return dict(amounts)


def split_percentage(total_paise: int, percents: Mapping[K, float | int | str]) -> dict[K, int]:
    """Percent per member; must sum to 100 (within 0.01). Largest-remainder rounding."""
    _check_total(total_paise)
    if not percents:
        raise SplitError("no participants")
    pct_sum = sum(Fraction(str(p)) for p in percents.values())
    if abs(pct_sum - 100) > Fraction(1, 100):
        raise SplitError(f"percentages sum to {float(pct_sum):g}, expected 100")
    return largest_remainder(total_paise, percents)


def split_shares(total_paise: int, shares: Mapping[K, float | int | str]) -> dict[K, int]:
    """Share counts such as 2:1:1. Proportional with largest-remainder rounding."""
    _check_total(total_paise)
    return largest_remainder(total_paise, shares)


def split_adjustment(
    total_paise: int, members: Sequence[K], adjustments: Mapping[K, int]
) -> dict[K, int]:
    """Equal split of what remains after per-member ± paise adjustments ("extra drink")."""
    _check_total(total_paise)
    unknown = set(adjustments) - set(members)
    if unknown:
        raise SplitError(f"adjustments for non-participants: {sorted(map(str, unknown))}")
    adj_sum = sum(adjustments.values())
    remainder = total_paise - adj_sum
    if remainder < 0:
        raise SplitError("adjustments exceed the total")
    base = split_equal(remainder, members) if remainder else dict.fromkeys(members, 0)
    result = {m: base[m] + adjustments.get(m, 0) for m in members}
    if any(v < 0 for v in result.values()):
        raise SplitError("an adjustment makes a share negative")
    return result


def compute_split(
    split_type: SplitType | str,
    total_paise: int,
    participants: Sequence[K],
    values: Mapping[K, float | int | str] | None = None,
) -> dict[K, int]:
    """Dispatch to the right split function.

    ``values`` means: exact paise (exact), percent (percentage), share count (shares) or
    ± paise (adjustment). It is ignored for equal splits.
    """
    kind = SplitType(split_type)
    values = values or {}
    if kind is SplitType.EQUAL:
        return split_equal(total_paise, participants)
    picked = {p: values.get(p, 0) for p in participants}
    if kind is SplitType.EXACT:
        return split_exact(total_paise, {k: int(v) for k, v in picked.items()})
    if kind is SplitType.PERCENTAGE:
        return split_percentage(total_paise, picked)
    if kind is SplitType.SHARES:
        return split_shares(total_paise, picked)
    return split_adjustment(
        total_paise, participants, {k: int(v) for k, v in picked.items() if v}
    )
