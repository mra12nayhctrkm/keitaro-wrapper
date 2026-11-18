"""Offer share distribution inside a stream. Pure functions, no I/O."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.services.errors import ValidationError

TOTAL = 100


@dataclass(frozen=True, slots=True)
class Slot:
    active: bool
    pinned: bool
    share: int


def distribute(slots: Sequence[Slot]) -> list[int]:
    """
    Return the share for every slot, in the same order:

    * inactive (removed) offers get 0;
    * pinned active offers keep their share;
    * the rest of 100% is split evenly between unpinned active offers.
      Keitaro shares are integers, so the remainder goes one point each
      to the first offers: 100 / 3 -> 34, 33, 33.

    Raises ValidationError when the pinned shares cannot add up to 100%.
    """
    pinned_total = sum(s.share for s in slots if s.active and s.pinned)
    free = [i for i, s in enumerate(slots) if s.active and not s.pinned]
    budget = TOTAL - pinned_total

    if budget < 0:
        raise ValidationError(f"Pinned shares add up to {pinned_total}%, more than {TOTAL}%.")
    if not free and budget != 0 and any(s.active for s in slots):
        raise ValidationError(
            f"All offers are pinned but add up to {pinned_total}%, not {TOTAL}%. "
            "Unpin an offer or change a pinned share."
        )

    result = [s.share if s.active and s.pinned else 0 for s in slots]
    if free:
        base, extra = divmod(budget, len(free))
        for rank, index in enumerate(free):
            result[index] = base + (1 if rank < extra else 0)
    return result
