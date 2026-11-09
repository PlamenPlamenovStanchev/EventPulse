from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse

from attendees.models import Attendee
from events.models import Event, Venue

from .models import Ticket


class InterfaceFoundationTests(TestCase):
    navigation_routes = (
        'ticketing:dashboard',
        'events:event_list',
        'attendees:attendee_list',
        'events:venue_list',
        'ticketing:ticket_list',
        'ticketing:tracker',
        'ticketing:insights',
    )

    def test_dashboard_returns_success(self):
        response = self.client.get(reverse('ticketing:dashboard'))

        self.assertEqual(response.status_code, 200)

    def test_every_navigation_destination_returns_success(self):
        for route_name in self.navigation_routes:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)

    def test_shared_navigation_and_footer_appear_on_every_destination(self):
        for route_name in self.navigation_routes:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertContains(response, 'Primary navigation')
                self.assertContains(response, 'Built for clearer operations.')

    def test_homepage_contains_eventpulse_identity(self):
        response = self.client.get(reverse('ticketing:dashboard'))

        self.assertContains(response, 'Welcome to EventPulse')
        self.assertContains(response, 'Every event. Every attendee. Every insight.')

    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
    def test_custom_404_handler_renders_when_debug_is_disabled(self):
        response = self.client.get('/not-a-real-route/')

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'This route is not on the event plan.', status_code=404)


class TicketModelTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(
            name="Riverside Hall", address="1 Main Street", capacity=2
        )
        self.event = Event.objects.create(
            name="Autumn Conference",
            starts_at="2026-11-10T09:00:00Z",
            description="A one-day conference.",
            venue=self.venue,
        )
        self.attendee = self.create_attendee("Alex", "alex@example.com")

    def create_attendee(self, name, email):
        return Attendee.objects.create(name=name, email=email, phone="555-0100")

    def create_ticket(self, **overrides):
        defaults = {
            "event": self.event,
            "attendee": self.attendee,
            "price": Decimal("25.00"),
        }
        defaults.update(overrides)
        return Ticket.objects.create(**defaults)

    def test_event_and_attendee_are_connected_through_tickets(self):
        ticket = self.create_ticket()

        self.assertEqual(self.event.attendees.get(), self.attendee)
        self.assertEqual(self.attendee.events.get(), self.event)
        self.assertEqual(self.event.tickets.get(), ticket)

    def test_unique_event_attendee_pair_is_enforced_by_model_and_database(self):
        self.create_ticket()
        duplicate = Ticket(
            event=self.event, attendee=self.attendee, price=Decimal("25.00")
        )

        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        with self.assertRaises(IntegrityError):
            Ticket.objects.bulk_create([duplicate])

    def test_paid_ticket_requires_payment_details(self):
        ticket = Ticket(
            event=self.event,
            attendee=self.attendee,
            price=Decimal("25.00"),
            status=Ticket.Status.PAID,
        )

        with self.assertRaises(ValidationError) as context:
            ticket.full_clean()

        self.assertIn("payment_date", context.exception.message_dict)
        self.assertIn("payment_method", context.exception.message_dict)

    def test_unpaid_ticket_rejects_payment_details(self):
        ticket = Ticket(
            event=self.event,
            attendee=self.attendee,
            price=Decimal("25.00"),
            payment_date=date(2026, 11, 1),
            payment_method=Ticket.PaymentMethod.CARD,
        )

        with self.assertRaises(ValidationError) as context:
            ticket.full_clean()

        self.assertIn("__all__", context.exception.message_dict)

    def test_price_cannot_be_negative(self):
        ticket = Ticket(
            event=self.event,
            attendee=self.attendee,
            price=Decimal("-0.01"),
        )

        with self.assertRaises(ValidationError) as context:
            ticket.full_clean()

        self.assertIn("price", context.exception.message_dict)

    def test_full_capacity_rejects_ticket_regardless_of_payment_status(self):
        self.venue.capacity = 1
        self.venue.save()
        self.create_ticket()
        attendee = self.create_attendee("Blake", "blake@example.com")

        with self.assertRaises(ValidationError):
            self.create_ticket(attendee=attendee, status=Ticket.Status.PAID,
                               payment_date=date(2026, 11, 1),
                               payment_method=Ticket.PaymentMethod.CARD)

    def test_capacity_boundary_allows_exactly_the_venue_capacity(self):
        self.create_ticket()
        self.create_ticket(
            attendee=self.create_attendee("Blake", "blake@example.com")
        )

        self.assertEqual(self.event.tickets.count(), self.venue.capacity)

    def test_ticket_reassignment_validates_destination_capacity(self):
        ticket = self.create_ticket()
        destination = Event.objects.create(
            name="Winter Conference",
            starts_at="2026-12-10T09:00:00Z",
            description="A one-day conference.",
            venue=Venue.objects.create(
                name="Small Hall", address="2 Main Street", capacity=1
            ),
        )
        occupied_destination = Ticket.objects.create(
            event=destination,
            attendee=self.create_attendee("Blake", "blake@example.com"),
            price=Decimal("25.00"),
        )

        ticket.event = destination
        with self.assertRaises(ValidationError):
            ticket.save()

        ticket.refresh_from_db()
        self.assertEqual(ticket.event, self.event)
        self.assertEqual(occupied_destination.event, destination)

    def test_ticket_can_move_to_event_with_available_capacity(self):
        ticket = self.create_ticket()
        destination = Event.objects.create(
            name="Winter Conference",
            starts_at="2026-12-10T09:00:00Z",
            description="A one-day conference.",
            venue=Venue.objects.create(
                name="Second Hall", address="2 Main Street", capacity=1
            ),
        )

        ticket.event = destination
        ticket.save()

        self.assertEqual(ticket.event, destination)

    def test_updating_ticket_without_changing_event_does_not_double_count(self):
        self.venue.capacity = 1
        self.venue.save()
        ticket = self.create_ticket()

        ticket.price = Decimal("30.00")
        ticket.save()

        self.assertEqual(Ticket.objects.get(pk=ticket.pk).price, Decimal("30.00"))

    def test_venue_capacity_cannot_be_reduced_below_issued_tickets(self):
        self.create_ticket()
        self.create_ticket(
            attendee=self.create_attendee("Blake", "blake@example.com")
        )
        self.venue.capacity = 1

        with self.assertRaises(ValidationError):
            self.venue.save()

    def test_event_cannot_move_to_venue_too_small_for_issued_tickets(self):
        self.create_ticket()
        self.create_ticket(
            attendee=self.create_attendee("Blake", "blake@example.com")
        )
        smaller_venue = Venue.objects.create(
            name="Small Hall", address="2 Main Street", capacity=1
        )
        self.event.venue = smaller_venue

        with self.assertRaises(ValidationError):
            self.event.save()

    def test_ticket_relationship_deletions_cascade_and_protect(self):
        ticket = self.create_ticket()

        with self.assertRaises(ProtectedError):
            self.attendee.delete()

        self.event.delete()

        self.assertFalse(Ticket.objects.filter(pk=ticket.pk).exists())
        self.assertTrue(Attendee.objects.filter(pk=self.attendee.pk).exists())
        self.assertTrue(Venue.objects.filter(pk=self.venue.pk).exists())


class DomainEmptyDatabaseTests(TestCase):
    def test_domain_models_do_not_require_or_create_seed_data(self):
        self.assertEqual(Venue.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(Attendee.objects.count(), 0)
        self.assertEqual(Ticket.objects.count(), 0)
