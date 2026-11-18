import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.services.errors import ValidationError
from app.services.weights import Slot, distribute


def free(n: int) -> list[Slot]:
    return [Slot(active=True, pinned=False, share=0) for _ in range(n)]


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, [100]),
        (2, [50, 50]),
        (3, [34, 33, 33]),  # remainder goes to the first offers
        (4, [25, 25, 25, 25]),
        (6, [17, 17, 17, 17, 16, 16]),
    ],
)
def test_even_split(count: int, expected: list[int]) -> None:
    assert distribute(free(count)) == expected


def test_removed_offers_get_zero_and_do_not_take_a_share() -> None:
    slots = [Slot(True, False, 0), Slot(False, False, 40), Slot(True, False, 0)]
    assert distribute(slots) == [50, 0, 50]


def test_pinned_share_is_kept_and_the_rest_is_split() -> None:
    # The video: pinned 25%, two others become 38% and 37%.
    slots = [Slot(True, False, 0), Slot(True, False, 0), Slot(True, True, 25)]
    assert distribute(slots) == [38, 37, 25]


def test_removed_pinned_offer_is_ignored() -> None:
    slots = [Slot(False, True, 25), Slot(True, False, 0), Slot(True, False, 0)]
    assert distribute(slots) == [0, 50, 50]


def test_empty_and_all_removed() -> None:
    assert distribute([]) == []
    assert distribute([Slot(False, False, 10)]) == [0]


def test_pinned_over_100_is_rejected() -> None:
    with pytest.raises(ValidationError, match="more than 100"):
        distribute([Slot(True, True, 70), Slot(True, True, 40), Slot(True, False, 0)])


def test_all_pinned_must_add_up_to_100() -> None:
    assert distribute([Slot(True, True, 60), Slot(True, True, 40)]) == [60, 40]
    with pytest.raises(ValidationError, match="All offers are pinned"):
        distribute([Slot(True, True, 60), Slot(True, True, 30)])


slots_strategy = st.lists(
    st.builds(
        Slot,
        active=st.booleans(),
        pinned=st.booleans(),
        share=st.integers(min_value=0, max_value=100),
    ),
    max_size=12,
)


@given(slots_strategy)
def test_properties(slots: list[Slot]) -> None:
    try:
        shares = distribute(slots)
    except ValidationError:
        return
    active = [s for s in slots if s.active]
    if active:
        assert sum(shares) == 100
    for slot, share in zip(slots, shares, strict=True):
        if not slot.active:
            assert share == 0
        elif slot.pinned:
            assert share == slot.share
    free_shares = [sh for s, sh in zip(slots, shares, strict=True) if s.active and not s.pinned]
    if free_shares:
        assert max(free_shares) - min(free_shares) <= 1
        assert free_shares == sorted(free_shares, reverse=True)
