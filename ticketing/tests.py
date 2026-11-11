from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse

from attendees.models import Attendee
from events.models import Event, Venue

from .forms import TicketForm
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
            ticket.save()

        self.assertIn("price", context.exception.message_dict)
        self.assertFalse(Ticket.objects.exists())

    def test_save_rejects_duplicate_attendee_event_pair(self):
        self.create_ticket()
        duplicate = Ticket(
            event=self.event,
            attendee=self.attendee,
            price=Decimal("25.00"),
        )

        with self.assertRaises(ValidationError):
            duplicate.save()

        self.assertEqual(Ticket.objects.count(), 1)

    def test_save_rejects_inconsistent_payment_metadata(self):
        ticket = Ticket(
            event=self.event,
            attendee=self.attendee,
            price=Decimal("25.00"),
            status=Ticket.Status.PAID,
        )

        with self.assertRaises(ValidationError) as context:
            ticket.save()

        self.assertIn("payment_date", context.exception.message_dict)
        self.assertIn("payment_method", context.exception.message_dict)
        self.assertFalse(Ticket.objects.exists())

    def test_database_check_constraint_rejects_negative_price_when_validation_is_bypassed(self):
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Ticket.objects.bulk_create(
                    [
                        Ticket(
                            event=self.event,
                            attendee=self.attendee,
                            price=Decimal("-0.01"),
                        )
                    ]
                )

        self.assertFalse(Ticket.objects.exists())

    def test_database_check_constraint_rejects_inconsistent_payment_metadata_when_validation_is_bypassed(self):
        invalid_tickets = (
            {
                "status": Ticket.Status.PAID,
                "payment_date": None,
                "payment_method": None,
            },
            {
                "status": Ticket.Status.UNPAID,
                "payment_date": date(2026, 11, 1),
                "payment_method": Ticket.PaymentMethod.CARD,
            },
        )

        for index, invalid_values in enumerate(invalid_tickets):
            with self.subTest(invalid_values=invalid_values):
                attendee = self.create_attendee(
                    f"Invalid {index}", f"invalid-{index}@example.com"
                )
                with transaction.atomic():
                    with self.assertRaises(IntegrityError):
                        Ticket.objects.bulk_create(
                            [
                                Ticket(
                                    event=self.event,
                                    attendee=attendee,
                                    price=Decimal("25.00"),
                                    **invalid_values,
                                )
                            ]
                        )

        self.assertFalse(Ticket.objects.exists())

    def test_full_capacity_rejects_ticket_regardless_of_payment_status(self):
        self.venue.capacity = 1
        self.venue.save()
        self.create_ticket()
        attendee = self.create_attendee("Blake", "blake@example.com")

        ticket = Ticket(
            event=self.event,
            attendee=attendee,
            price=Decimal("25.00"),
            status=Ticket.Status.PAID,
            payment_date=date(2026, 11, 1),
            payment_method=Ticket.PaymentMethod.CARD,
        )
        with self.assertRaises(ValidationError):
            ticket.save()

        self.assertEqual(self.event.tickets.count(), 1)

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

    def test_failed_ticket_update_does_not_partially_persist_changes(self):
        ticket = self.create_ticket()
        destination = Event.objects.create(
            name="Full Destination",
            starts_at="2026-12-10T09:00:00Z",
            description="A one-day conference.",
            venue=Venue.objects.create(
                name="Full Hall", address="2 Main Street", capacity=1
            ),
        )
        Ticket.objects.create(
            event=destination,
            attendee=self.create_attendee("Blake", "blake@example.com"),
            price=Decimal("25.00"),
        )

        ticket.event = destination
        ticket.price = Decimal("30.00")
        with self.assertRaises(ValidationError):
            ticket.save()

        ticket.refresh_from_db()
        self.assertEqual(ticket.event, self.event)
        self.assertEqual(ticket.price, Decimal("25.00"))

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


class TicketFormTests(TestCase):
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
        values = {
            "event": self.event,
            "attendee": self.attendee,
            "price": Decimal("25.00"),
        }
        values.update(overrides)
        return Ticket.objects.create(**values)

    def form_data(self, **overrides):
        values = {
            "event": self.event.pk,
            "attendee": self.attendee.pk,
            "price": "25.00",
            "status": Ticket.Status.UNPAID,
            "payment_date": "",
            "payment_method": "",
        }
        values.update(overrides)
        return values

    def test_valid_form_creates_ticket_with_readable_choices(self):
        form = TicketForm(data=self.form_data())

        self.assertTrue(form.is_valid())
        ticket = form.save()
        self.assertEqual(ticket.event, self.event)
        self.assertEqual(ticket.attendee, self.attendee)
        self.assertEqual(ticket.price, Decimal("25.00"))
        self.assertEqual(
            form.fields["event"].label_from_instance(self.event),
            "Autumn Conference — Riverside Hall (2 places)",
        )
        self.assertEqual(
            form.fields["attendee"].label_from_instance(self.attendee),
            "Alex (alex@example.com)",
        )

    def test_editing_existing_ticket_is_valid_without_double_counting(self):
        self.venue.capacity = 1
        self.venue.save()
        ticket = self.create_ticket()

        form = TicketForm(
            data=self.form_data(price="30.00"), instance=ticket
        )

        self.assertTrue(form.is_valid())
        updated_ticket = form.save()
        self.assertEqual(updated_ticket.price, Decimal("30.00"))

    def test_negative_price_is_rejected(self):
        form = TicketForm(data=self.form_data(price="-0.01"))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["price"], ["Ticket price cannot be negative."])
        self.assertFalse(Ticket.objects.exists())

    def test_zero_price_ticket_is_valid(self):
        form = TicketForm(data=self.form_data(price="0.00"))

        self.assertTrue(form.is_valid())
        self.assertEqual(form.save().price, Decimal("0.00"))

    def test_duplicate_attendee_event_combination_is_a_non_field_error(self):
        self.create_ticket()
        form = TicketForm(data=self.form_data())

        self.assertFalse(form.is_valid())
        self.assertIn(
            "This attendee already has a ticket for the selected event.",
            form.non_field_errors(),
        )
        self.assertEqual(Ticket.objects.count(), 1)

    def test_full_capacity_event_is_rejected_without_persisting(self):
        self.venue.capacity = 1
        self.venue.save()
        self.create_ticket()
        attendee = self.create_attendee("Blake", "blake@example.com")
        form = TicketForm(data=self.form_data(attendee=attendee.pk))

        self.assertFalse(form.is_valid())
        self.assertFormError(
            form, "event", "This event's venue is already at full capacity."
        )
        self.assertEqual(Ticket.objects.count(), 1)

    def test_event_reassignment_respects_destination_capacity(self):
        ticket = self.create_ticket()
        destination = Event.objects.create(
            name="Winter Conference",
            starts_at="2026-12-10T09:00:00Z",
            description="A one-day conference.",
            venue=Venue.objects.create(
                name="Second Hall", address="2 Main Street", capacity=1
            ),
        )
        form = TicketForm(
            data=self.form_data(event=destination.pk), instance=ticket
        )

        self.assertTrue(form.is_valid())
        self.assertEqual(form.save().event, destination)

    def test_reassignment_to_full_event_does_not_persist_partial_changes(self):
        ticket = self.create_ticket()
        destination = Event.objects.create(
            name="Full Conference",
            starts_at="2026-12-10T09:00:00Z",
            description="A one-day conference.",
            venue=Venue.objects.create(
                name="Full Hall", address="2 Main Street", capacity=1
            ),
        )
        Ticket.objects.create(
            event=destination,
            attendee=self.create_attendee("Blake", "blake@example.com"),
            price=Decimal("25.00"),
        )
        form = TicketForm(
            data=self.form_data(event=destination.pk, price="30.00"),
            instance=ticket,
        )

        self.assertFalse(form.is_valid())
        self.assertFormError(
            form, "event", "This event's venue is already at full capacity."
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.event, self.event)
        self.assertEqual(ticket.price, Decimal("25.00"))

    def test_paid_ticket_requires_both_payment_details(self):
        missing_date = TicketForm(
            data=self.form_data(
                status=Ticket.Status.PAID,
                payment_method=Ticket.PaymentMethod.CARD,
            )
        )
        missing_method = TicketForm(
            data=self.form_data(
                status=Ticket.Status.PAID,
                payment_date="2026-11-01",
            )
        )

        self.assertFalse(missing_date.is_valid())
        self.assertEqual(
            missing_date.errors["payment_date"],
            ["Paid tickets require a payment date."],
        )
        self.assertFalse(missing_method.is_valid())
        self.assertEqual(
            missing_method.errors["payment_method"],
            ["Paid tickets require a payment method."],
        )

    def test_unpaid_ticket_rejects_payment_metadata(self):
        form = TicketForm(
            data=self.form_data(
                payment_date="2026-11-01",
                payment_method=Ticket.PaymentMethod.CARD,
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Unpaid tickets cannot have payment date or payment method details.",
            form.non_field_errors(),
        )

    def test_form_excludes_created_at_and_has_clear_field_metadata(self):
        form = TicketForm()

        self.assertEqual(
            list(form.fields),
            ["event", "attendee", "price", "status", "payment_date", "payment_method"],
        )
        self.assertNotIn("created_at", form.fields)
        self.assertEqual(form.fields["price"].label, "Ticket price")
        self.assertEqual(form.fields["price"].widget.attrs["step"], "0.01")
        self.assertEqual(form.fields["payment_date"].widget.input_type, "date")
        self.assertIn("complimentary", form.fields["price"].help_text)


class DomainEmptyDatabaseTests(TestCase):
    def test_domain_models_do_not_require_or_create_seed_data(self):
        self.assertEqual(Venue.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(Attendee.objects.count(), 0)
        self.assertEqual(Ticket.objects.count(), 0)
