"""Small, database-backed aggregates shared by ticketing reporting views."""

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce

from events.models import Event

from .models import Ticket


ZERO_MONEY = Decimal("0.00")
NEEDS_ATTENTION_MAX_OCCUPANCY = Decimal("30")
ON_TRACK_MAX_OCCUPANCY = Decimal("80")
NEAR_CAPACITY_MAX_OCCUPANCY = Decimal("100")


@dataclass(frozen=True)
class RevenueMetrics:
    """Financial totals derived from issued tickets."""

    expected_revenue: Decimal
    collected_revenue: Decimal
    issued_ticket_count: int
    paid_ticket_count: int
    unpaid_ticket_count: int

    @property
    def outstanding_revenue(self):
        return self.expected_revenue - self.collected_revenue

    @property
    def collection_percentage(self):
        if self.expected_revenue == ZERO_MONEY:
            return ZERO_MONEY
        return self.collected_revenue / self.expected_revenue * Decimal("100")


def get_revenue_metrics(tickets=None):
    """Return decimal-safe revenue and payment counts for a ticket queryset.

    The default queryset represents all issued tickets, which is the reporting
    scope used by both the dashboard and tracker.
    """

    tickets = Ticket.objects.all() if tickets is None else tickets
    money_field = DecimalField(max_digits=10, decimal_places=2)
    totals = tickets.aggregate(
        expected_revenue=Coalesce(
            Sum("price"), Value(ZERO_MONEY, output_field=money_field)
        ),
        collected_revenue=Coalesce(
            Sum("price", filter=Q(status=Ticket.Status.PAID)),
            Value(ZERO_MONEY, output_field=money_field),
        ),
        issued_ticket_count=Count("pk"),
        paid_ticket_count=Count("pk", filter=Q(status=Ticket.Status.PAID)),
        unpaid_ticket_count=Count("pk", filter=Q(status=Ticket.Status.UNPAID)),
    )
    return RevenueMetrics(**totals)


@dataclass(frozen=True)
class EventPerformance:
    """Presentation-ready, occupancy-based metrics for one persisted event.

    Health status uses only unrounded occupancy: below 30% is Needs Attention,
    30% to below 80% is On Track, 80% to below 100% is Near Capacity, and
    exactly 100% is Full. It is a current operational classification, not a
    prediction and does not incorporate payment or schedule data.
    """

    event: Event

    @property
    def ticket_count(self):
        return self.event.ticket_count

    @property
    def capacity(self):
        return self.event.venue.capacity

    @property
    def remaining_seats(self):
        return max(self.capacity - self.ticket_count, 0)

    @property
    def occupancy_percentage(self):
        if not self.capacity:
            return Decimal("0")
        return Decimal(self.ticket_count) / Decimal(self.capacity) * Decimal("100")

    @property
    def expected_revenue(self):
        return self.event.expected_revenue

    @property
    def collected_revenue(self):
        return self.event.collected_revenue

    @property
    def outstanding_revenue(self):
        return self.expected_revenue - self.collected_revenue

    @property
    def collection_percentage(self):
        if self.expected_revenue == ZERO_MONEY:
            return ZERO_MONEY
        return self.collected_revenue / self.expected_revenue * Decimal("100")

    @property
    def health_status(self):
        occupancy = self.occupancy_percentage
        if occupancy < NEEDS_ATTENTION_MAX_OCCUPANCY:
            return "Needs Attention"
        if occupancy < ON_TRACK_MAX_OCCUPANCY:
            return "On Track"
        if occupancy < NEAR_CAPACITY_MAX_OCCUPANCY:
            return "Near Capacity"
        return "Full"


def get_event_performance(events=None):
    """Return event performance with ticket and revenue aggregates in one query.

    ``events`` may narrow the persisted event queryset for a reporting scope.
    """

    money_field = DecimalField(max_digits=10, decimal_places=2)
    events = Event.objects.all() if events is None else events
    events = events.select_related("venue").annotate(
        ticket_count=Count("tickets"),
        expected_revenue=Coalesce(
            Sum("tickets__price"), Value(ZERO_MONEY, output_field=money_field)
        ),
        collected_revenue=Coalesce(
            Sum("tickets__price", filter=Q(tickets__status=Ticket.Status.PAID)),
            Value(ZERO_MONEY, output_field=money_field),
        ),
    )
    return [EventPerformance(event) for event in events]
