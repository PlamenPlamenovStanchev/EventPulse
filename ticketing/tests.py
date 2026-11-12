from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

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
