from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class OfferState(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


class OfferStatus(StrEnum):
    """What the UI shows for an offer in a stream."""

    ACTIVE = "active"  # in Keitaro, unchanged
    PENDING_ADD = "pending_add"  # will be added on push
    PENDING_REMOVE = "pending_remove"  # will be removed on push
    REMOVED = "removed"  # not in Keitaro, kept in our archive


class Campaign(Base):
    """A Keitaro campaign known to the wrapper. Primary key is the Keitaro ID."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str | None] = mapped_column(String(64))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    streams: Mapped[list[Stream]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="Stream.position",
    )


class Stream(Base):
    """A Keitaro stream (flow). Primary key is the Keitaro ID."""

    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(32))
    schema: Mapped[str | None] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer, default=0)

    campaign: Mapped[Campaign] = relationship(back_populates="streams")
    offers: Mapped[list[StreamOffer]] = relationship(
        back_populates="stream",
        cascade="all, delete-orphan",
        order_by="StreamOffer.id",
    )

    @property
    def has_offers(self) -> bool:
        """Streams that never had offers are shown as-is, without an editor."""
        return self.schema == "landings" or bool(self.offers)

    @property
    def is_dirty(self) -> bool:
        return any(o.is_dirty for o in self.offers)

    @property
    def total_share(self) -> int:
        return sum(o.share for o in self.offers if o.state is OfferState.ACTIVE)


class StreamOffer(Base):
    """
    An offer in a stream: the desired state (`state`, `share`) edited in the UI,
    and the state last seen in Keitaro (`published_*`). The difference between
    the two is the unpublished draft.
    """

    __tablename__ = "stream_offers"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"))
    offer_id: Mapped[int] = mapped_column(Integer)
    offer_name: Mapped[str] = mapped_column(String(255), default="")

    state: Mapped[OfferState] = mapped_column(
        SAEnum(
            OfferState, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e]
        )
    )
    share: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(default=False)

    published_state: Mapped[OfferState | None] = mapped_column(
        SAEnum(
            OfferState, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e]
        )
    )
    published_share: Mapped[int | None] = mapped_column(Integer)
    # Keitaro's own flag for the offer in this stream ("active" / "disabled").
    # Preserved on push so we never silently re-enable a disabled offer.
    kt_state: Mapped[str] = mapped_column(String(16), default="active", server_default="active")

    stream: Mapped[Stream] = relationship(back_populates="offers")

    @property
    def is_dirty(self) -> bool:
        if self.state is not self.published_state:
            # A never-published offer that was removed again is not a change.
            return not (self.published_state is None and self.state is OfferState.REMOVED)
        return self.state is OfferState.ACTIVE and self.share != self.published_share

    @property
    def status(self) -> OfferStatus:
        if self.state is OfferState.ACTIVE:
            if self.published_state is OfferState.ACTIVE:
                return OfferStatus.ACTIVE
            return OfferStatus.PENDING_ADD
        if self.published_state is OfferState.ACTIVE:
            return OfferStatus.PENDING_REMOVE
        return OfferStatus.REMOVED
