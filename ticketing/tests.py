from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from attendees.models import Attendee
from events.models import Event, Venue

from .analytics import get_event_performance
from .forms import PaymentForm, TicketForm
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


class PaymentFormTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(
            name="Payment Hall", address="3 Payment Street", capacity=2
        )
        self.event = Event.objects.create(
            name="Payment Workshop",
            starts_at="2026-12-10T09:00:00Z",
            description="An event used to verify payment recording.",
            venue=self.venue,
        )
        self.attendee = Attendee.objects.create(
            name="Payton", email="payton@example.com", phone="555-0110"
        )

    def create_ticket(self, **overrides):
        values = {"event": self.event, "attendee": self.attendee, "price": Decimal("25.00")}
        values.update(overrides)
        return Ticket.objects.create(**values)

    def payment_data(self, **overrides):
        values = {
            "payment_date": "2026-12-01",
            "payment_method": Ticket.PaymentMethod.CARD,
        }
        values.update(overrides)
        return values

    def test_valid_payment_details_are_valid_without_persisting(self):
        ticket = self.create_ticket()
        ticket.status = Ticket.Status.PAID
        form = PaymentForm(data=self.payment_data(), instance=ticket)

        self.assertTrue(form.is_valid())
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.UNPAID)
        self.assertIsNone(ticket.payment_date)
        self.assertIsNone(ticket.payment_method)

    def test_paid_ticket_requires_payment_date(self):
        ticket = self.create_ticket()
        ticket.status = Ticket.Status.PAID
        form = PaymentForm(data=self.payment_data(payment_date=""), instance=ticket)

        self.assertFalse(form.is_valid())
        self.assertFormError(form, "payment_date", "Paid tickets require a payment date.")

    def test_paid_ticket_requires_payment_method(self):
        ticket = self.create_ticket()
        ticket.status = Ticket.Status.PAID
        form = PaymentForm(data=self.payment_data(payment_method=""), instance=ticket)

        self.assertFalse(form.is_valid())
        self.assertFormError(form, "payment_method", "Paid tickets require a payment method.")

    def test_invalid_payment_date_is_rejected(self):
        ticket = self.create_ticket()
        ticket.status = Ticket.Status.PAID
        form = PaymentForm(
            data=self.payment_data(payment_date="not-a-date"), instance=ticket
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Enter a valid payment date.", form.errors["payment_date"])

    def test_editing_existing_ticket_preserves_unrelated_fields(self):
        ticket = self.create_ticket()
        created_at = ticket.created_at
        ticket.status = Ticket.Status.PAID
        form = PaymentForm(data=self.payment_data(), instance=ticket)

        self.assertTrue(form.is_valid())
        updated_ticket = form.save()
        updated_ticket.refresh_from_db()
        self.assertEqual(updated_ticket.event, self.event)
        self.assertEqual(updated_ticket.attendee, self.attendee)
        self.assertEqual(updated_ticket.price, Decimal("25.00"))
        self.assertEqual(updated_ticket.created_at, created_at)

    def test_form_excludes_unrelated_ticket_fields(self):
        self.assertEqual(list(PaymentForm.base_fields), ["payment_date", "payment_method"])

    def test_zero_price_ticket_can_record_a_payment(self):
        ticket = self.create_ticket(price=Decimal("0.00"))
        ticket.status = Ticket.Status.PAID
        form = PaymentForm(data=self.payment_data(), instance=ticket)

        self.assertTrue(form.is_valid())
        self.assertEqual(form.save().price, Decimal("0.00"))

    def test_unpaid_ticket_rejects_payment_metadata_via_model_validation(self):
        form = PaymentForm(data=self.payment_data(), instance=self.create_ticket())

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Unpaid tickets cannot have payment date or payment method details.",
            form.non_field_errors(),
        )


class PaymentStatusActionTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(
            name="Status Hall", address="4 Payment Street", capacity=2
        )
        self.event = Event.objects.create(
            name="Status Workshop",
            starts_at="2026-12-11T09:00:00Z",
            description="An event used to verify payment status actions.",
            venue=self.venue,
        )
        self.attendee = Attendee.objects.create(
            name="Sam", email="sam@example.com", phone="555-0111"
        )

    def create_ticket(self, **overrides):
        values = {"event": self.event, "attendee": self.attendee, "price": Decimal("25.00")}
        values.update(overrides)
        return Ticket.objects.create(**values)

    def paid_data(self, **overrides):
        values = {
            "payment_date": "2026-12-01",
            "payment_method": Ticket.PaymentMethod.CARD,
        }
        values.update(overrides)
        return values

    def paid_url(self, ticket):
        return reverse("ticketing:ticket_mark_paid", args=[ticket.pk])

    def unpaid_url(self, ticket):
        return reverse("ticketing:ticket_mark_unpaid", args=[ticket.pk])

    def test_unpaid_ticket_can_be_marked_paid(self):
        ticket = self.create_ticket()

        response = self.client.post(self.paid_url(ticket), self.paid_data(), follow=True)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.PAID)
        self.assertEqual(ticket.payment_date, date(2026, 12, 1))
        self.assertEqual(ticket.payment_method, Ticket.PaymentMethod.CARD)
        self.assertRedirects(response, reverse("ticketing:ticket_detail", args=[ticket.pk]))
        self.assertContains(response, "Ticket marked as paid.")

    def test_paid_ticket_can_be_marked_unpaid_and_payment_details_are_cleared(self):
        ticket = self.create_ticket(
            status=Ticket.Status.PAID,
            payment_date=date(2026, 12, 1),
            payment_method=Ticket.PaymentMethod.CARD,
        )

        response = self.client.post(self.unpaid_url(ticket), follow=True)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.UNPAID)
        self.assertIsNone(ticket.payment_date)
        self.assertIsNone(ticket.payment_method)
        self.assertContains(response, "Ticket marked as unpaid.")

    def test_paid_action_requires_payment_date_and_does_not_persist(self):
        ticket = self.create_ticket()

        response = self.client.post(self.paid_url(ticket), self.paid_data(payment_date=""))

        ticket.refresh_from_db()
        self.assertFormError(response.context["form"], "payment_date", "Paid tickets require a payment date.")
        self.assertEqual(ticket.status, Ticket.Status.UNPAID)
        self.assertIsNone(ticket.payment_date)
        self.assertIsNone(ticket.payment_method)

    def test_paid_action_requires_payment_method_and_rejects_invalid_dates(self):
        ticket = self.create_ticket()

        missing_method = self.client.post(
            self.paid_url(ticket), self.paid_data(payment_method="")
        )
        invalid_date = self.client.post(
            self.paid_url(ticket), self.paid_data(payment_date="not-a-date")
        )

        ticket.refresh_from_db()
        self.assertFormError(
            missing_method.context["form"], "payment_method", "Paid tickets require a payment method."
        )
        self.assertIn("Enter a valid payment date.", invalid_date.context["form"].errors["payment_date"])
        self.assertEqual(ticket.status, Ticket.Status.UNPAID)

    def test_zero_price_ticket_can_be_marked_paid(self):
        ticket = self.create_ticket(price=Decimal("0.00"))

        self.client.post(self.paid_url(ticket), self.paid_data())

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.PAID)
        self.assertEqual(ticket.price, Decimal("0.00"))

    def test_get_actions_do_not_mutate_ticket(self):
        unpaid_ticket = self.create_ticket()
        paid_ticket = self.create_ticket(
            attendee=Attendee.objects.create(
                name="Parker", email="parker@example.com", phone="555-0112"
            ),
            status=Ticket.Status.PAID,
            payment_date=date(2026, 12, 1),
            payment_method=Ticket.PaymentMethod.CASH,
        )

        paid_response = self.client.get(self.paid_url(unpaid_ticket))
        unpaid_response = self.client.get(self.unpaid_url(paid_ticket))

        unpaid_ticket.refresh_from_db()
        paid_ticket.refresh_from_db()
        self.assertEqual(paid_response.status_code, 200)
        self.assertEqual(unpaid_response.status_code, 200)
        self.assertEqual(unpaid_ticket.status, Ticket.Status.UNPAID)
        self.assertEqual(paid_ticket.status, Ticket.Status.PAID)

    def test_forged_status_does_not_override_server_defined_transition(self):
        ticket = self.create_ticket()

        self.client.post(self.paid_url(ticket), self.paid_data(status=Ticket.Status.UNPAID))
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.PAID)

        self.client.post(self.unpaid_url(ticket), {"status": Ticket.Status.PAID})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.UNPAID)

    def test_actions_preserve_unrelated_fields_and_repeated_post_does_not_write_again(self):
        ticket = self.create_ticket()
        original_created_at = ticket.created_at

        self.client.post(self.paid_url(ticket), self.paid_data())
        ticket.refresh_from_db()
        original_payment_date = ticket.payment_date
        self.client.post(self.paid_url(ticket), self.paid_data(payment_date="2026-12-02"))
        ticket.refresh_from_db()

        self.assertEqual(ticket.event, self.event)
        self.assertEqual(ticket.attendee, self.attendee)
        self.assertEqual(ticket.price, Decimal("25.00"))
        self.assertEqual(ticket.created_at, original_created_at)
        self.assertEqual(ticket.payment_date, original_payment_date)

    def test_already_target_state_is_safe_and_unknown_tickets_return_404(self):
        unpaid_ticket = self.create_ticket()
        paid_ticket = self.create_ticket(
            attendee=Attendee.objects.create(
                name="Riley", email="riley@example.com", phone="555-0113"
            ),
            status=Ticket.Status.PAID,
            payment_date=date(2026, 12, 1),
            payment_method=Ticket.PaymentMethod.CARD,
        )

        unpaid_response = self.client.post(self.unpaid_url(unpaid_ticket), follow=True)
        paid_response = self.client.post(self.paid_url(paid_ticket), self.paid_data(), follow=True)

        self.assertContains(unpaid_response, "This ticket is already marked as unpaid.")
        self.assertContains(paid_response, "This ticket is already marked as paid.")
        self.assertEqual(self.client.get(reverse("ticketing:ticket_mark_paid", args=[999])).status_code, 404)
        self.assertEqual(self.client.post(reverse("ticketing:ticket_mark_unpaid", args=[999])).status_code, 404)

    def test_payment_actions_require_csrf_tokens(self):
        ticket = self.create_ticket()
        csrf_client = Client(enforce_csrf_checks=True)

        paid_response = csrf_client.post(self.paid_url(ticket), self.paid_data())
        unpaid_response = csrf_client.post(self.unpaid_url(ticket))

        ticket.refresh_from_db()
        self.assertEqual(paid_response.status_code, 403)
        self.assertEqual(unpaid_response.status_code, 403)
        self.assertEqual(ticket.status, Ticket.Status.UNPAID)


class TrackerTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(
            name="Tracker Hall", address="5 Revenue Street", capacity=10
        )
        self.alpha_event = Event.objects.create(
            name="Alpha Summit",
            starts_at="2026-12-12T09:00:00Z",
            description="An event used to verify tracker calculations.",
            venue=self.venue,
        )
        self.beta_event = Event.objects.create(
            name="Beta Workshop",
            starts_at="2026-12-13T09:00:00Z",
            description="Another event used to verify tracker calculations.",
            venue=self.venue,
        )

    def create_ticket(self, attendee_name, email, **overrides):
        attendee = Attendee.objects.create(name=attendee_name, email=email, phone="555-0120")
        values = {"event": self.alpha_event, "attendee": attendee, "price": Decimal("10.00")}
        values.update(overrides)
        return Ticket.objects.create(**values)

    def tracker(self, **params):
        return self.client.get(reverse("ticketing:tracker"), params)

    def test_empty_tracker_uses_zero_decimal_metrics_and_empty_state(self):
        response = self.tracker()

        self.assertEqual(response.context["expected_revenue"], Decimal("0.00"))
        self.assertEqual(response.context["collected_revenue"], Decimal("0.00"))
        self.assertEqual(response.context["outstanding_revenue"], Decimal("0.00"))
        self.assertEqual(response.context["collection_percentage"], Decimal("0.00"))
        self.assertEqual(response.context["matching_ticket_count"], 0)
        self.assertContains(response, "No tickets to monitor yet")

    def test_mixed_ticket_kpis_use_payment_status_and_decimal_values(self):
        self.create_ticket(
            "Alex", "alex-tracker@example.com", price=Decimal("30.00"),
            status=Ticket.Status.PAID, payment_date=date(2026, 12, 1),
            payment_method=Ticket.PaymentMethod.CARD,
        )
        self.create_ticket("Blair", "blair-tracker@example.com", price=Decimal("20.00"))
        self.create_ticket("Casey", "casey-tracker@example.com", price=Decimal("0.00"))

        response = self.tracker()

        self.assertEqual(response.context["expected_revenue"], Decimal("50"))
        self.assertEqual(response.context["collected_revenue"], Decimal("30"))
        self.assertEqual(response.context["outstanding_revenue"], Decimal("20"))
        self.assertEqual(response.context["paid_ticket_count"], 1)
        self.assertEqual(response.context["unpaid_ticket_count"], 2)
        self.assertEqual(response.context["collection_percentage"], Decimal("60.0"))

    def test_fully_paid_and_fully_unpaid_sets_are_calculated_correctly(self):
        paid = self.create_ticket(
            "Dana", "dana-tracker@example.com", price=Decimal("15.00"),
            status=Ticket.Status.PAID, payment_date=date(2026, 12, 1),
            payment_method=Ticket.PaymentMethod.CASH,
        )
        paid_response = self.tracker()
        paid.delete()
        self.create_ticket("Evan", "evan-tracker@example.com", price=Decimal("15.00"))
        unpaid_response = self.tracker()

        self.assertEqual(paid_response.context["collection_percentage"], Decimal("100"))
        self.assertEqual(paid_response.context["outstanding_revenue"], Decimal("0"))
        self.assertEqual(unpaid_response.context["collection_percentage"], Decimal("0"))
        self.assertEqual(unpaid_response.context["collected_revenue"], Decimal("0"))

    def test_zero_price_tickets_do_not_cause_division_errors(self):
        self.create_ticket("Free", "free-tracker@example.com", price=Decimal("0.00"))

        response = self.tracker()

        self.assertEqual(response.context["expected_revenue"], Decimal("0"))
        self.assertEqual(response.context["collection_percentage"], Decimal("0.00"))

    def test_search_matches_event_attendee_and_email(self):
        alpha_ticket = self.create_ticket("Alex Morgan", "alex@example.com")
        beta_ticket = self.create_ticket(
            "Blair Stone", "blair@example.com", event=self.beta_event
        )

        expected = {
            "ALPHA": [alpha_ticket],
            "blair": [beta_ticket],
            "ALEX@EXAMPLE.COM": [alpha_ticket],
        }
        for query, tickets in expected.items():
            with self.subTest(query=query):
                response = self.tracker(q=query)
                self.assertEqual(list(response.context["tickets"]), tickets)
                self.assertEqual(response.context["matching_ticket_count"], len(tickets))

    def test_valid_filters_apply_only_to_tracker_table_and_invalid_filters_are_safe(self):
        paid_ticket = self.create_ticket(
            "Alex", "filters-alex@example.com", price=Decimal("30.00"),
            status=Ticket.Status.PAID, payment_date=date(2026, 12, 1),
            payment_method=Ticket.PaymentMethod.CARD,
        )
        unpaid_ticket = self.create_ticket(
            "Blair", "filters-blair@example.com", event=self.beta_event, price=Decimal("20.00")
        )

        filtered = self.tracker(event=self.alpha_event.pk, status=Ticket.Status.PAID)
        invalid = self.tracker(event="not-an-id", status="SETTLED")

        self.assertEqual(list(filtered.context["tickets"]), [paid_ticket])
        self.assertEqual(filtered.context["matching_ticket_count"], 1)
        self.assertEqual(filtered.context["expected_revenue"], Decimal("50"))
        self.assertEqual(filtered.context["collected_revenue"], Decimal("30"))
        self.assertEqual(list(invalid.context["tickets"]), [paid_ticket, unpaid_ticket])
        self.assertIsNone(invalid.context["selected_event"])
        self.assertEqual(invalid.context["selected_status"], "")

    def test_tracker_displays_payment_action_links_for_each_status(self):
        unpaid_ticket = self.create_ticket("Alex", "links-alex@example.com")
        paid_ticket = self.create_ticket(
            "Blair", "links-blair@example.com", status=Ticket.Status.PAID,
            payment_date=date(2026, 12, 1), payment_method=Ticket.PaymentMethod.CARD,
        )

        response = self.tracker()

        self.assertContains(response, reverse("ticketing:ticket_mark_paid", args=[unpaid_ticket.pk]))
        self.assertContains(response, reverse("ticketing:ticket_mark_unpaid", args=[paid_ticket.pk]))

    def test_tracker_metrics_refresh_after_valid_and_invalid_payment_submissions(self):
        ticket = self.create_ticket("Alex", "transition-alex@example.com", price=Decimal("25.00"))
        before = self.tracker()
        invalid = self.client.post(
            reverse("ticketing:ticket_mark_paid", args=[ticket.pk]),
            {"payment_date": "", "payment_method": Ticket.PaymentMethod.CARD},
        )
        after_invalid = self.tracker()
        self.client.post(
            reverse("ticketing:ticket_mark_paid", args=[ticket.pk]),
            {"payment_date": "2026-12-01", "payment_method": Ticket.PaymentMethod.CARD},
        )
        after_paid = self.tracker()

        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(before.context["collected_revenue"], Decimal("0"))
        self.assertEqual(after_invalid.context["collected_revenue"], Decimal("0"))
        self.assertEqual(after_paid.context["collected_revenue"], Decimal("25"))
        self.assertEqual(after_paid.context["outstanding_revenue"], Decimal("0"))


class DashboardAnalyticsTests(TestCase):
    def dashboard(self):
        return self.client.get(reverse("ticketing:dashboard"))

    def test_empty_dashboard_uses_zero_metrics_and_existing_route(self):
        response = self.dashboard()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_event_count"], 0)
        self.assertEqual(response.context["total_attendee_count"], 0)
        self.assertEqual(response.context["issued_ticket_count"], 0)
        self.assertEqual(response.context["expected_revenue"], Decimal("0.00"))
        self.assertEqual(response.context["collected_revenue"], Decimal("0.00"))
        self.assertEqual(response.context["outstanding_revenue"], Decimal("0.00"))
        self.assertEqual(response.context["collection_percentage"], Decimal("0.00"))
        self.assertContains(response, "Total attendees")
        self.assertContains(response, "Collection rate")

    def test_dashboard_counts_and_financial_metrics_match_tracker(self):
        venue = Venue.objects.create(
            name="Dashboard Hall", address="8 Metrics Street", capacity=10
        )
        first_event = Event.objects.create(
            name="Dashboard Summit", starts_at="2027-01-10T09:00:00Z",
            description="An event used for dashboard metrics.", venue=venue,
        )
        second_event = Event.objects.create(
            name="Dashboard Workshop", starts_at="2027-01-11T09:00:00Z",
            description="A second event used for dashboard metrics.", venue=venue,
        )
        shared_attendee = Attendee.objects.create(
            name="Alex", email="alex-dashboard@example.com", phone="555-0130"
        )
        other_attendee = Attendee.objects.create(
            name="Blair", email="blair-dashboard@example.com", phone="555-0131"
        )
        Ticket.objects.create(
            event=first_event, attendee=shared_attendee, price=Decimal("25.00"),
            status=Ticket.Status.PAID, payment_date=date(2027, 1, 1),
            payment_method=Ticket.PaymentMethod.CARD,
        )
        Ticket.objects.create(
            event=second_event, attendee=shared_attendee, price=Decimal("15.00")
        )
        Ticket.objects.create(
            event=first_event, attendee=other_attendee, price=Decimal("0.00"),
            status=Ticket.Status.PAID, payment_date=date(2027, 1, 2),
            payment_method=Ticket.PaymentMethod.CASH,
        )

        dashboard_response = self.dashboard()
        tracker_response = self.client.get(reverse("ticketing:tracker"))

        self.assertEqual(dashboard_response.context["total_event_count"], 2)
        self.assertEqual(dashboard_response.context["total_attendee_count"], 2)
        self.assertEqual(dashboard_response.context["issued_ticket_count"], 3)
        self.assertEqual(dashboard_response.context["expected_revenue"], Decimal("40"))
        self.assertEqual(dashboard_response.context["collected_revenue"], Decimal("25"))
        self.assertEqual(dashboard_response.context["outstanding_revenue"], Decimal("15"))
        self.assertEqual(dashboard_response.context["collection_percentage"], Decimal("62.5"))
        for metric in (
            "expected_revenue", "collected_revenue", "outstanding_revenue",
            "collection_percentage",
        ):
            self.assertEqual(
                dashboard_response.context[metric], tracker_response.context[metric]
            )


class EventPerformanceAnalyticsTests(TestCase):
    def create_event(self, name, capacity=10, venue=None):
        venue = venue or Venue.objects.create(
            name=f"{name} Hall", address=f"{name} Street", capacity=capacity
        )
        return Event.objects.create(
            name=name,
            starts_at="2027-02-01T09:00:00Z",
            description=f"{name} performance test event.",
            venue=venue,
        )

    def issue_tickets(self, event, count, price=Decimal("0.00")):
        for number in range(count):
            attendee = Attendee.objects.create(
                name=f"{event.name} attendee {number}",
                email=f"{event.pk}-{number}@performance.example.com",
                phone="555-0190",
            )
            Ticket.objects.create(event=event, attendee=attendee, price=price)

    def test_empty_dashboard_has_event_comparison_empty_state(self):
        response = self.client.get(reverse("ticketing:dashboard"))

        self.assertEqual(response.context["event_performance"], [])
        self.assertContains(response, "No events to compare yet")
        self.assertContains(response, reverse("events:event_create"))

    def test_health_status_uses_exact_unrounded_occupancy_boundaries(self):
        boundary_cases = (
            ("Below 30", 2, "Needs Attention"),
            ("Exactly 30", 3, "On Track"),
            ("Below 80", 7, "On Track"),
            ("Exactly 80", 8, "Near Capacity"),
            ("Below 100", 9, "Near Capacity"),
            ("Exactly 100", 10, "Full"),
        )
        events = []
        for name, ticket_count, _ in boundary_cases:
            event = self.create_event(name)
            self.issue_tickets(event, ticket_count)
            events.append(event)

        with self.assertNumQueries(1):
            performances = get_event_performance()

        performance_by_event = {performance.event.pk: performance for performance in performances}
        for event, (_, ticket_count, expected_health) in zip(events, boundary_cases):
            with self.subTest(event=event.name):
                performance = performance_by_event[event.pk]
                self.assertEqual(performance.ticket_count, ticket_count)
                self.assertEqual(performance.occupancy_percentage, Decimal(ticket_count * 10))
                self.assertEqual(performance.health_status, expected_health)

    def test_event_metrics_are_independent_and_match_tracker_and_detail(self):
        shared_venue = Venue.objects.create(
            name="Shared Performance Hall", address="1 Compare Street", capacity=5
        )
        partially_filled_event = self.create_event(
            "Partially Filled", venue=shared_venue
        )
        full_event = self.create_event("Full Shared Venue", venue=shared_venue)
        empty_event = self.create_event("Empty Venue", capacity=8)

        paid_attendee = Attendee.objects.create(
            name="Paid attendee", email="paid-performance@example.com", phone="555-0191"
        )
        unpaid_attendee = Attendee.objects.create(
            name="Unpaid attendee", email="unpaid-performance@example.com", phone="555-0192"
        )
        Ticket.objects.create(
            event=partially_filled_event, attendee=paid_attendee, price=Decimal("20.00"),
            status=Ticket.Status.PAID, payment_date=date(2027, 1, 15),
            payment_method=Ticket.PaymentMethod.CARD,
        )
        Ticket.objects.create(
            event=partially_filled_event, attendee=unpaid_attendee, price=Decimal("10.00")
        )
        self.issue_tickets(full_event, 4, price=Decimal("5.00"))
        zero_price_attendee = Attendee.objects.create(
            name="Zero price attendee",
            email="zero-price-performance@example.com",
            phone="555-0193",
        )
        Ticket.objects.create(
            event=full_event, attendee=zero_price_attendee, price=Decimal("0.00")
        )

        dashboard_response = self.client.get(reverse("ticketing:dashboard"))
        tracker_response = self.client.get(reverse("ticketing:tracker"))
        detail_response = self.client.get(
            reverse("events:event_detail", args=[partially_filled_event.pk])
        )
        performance_by_event = {
            performance.event.pk: performance
            for performance in dashboard_response.context["event_performance"]
        }
        partial_performance = performance_by_event[partially_filled_event.pk]
        full_performance = performance_by_event[full_event.pk]
        empty_performance = performance_by_event[empty_event.pk]

        self.assertEqual(partial_performance.ticket_count, 2)
        self.assertEqual(partial_performance.remaining_seats, 3)
        self.assertEqual(partial_performance.occupancy_percentage, Decimal("40"))
        self.assertEqual(partial_performance.expected_revenue, Decimal("30"))
        self.assertEqual(partial_performance.collected_revenue, Decimal("20"))
        self.assertEqual(partial_performance.outstanding_revenue, Decimal("10"))
        self.assertEqual(partial_performance.collection_percentage, Decimal("66.66666666666666666666666667"))
        self.assertEqual(partial_performance.health_status, "On Track")
        self.assertEqual(full_performance.occupancy_percentage, Decimal("100"))
        self.assertEqual(full_performance.health_status, "Full")
        self.assertEqual(full_performance.expected_revenue, Decimal("20"))
        self.assertEqual(full_performance.collected_revenue, Decimal("0"))
        self.assertEqual(full_performance.outstanding_revenue, Decimal("20"))
        self.assertEqual(full_performance.collection_percentage, Decimal("0.00"))
        self.assertEqual(empty_performance.ticket_count, 0)
        self.assertEqual(empty_performance.remaining_seats, 8)
        self.assertEqual(empty_performance.expected_revenue, Decimal("0"))
        self.assertEqual(empty_performance.collection_percentage, Decimal("0.00"))
        self.assertEqual(empty_performance.health_status, "Needs Attention")
        self.assertEqual(
            partial_performance.expected_revenue,
            detail_response.context["event"].expected_revenue,
        )
        self.assertEqual(
            partial_performance.collected_revenue,
            detail_response.context["event"].collected_revenue,
        )
        self.assertEqual(
            dashboard_response.context["expected_revenue"],
            tracker_response.context["expected_revenue"],
        )
        self.assertEqual(
            dashboard_response.context["collected_revenue"],
            tracker_response.context["collected_revenue"],
        )
        self.assertContains(
            dashboard_response,
            reverse("events:event_detail", args=[partially_filled_event.pk]),
        )
        self.assertContains(dashboard_response, "Full")


class InsightsTests(TestCase):
    def create_event(self, name, venue):
        return Event.objects.create(
            name=name,
            starts_at="2027-06-01T09:00:00Z",
            description="An event used for insights tests.",
            venue=venue,
        )

    def create_attendee(self, suffix):
        return Attendee.objects.create(
            name=f"Insights attendee {suffix}",
            email=f"insights-{suffix}@example.com",
            phone="555-0160",
        )

    def test_empty_insights_uses_zero_metrics_and_text_alternatives(self):
        response = self.client.get(reverse("ticketing:insights"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["selected_event"])
        self.assertEqual(response.context["event_performance"], [])
        self.assertEqual(response.context["issued_ticket_count"], 0)
        self.assertEqual(response.context["paid_ticket_percentage"], Decimal("0"))
        self.assertContains(response, "No events to compare yet")
        self.assertContains(response, "Expected vs collected revenue by event")
        self.assertContains(response, "Ticket payment distribution values")

    def test_overall_and_selected_scope_reuse_shared_financial_definitions(self):
        shared_venue = Venue.objects.create(
            name="Insights Shared Hall", address="40 Data Street", capacity=4
        )
        alpha_event = self.create_event("Alpha Insights", shared_venue)
        beta_event = self.create_event("Beta Insights", shared_venue)
        long_event_name = (
            "A very long insights event name designed to wrap safely in a chart label "
            + "<script>alert('not executable')</script>"
        )
        long_name_event = self.create_event(
            long_event_name,
            Venue.objects.create(
                name="Quiet Hall", address="41 Data Street", capacity=3
            ),
        )
        Ticket.objects.create(
            event=alpha_event, attendee=self.create_attendee("alpha-paid"),
            price=Decimal("50.00"), status=Ticket.Status.PAID,
            payment_date=date(2027, 5, 1), payment_method=Ticket.PaymentMethod.CARD,
        )
        Ticket.objects.create(
            event=alpha_event, attendee=self.create_attendee("alpha-unpaid"),
            price=Decimal("25.00"),
        )
        Ticket.objects.create(
            event=alpha_event, attendee=self.create_attendee("alpha-zero"),
            price=Decimal("0.00"),
        )
        for number in range(4):
            Ticket.objects.create(
                event=beta_event, attendee=self.create_attendee(f"beta-{number}"),
                price=Decimal("10.00"),
            )

        overall_response = self.client.get(reverse("ticketing:insights"))
        selected_response = self.client.get(
            reverse("ticketing:insights"), {"event": alpha_event.pk}
        )
        tracker_response = self.client.get(reverse("ticketing:tracker"))
        detail_response = self.client.get(
            reverse("events:event_detail", args=[alpha_event.pk])
        )

        self.assertEqual(len(overall_response.context["event_performance"]), 3)
        self.assertEqual(overall_response.context["expected_revenue"], Decimal("115"))
        self.assertEqual(overall_response.context["collected_revenue"], Decimal("50"))
        self.assertEqual(overall_response.context["paid_ticket_count"], 1)
        self.assertEqual(overall_response.context["unpaid_ticket_count"], 6)
        self.assertEqual(overall_response.context["paid_ticket_percentage"], Decimal("14.28571428571428571428571429"))
        self.assertEqual(overall_response.context["expected_revenue"], tracker_response.context["expected_revenue"])
        self.assertEqual(overall_response.context["collected_revenue"], tracker_response.context["collected_revenue"])
        self.assertEqual(selected_response.context["selected_event"], alpha_event)
        self.assertEqual(len(selected_response.context["event_performance"]), 1)
        self.assertEqual(selected_response.context["expected_revenue"], Decimal("75"))
        self.assertEqual(selected_response.context["collected_revenue"], Decimal("50"))
        self.assertEqual(selected_response.context["outstanding_revenue"], Decimal("25"))
        self.assertEqual(selected_response.context["paid_ticket_count"], 1)
        self.assertEqual(selected_response.context["unpaid_ticket_count"], 2)
        self.assertEqual(selected_response.context["event_performance"][0].occupancy_percentage, Decimal("75"))
        self.assertEqual(selected_response.context["event_performance"][0].health_status, "On Track")
        self.assertEqual(selected_response.context["expected_revenue"], detail_response.context["event"].expected_revenue)
        self.assertEqual(selected_response.context["collected_revenue"], detail_response.context["event"].collected_revenue)
        self.assertContains(selected_response, f'<option value="{alpha_event.pk}" selected>')
        self.assertContains(selected_response, "Reset filters")
        self.assertContains(overall_response, "Expected vs collected revenue by event")
        self.assertContains(overall_response, "Event occupancy comparison")
        self.assertContains(overall_response, "Paid vs unpaid ticket distribution")
        self.assertContains(overall_response, "Revenue comparison values")
        self.assertContains(overall_response, "Occupancy comparison values")
        self.assertContains(overall_response, long_event_name.split("<")[0])
        self.assertContains(overall_response, "&lt;script&gt;")
        self.assertNotContains(overall_response, "<script>alert('not executable')</script>")

    def test_invalid_event_filter_falls_back_to_overall_scope(self):
        venue = Venue.objects.create(
            name="Filter Hall", address="42 Data Street", capacity=1
        )
        event = self.create_event("Filter Event", venue)
        Ticket.objects.create(
            event=event, attendee=self.create_attendee("filter"), price=Decimal("12.00")
        )

        response = self.client.get(reverse("ticketing:insights"), {"event": "invalid"})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["selected_event"])
        self.assertEqual(response.context["expected_revenue"], Decimal("12"))
        self.assertEqual(len(response.context["event_performance"]), 1)

    def test_fully_paid_selected_event_has_full_collection_distribution(self):
        venue = Venue.objects.create(
            name="Paid Hall", address="43 Data Street", capacity=2
        )
        event = self.create_event("Paid Insights", venue)
        Ticket.objects.create(
            event=event, attendee=self.create_attendee("paid-only"), price=Decimal("30.00"),
            status=Ticket.Status.PAID, payment_date=date(2027, 5, 2),
            payment_method=Ticket.PaymentMethod.CASH,
        )

        response = self.client.get(reverse("ticketing:insights"), {"event": event.pk})

        self.assertEqual(response.context["collection_percentage"], Decimal("100"))
        self.assertEqual(response.context["paid_ticket_percentage"], Decimal("100"))
        self.assertEqual(response.context["unpaid_ticket_percentage"], Decimal("0"))


class TicketCrudViewTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(
            name="Ticket Hall", address="10 Ticket Lane", capacity=2
        )
        self.event = Event.objects.create(
            name="Ticket Conference",
            starts_at="2026-12-10T09:00:00Z",
            description="A ticketing test event.",
            venue=self.venue,
        )
        self.attendee = Attendee.objects.create(
            name="Taylor", email="taylor@example.com", phone="555-0101"
        )

    def ticket_data(self, **overrides):
        data = {
            "event": self.event.pk,
            "attendee": self.attendee.pk,
            "price": "25.00",
            "status": Ticket.Status.UNPAID,
            "payment_date": "",
            "payment_method": "",
        }
        data.update(overrides)
        return data

    def create_attendee(self, name, email):
        return Attendee.objects.create(name=name, email=email, phone="555-0102")

    def create_ticket(self, **overrides):
        values = {
            "event": self.event,
            "attendee": self.attendee,
            "price": Decimal("25.00"),
        }
        values.update(overrides)
        return Ticket.objects.create(**values)

    def test_list_and_detail_display_ticket(self):
        ticket = self.create_ticket()

        list_response = self.client.get(reverse("ticketing:ticket_list"))
        detail_response = self.client.get(
            reverse("ticketing:ticket_detail", kwargs={"pk": ticket.pk})
        )

        self.assertContains(list_response, self.attendee.name)
        self.assertContains(list_response, self.event.name)
        self.assertContains(detail_response, self.attendee.email)
        self.assertContains(detail_response, "Edit ticket")

    def test_create_ticket_redirects_to_detail_with_success_message(self):
        response = self.client.post(
            reverse("ticketing:ticket_create"), self.ticket_data(), follow=True
        )

        ticket = Ticket.objects.get()
        self.assertRedirects(response, reverse("ticketing:ticket_detail", args=[ticket.pk]))
        self.assertContains(response, "Ticket created successfully.")

    def test_update_ticket_does_not_double_count_capacity(self):
        self.venue.capacity = 1
        self.venue.save()
        ticket = self.create_ticket()

        response = self.client.post(
            reverse("ticketing:ticket_update", args=[ticket.pk]),
            self.ticket_data(price="30.00"),
            follow=True,
        )

        ticket.refresh_from_db()
        self.assertEqual(ticket.price, Decimal("30.00"))
        self.assertContains(response, "Ticket updated successfully.")

    def test_create_rejects_full_capacity_and_preserves_error(self):
        self.venue.capacity = 1
        self.venue.save()
        self.create_ticket()
        other_attendee = self.create_attendee("Morgan", "morgan@example.com")

        response = self.client.post(
            reverse("ticketing:ticket_create"), self.ticket_data(attendee=other_attendee.pk)
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "event",
            "This event's venue is already at full capacity.",
        )
        self.assertContains(response, "Please correct the ticket form errors below.")
        self.assertEqual(Ticket.objects.count(), 1)

    def test_create_rejects_duplicate_ticket(self):
        self.create_ticket()

        response = self.client.post(reverse("ticketing:ticket_create"), self.ticket_data())

        self.assertContains(response, "This attendee already has a ticket for the selected event.")
        self.assertEqual(Ticket.objects.count(), 1)

    def test_update_reassigns_ticket_when_destination_has_capacity(self):
        ticket = self.create_ticket()
        destination = Event.objects.create(
            name="Second Conference",
            starts_at="2027-01-10T09:00:00Z",
            description="A second event.",
            venue=Venue.objects.create(
                name="Second Hall", address="11 Ticket Lane", capacity=1
            ),
        )

        response = self.client.post(
            reverse("ticketing:ticket_update", args=[ticket.pk]),
            self.ticket_data(event=destination.pk),
            follow=True,
        )

        ticket.refresh_from_db()
        self.assertEqual(ticket.event, destination)
        self.assertContains(response, "Ticket updated successfully.")

    def test_update_reassignment_to_full_event_saves_nothing(self):
        ticket = self.create_ticket()
        destination = Event.objects.create(
            name="Full Conference",
            starts_at="2027-01-10T09:00:00Z",
            description="A full event.",
            venue=Venue.objects.create(
                name="Full Hall", address="12 Ticket Lane", capacity=1
            ),
        )
        Ticket.objects.create(
            event=destination,
            attendee=self.create_attendee("Morgan", "morgan@example.com"),
            price=Decimal("25.00"),
        )

        response = self.client.post(
            reverse("ticketing:ticket_update", args=[ticket.pk]),
            self.ticket_data(event=destination.pk, price="30.00"),
        )

        ticket.refresh_from_db()
        self.assertFormError(
            response.context["form"],
            "event",
            "This event's venue is already at full capacity.",
        )
        self.assertEqual(ticket.event, self.event)
        self.assertEqual(ticket.price, Decimal("25.00"))

    def test_delete_uses_get_confirmation_and_post_only_deletion(self):
        ticket = self.create_ticket()
        delete_url = reverse("ticketing:ticket_delete", args=[ticket.pk])

        confirmation = self.client.get(delete_url)
        self.assertContains(confirmation, f"Delete ticket #{ticket.pk}?")
        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())

        response = self.client.post(delete_url, follow=True)
        self.assertRedirects(response, reverse("ticketing:ticket_list"))
        self.assertContains(response, "Ticket deleted successfully.")
        self.assertFalse(Ticket.objects.filter(pk=ticket.pk).exists())

    def test_ticket_views_return_404_for_unknown_ticket(self):
        for route_name in ("ticketing:ticket_detail", "ticketing:ticket_update", "ticketing:ticket_delete"):
            with self.subTest(route_name=route_name):
                self.assertEqual(self.client.get(reverse(route_name, args=[999])).status_code, 404)

    def test_empty_database_ticket_create_shows_prerequisites_and_links(self):
        Ticket.objects.all().delete()
        Attendee.objects.all().delete()
        Event.objects.all().delete()
        Venue.objects.all().delete()

        response = self.client.get(reverse("ticketing:ticket_create"))

        self.assertContains(response, "Create ticket prerequisites first")
        self.assertContains(response, reverse("events:event_create"))
        self.assertContains(response, reverse("attendees:attendee_create"))

    def test_ticket_navigation_and_placeholder_routes_remain_available(self):
        for route_name in (
            "ticketing:dashboard",
            "ticketing:ticket_list",
            "ticketing:tracker",
            "ticketing:insights",
        ):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Primary navigation")


class TicketUiRefinementTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(
            name="Harbor Hall", address="14 Harbor Road", capacity=5
        )
        self.event = Event.objects.create(
            name="Design Summit",
            starts_at="2027-02-10T09:00:00Z",
            description="A design event.",
            venue=self.venue,
        )
        self.attendee = Attendee.objects.create(
            name="Jordan Lee", email="jordan@example.com", phone="555-0130"
        )

    def ticket_data(self, **overrides):
        data = {
            "event": self.event.pk,
            "attendee": self.attendee.pk,
            "price": "45.00",
            "status": Ticket.Status.UNPAID,
            "payment_date": "",
            "payment_method": "",
        }
        data.update(overrides)
        return data

    def test_list_displays_ticket_fields_status_badge_and_action_links(self):
        ticket = Ticket.objects.create(
            event=self.event,
            attendee=self.attendee,
            price=Decimal("45.00"),
            status=Ticket.Status.PAID,
            payment_date=date(2027, 1, 15),
            payment_method=Ticket.PaymentMethod.CARD,
        )

        response = self.client.get(reverse("ticketing:ticket_list"))

        self.assertContains(response, f"#{ticket.pk}")
        self.assertContains(response, self.event.name)
        self.assertContains(response, self.attendee.name)
        self.assertContains(response, "status-badge status-paid")
        for route_name in (
            "ticketing:ticket_detail",
            "ticketing:ticket_update",
            "ticketing:ticket_delete",
        ):
            self.assertContains(response, reverse(route_name, args=[ticket.pk]))

    def test_detail_displays_payment_metadata_and_creation_date(self):
        ticket = Ticket.objects.create(
            event=self.event,
            attendee=self.attendee,
            price=Decimal("45.00"),
            status=Ticket.Status.PAID,
            payment_date=date(2027, 1, 15),
            payment_method=Ticket.PaymentMethod.CARD,
        )

        response = self.client.get(reverse("ticketing:ticket_detail", args=[ticket.pk]))

        self.assertContains(response, self.venue.name)
        self.assertContains(response, "Paid on 15 Jan 2027 by Card")
        self.assertContains(response, "Issued")

    def test_invalid_form_retains_submitted_values_and_displays_error_context(self):
        response = self.client.post(
            reverse("ticketing:ticket_create"), self.ticket_data(price="-1.00")
        )

        self.assertContains(response, 'value="-1.00"')
        self.assertContains(response, "Ticket price needs attention:")
        self.assertContains(response, "Please correct the ticket form errors below.")

    def test_delete_confirmation_identifies_ticket_and_uses_post_form(self):
        ticket = Ticket.objects.create(
            event=self.event, attendee=self.attendee, price=Decimal("45.00")
        )

        response = self.client.get(reverse("ticketing:ticket_delete", args=[ticket.pk]))

        self.assertContains(response, f"Delete ticket #{ticket.pk}?")
        self.assertContains(response, self.venue.name)
        self.assertContains(response, 'method="post"')
        self.assertContains(response, "csrfmiddlewaretoken")


class TicketListControlsAndIntegrationTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(
            name="Search Hall", address="20 Search Street", capacity=5
        )
        self.earlier_event = Event.objects.create(
            name="Alpha Workshop",
            starts_at="2027-03-01T09:00:00Z",
            description="An earlier event.",
            venue=self.venue,
        )
        self.later_event = Event.objects.create(
            name="Beta Summit",
            starts_at="2027-04-01T09:00:00Z",
            description="A later event.",
            venue=self.venue,
        )
        self.alex = Attendee.objects.create(
            name="Alex Morgan", email="alex@example.com", phone="555-0140"
        )
        self.blair = Attendee.objects.create(
            name="Blair Stone", email="blair@example.com", phone="555-0141"
        )
        self.casey = Attendee.objects.create(
            name="Casey Jones", email="casey@example.com", phone="555-0142"
        )
        self.alpha_paid = Ticket.objects.create(
            event=self.earlier_event,
            attendee=self.alex,
            price=Decimal("30.00"),
            status=Ticket.Status.PAID,
            payment_date=date(2027, 2, 1),
            payment_method=Ticket.PaymentMethod.CARD,
        )
        self.beta_unpaid = Ticket.objects.create(
            event=self.later_event,
            attendee=self.blair,
            price=Decimal("10.00"),
        )
        self.alpha_unpaid = Ticket.objects.create(
            event=self.earlier_event,
            attendee=self.casey,
            price=Decimal("20.00"),
        )
        now = timezone.now()
        Ticket.objects.filter(pk=self.alpha_paid.pk).update(created_at=now - timedelta(days=3))
        Ticket.objects.filter(pk=self.beta_unpaid.pk).update(created_at=now - timedelta(days=2))
        Ticket.objects.filter(pk=self.alpha_unpaid.pk).update(created_at=now - timedelta(days=1))

    def ticket_list(self, **params):
        return self.client.get(reverse("ticketing:ticket_list"), params)

    def test_search_matches_event_attendee_and_email_case_insensitively(self):
        expected_searches = {
            "ALPHA": [self.alpha_unpaid, self.alpha_paid],
            "blair": [self.beta_unpaid],
            "CASEY@EXAMPLE.COM": [self.alpha_unpaid],
        }

        for query, expected_tickets in expected_searches.items():
            with self.subTest(query=query):
                response = self.ticket_list(q=query)
                self.assertEqual(list(response.context["tickets"]), expected_tickets)

    def test_valid_event_and_payment_status_filters_can_be_combined(self):
        event_response = self.ticket_list(event=self.earlier_event.pk)
        paid_response = self.ticket_list(status=Ticket.Status.PAID)
        unpaid_response = self.ticket_list(status=Ticket.Status.UNPAID)
        combined_response = self.ticket_list(
            q="alpha", event=self.earlier_event.pk, status=Ticket.Status.UNPAID
        )

        self.assertEqual(
            list(event_response.context["tickets"]), [self.alpha_unpaid, self.alpha_paid]
        )
        self.assertEqual(list(paid_response.context["tickets"]), [self.alpha_paid])
        self.assertEqual(
            list(unpaid_response.context["tickets"]), [self.alpha_unpaid, self.beta_unpaid]
        )
        self.assertEqual(list(combined_response.context["tickets"]), [self.alpha_unpaid])

    def test_every_allowlisted_sort_option_orders_tickets(self):
        expected_orderings = {
            "newest": [self.alpha_unpaid, self.beta_unpaid, self.alpha_paid],
            "oldest": [self.alpha_paid, self.beta_unpaid, self.alpha_unpaid],
            "price": [self.beta_unpaid, self.alpha_unpaid, self.alpha_paid],
            "-price": [self.alpha_paid, self.alpha_unpaid, self.beta_unpaid],
            "event_date": [self.alpha_unpaid, self.alpha_paid, self.beta_unpaid],
        }

        for sort_option, expected_tickets in expected_orderings.items():
            with self.subTest(sort_option=sort_option):
                response = self.ticket_list(sort=sort_option)
                self.assertEqual(list(response.context["tickets"]), expected_tickets)
                self.assertEqual(response.context["sort"], sort_option)

    def test_invalid_filters_and_sorting_fall_back_without_errors(self):
        response = self.ticket_list(
            event="not-an-id", status="SETTLED", sort="price; DROP TABLE ticketing_ticket"
        )
        unknown_event_response = self.ticket_list(event=999999)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["tickets"]),
            [self.alpha_unpaid, self.beta_unpaid, self.alpha_paid],
        )
        self.assertIsNone(response.context["selected_event"])
        self.assertEqual(response.context["selected_status"], "")
        self.assertEqual(response.context["sort"], "newest")
        self.assertEqual(
            list(unknown_event_response.context["tickets"]),
            [self.alpha_unpaid, self.beta_unpaid, self.alpha_paid],
        )
        self.assertIsNone(unknown_event_response.context["selected_event"])

    def test_controls_preserve_values_and_expose_accurate_match_count(self):
        response = self.ticket_list(
            q="alpha", event=self.earlier_event.pk, status=Ticket.Status.UNPAID, sort="price"
        )

        self.assertEqual(response.context["matching_ticket_count"], 1)
        self.assertContains(response, 'value="alpha"')
        self.assertContains(response, f'<option value="{self.earlier_event.pk}" selected>')
        self.assertContains(response, '<option value="UNPAID" selected>')
        self.assertContains(response, '<option value="price" selected>')
        self.assertContains(response, "1 ticket found")
        self.assertContains(response, "Reset filters")

    def test_event_detail_issues_ticket_with_valid_preselection(self):
        response = self.client.get(reverse("events:event_detail", args=[self.earlier_event.pk]))
        create_url = reverse("ticketing:ticket_create")
        preselected_response = self.client.get(create_url, {"event": self.earlier_event.pk})

        self.assertContains(response, f"{create_url}?event={self.earlier_event.pk}")
        self.assertEqual(str(preselected_response.context["form"]["event"].value()), str(self.earlier_event.pk))

    def test_preselection_still_enforces_ticket_validation(self):
        full_venue = Venue.objects.create(
            name="Full Search Hall", address="21 Search Street", capacity=1
        )
        full_event = Event.objects.create(
            name="Full Workshop",
            starts_at="2027-05-01T09:00:00Z",
            description="A full event.",
            venue=full_venue,
        )
        Ticket.objects.create(event=full_event, attendee=self.alex, price=Decimal("10.00"))

        response = self.client.post(
            reverse("ticketing:ticket_create") + f"?event={full_event.pk}",
            {
                "event": full_event.pk,
                "attendee": self.blair.pk,
                "price": "10.00",
                "status": Ticket.Status.UNPAID,
                "payment_date": "",
                "payment_method": "",
            },
        )

        self.assertFormError(
            response.context["form"],
            "event",
            "This event's venue is already at full capacity.",
        )
        self.assertEqual(Ticket.objects.filter(event=full_event).count(), 1)

    def test_event_and_attendee_details_show_persisted_ticket_information(self):
        event_response = self.client.get(
            reverse("events:event_detail", args=[self.earlier_event.pk])
        )
        attendee_response = self.client.get(
            reverse("attendees:attendee_detail", args=[self.alex.pk])
        )

        event = event_response.context["event"]
        self.assertEqual(event.ticket_count, 2)
        self.assertEqual(event.expected_revenue, Decimal("50"))
        self.assertEqual(event.collected_revenue, Decimal("30"))
        self.assertContains(event_response, self.alex.name)
        self.assertContains(event_response, self.casey.name)
        self.assertContains(attendee_response, self.earlier_event.name)
        self.assertContains(attendee_response, "Paid")
