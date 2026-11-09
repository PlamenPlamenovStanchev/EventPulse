from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils import timezone

from attendees.models import Attendee
from ticketing.models import Ticket

from .models import Event, Venue


class VenueModelTests(TestCase):
    def test_required_fields_are_validated(self):
        venue = Venue(capacity=1)

        with self.assertRaises(ValidationError) as context:
            venue.full_clean()

        self.assertIn("name", context.exception.message_dict)
        self.assertIn("address", context.exception.message_dict)

    def test_capacity_must_be_at_least_one(self):
        venue = Venue(name="Hall", address="1 Main Street", capacity=0)

        with self.assertRaises(ValidationError) as context:
            venue.full_clean()

        self.assertEqual(
            context.exception.message_dict["capacity"],
            ["Venue capacity must be at least 1."],
        )

    def test_capacity_database_constraint_rejects_zero(self):
        with self.assertRaises(IntegrityError):
            Venue.objects.bulk_create(
                [Venue(name="Hall", address="1 Main Street", capacity=0)]
            )

    def test_string_representation_is_venue_name(self):
        venue = Venue.objects.create(
            name="Riverside Hall", address="1 Main Street", capacity=100
        )

        self.assertEqual(str(venue), "Riverside Hall")


class EventModelTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(
            name="Riverside Hall", address="1 Main Street", capacity=100
        )

    def test_required_fields_are_validated(self):
        event = Event(venue=self.venue)

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        self.assertIn("name", context.exception.message_dict)
        self.assertIn("starts_at", context.exception.message_dict)
        self.assertIn("description", context.exception.message_dict)

    def test_event_relationship_uses_protected_venue(self):
        event = Event.objects.create(
            name="Autumn Conference",
            starts_at=timezone.now(),
            description="A one-day conference.",
            venue=self.venue,
        )

        self.assertEqual(self.venue.events.get(), event)
        with self.assertRaises(ProtectedError):
            self.venue.delete()

    def test_string_representation_is_event_name(self):
        event = Event.objects.create(
            name="Autumn Conference",
            starts_at=timezone.now(),
            description="A one-day conference.",
            venue=self.venue,
        )

        self.assertEqual(str(event), "Autumn Conference")


class VenueCrudViewTests(TestCase):
    def create_venue(self, **overrides):
        values = {
            "name": "Riverside Hall",
            "address": "1 Main Street",
            "capacity": 100,
            "description": "Step-free entrance.",
        }
        values.update(overrides)
        return Venue.objects.create(**values)

    def test_empty_list_shows_create_action_and_navigation(self):
        response = self.client.get(reverse("events:venue_list"))

        self.assertContains(response, "Create your first venue")
        self.assertContains(response, reverse("events:venue_create"))
        self.assertContains(response, 'aria-current="page"')

    def test_list_and_detail_display_venue_and_related_events(self):
        venue = self.create_venue()
        Event.objects.create(
            name="Autumn Conference",
            starts_at=timezone.now(),
            description="A one-day conference.",
            venue=venue,
        )

        list_response = self.client.get(reverse("events:venue_list"))
        detail_response = self.client.get(reverse("events:venue_detail", args=[venue.pk]))

        self.assertContains(list_response, "Riverside Hall")
        self.assertContains(list_response, ">1<")
        self.assertContains(detail_response, "Step-free entrance.")
        self.assertContains(detail_response, "Autumn Conference")

    def test_create_uses_post_and_redirects_to_detail(self):
        create_url = reverse("events:venue_create")

        get_response = self.client.get(create_url)
        post_response = self.client.post(
            create_url,
            {
                "name": "  City   Gallery  ",
                "address": "  50   Art Lane ",
                "capacity": 250,
                "description": "",
            },
        )

        venue = Venue.objects.get()
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(venue.name, "City Gallery")
        self.assertEqual(venue.address, "50 Art Lane")
        self.assertRedirects(post_response, reverse("events:venue_detail", args=[venue.pk]))

    def test_update_redirects_and_persists_changes(self):
        venue = self.create_venue()

        response = self.client.post(
            reverse("events:venue_update", args=[venue.pk]),
            {
                "name": "Riverside Hall",
                "address": "10 River Road",
                "capacity": 180,
                "description": "Updated notes.",
            },
        )

        venue.refresh_from_db()
        self.assertRedirects(response, reverse("events:venue_detail", args=[venue.pk]))
        self.assertEqual(venue.capacity, 180)
        self.assertEqual(venue.address, "10 River Road")

    def test_invalid_capacity_and_required_fields_return_form_errors(self):
        response = self.client.post(
            reverse("events:venue_create"),
            {"name": "", "address": "", "capacity": 0, "description": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a venue name.")
        self.assertContains(response, "Enter the venue address.")
        self.assertContains(response, "Venue capacity must be at least 1.")
        self.assertFalse(Venue.objects.exists())

    def test_delete_requires_confirmation_and_post_deletes_unrelated_venue(self):
        venue = self.create_venue()
        delete_url = reverse("events:venue_delete", args=[venue.pk])

        get_response = self.client.get(delete_url)
        post_response = self.client.post(delete_url)

        self.assertContains(get_response, "Confirm deletion")
        self.assertRedirects(post_response, reverse("events:venue_list"))
        self.assertFalse(Venue.objects.filter(pk=venue.pk).exists())

    def test_delete_of_venue_with_events_shows_helpful_message(self):
        venue = self.create_venue()
        Event.objects.create(
            name="Autumn Conference",
            starts_at=timezone.now(),
            description="A one-day conference.",
            venue=venue,
        )

        response = self.client.post(
            reverse("events:venue_delete", args=[venue.pk]), follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Venue.objects.filter(pk=venue.pk).exists())
        self.assertContains(response, "cannot be deleted because one or more events reference it")


class EventCrudViewTests(TestCase):
    def create_venue(self, name="Riverside Hall", capacity=100):
        return Venue.objects.create(
            name=name, address="1 Main Street", capacity=capacity
        )

    def create_event(self, venue, **overrides):
        values = {
            "name": "Autumn Conference",
            "starts_at": timezone.now(),
            "description": "A one-day conference.",
            "venue": venue,
        }
        values.update(overrides)
        return Event.objects.create(**values)

    def create_ticket(self, event, email, price, **overrides):
        attendee = Attendee.objects.create(
            name=email.split("@")[0].title(), email=email, phone="555-0100"
        )
        values = {"event": event, "attendee": attendee, "price": price}
        values.update(overrides)
        return Ticket.objects.create(**values)

    def test_empty_list_and_create_form_offer_venue_creation(self):
        list_response = self.client.get(reverse("events:event_list"))
        form_response = self.client.get(reverse("events:event_create"))

        self.assertContains(list_response, "Create your first event")
        self.assertContains(list_response, reverse("events:venue_create"))
        self.assertContains(form_response, "Create a venue first")
        self.assertContains(form_response, reverse("events:venue_create"))
        self.assertFalse(Event.objects.exists())

    def test_valid_creation_selects_venue_and_redirects(self):
        venue = self.create_venue()
        create_url = reverse("events:event_create")

        form_response = self.client.get(create_url)
        post_response = self.client.post(
            create_url,
            {
                "name": "  Autumn   Conference ",
                "starts_at": "2026-12-10T09:30",
                "venue": venue.pk,
                "description": "  A   one-day conference. ",
            },
        )

        event = Event.objects.get()
        self.assertContains(form_response, 'type="datetime-local"')
        self.assertContains(form_response, f'value="{venue.pk}"')
        self.assertEqual(event.name, "Autumn Conference")
        self.assertEqual(event.description, "A one-day conference.")
        self.assertEqual(event.venue, venue)
        self.assertTrue(timezone.is_aware(event.starts_at))
        self.assertRedirects(post_response, reverse("events:event_detail", args=[event.pk]))

    def test_invalid_creation_returns_friendly_required_errors(self):
        venue = self.create_venue()

        response = self.client.post(
            reverse("events:event_create"),
            {"name": "", "starts_at": "", "venue": venue.pk, "description": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter an event name.")
        self.assertContains(response, "Enter when the event starts.")
        self.assertContains(response, "Enter event details.")
        self.assertFalse(Event.objects.exists())

    def test_edit_persists_changes_and_supports_sufficient_reassignment(self):
        source = self.create_venue("Source Hall", capacity=2)
        destination = self.create_venue("Destination Hall", capacity=3)
        event = self.create_event(source)
        self.create_ticket(event, "alex@example.com", Decimal("15.00"))
        self.create_ticket(event, "blake@example.com", Decimal("20.00"))

        response = self.client.post(
            reverse("events:event_update", args=[event.pk]),
            {
                "name": "Winter Conference",
                "starts_at": "2026-12-15T10:00",
                "venue": destination.pk,
                "description": "Updated schedule.",
            },
        )

        event.refresh_from_db()
        self.assertRedirects(response, reverse("events:event_detail", args=[event.pk]))
        self.assertEqual(event.venue, destination)
        self.assertEqual(event.name, "Winter Conference")

    def test_reassignment_to_undersized_venue_is_rejected(self):
        source = self.create_venue("Source Hall", capacity=2)
        too_small = self.create_venue("Small Hall", capacity=1)
        event = self.create_event(source)
        self.create_ticket(event, "alex@example.com", Decimal("15.00"))
        self.create_ticket(event, "blake@example.com", Decimal("20.00"))

        response = self.client.post(
            reverse("events:event_update", args=[event.pk]),
            {
                "name": event.name,
                "starts_at": "2026-12-15T10:00",
                "venue": too_small.pk,
                "description": event.description,
            },
        )

        event.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot hold this event")
        self.assertEqual(event.venue, source)

    def test_detail_calculates_persisted_ticket_metrics_and_zero_ticket_values(self):
        venue = self.create_venue(capacity=4)
        event = self.create_event(venue)
        self.create_ticket(
            event,
            "alex@example.com",
            Decimal("20.00"),
            status=Ticket.Status.PAID,
            payment_date=date(2026, 12, 1),
            payment_method=Ticket.PaymentMethod.CARD,
        )
        self.create_ticket(event, "blake@example.com", Decimal("15.00"))

        response = self.client.get(reverse("events:event_detail", args=[event.pk]))
        zero_event = self.create_event(venue, name="Planning Session")
        zero_response = self.client.get(reverse("events:event_detail", args=[zero_event.pk]))

        self.assertContains(response, ">2<")
        self.assertContains(response, "50%")
        self.assertContains(response, "35.00")
        self.assertContains(response, "20.00")
        self.assertContains(zero_response, ">0<")
        self.assertContains(zero_response, "0%")
        self.assertContains(zero_response, "0.00")

    def test_delete_confirmation_and_post_cascade_preserve_venue_and_attendee(self):
        venue = self.create_venue()
        event = self.create_event(venue)
        ticket = self.create_ticket(event, "alex@example.com", Decimal("20.00"))
        attendee = ticket.attendee
        delete_url = reverse("events:event_delete", args=[event.pk])

        get_response = self.client.get(delete_url)
        self.assertContains(get_response, "1 associated ticket")
        self.assertTrue(Event.objects.filter(pk=event.pk).exists())
        post_response = self.client.post(delete_url)

        self.assertRedirects(post_response, reverse("events:event_list"))
        self.assertFalse(Event.objects.filter(pk=event.pk).exists())
        self.assertFalse(Ticket.objects.filter(pk=ticket.pk).exists())
        self.assertTrue(Venue.objects.filter(pk=venue.pk).exists())
        self.assertTrue(Attendee.objects.filter(pk=attendee.pk).exists())


class EventAndVenueListControlsTests(TestCase):
    def setUp(self):
        self.riverside = Venue.objects.create(
            name="Riverside Hall", address="1 Main Street", capacity=100
        )
        self.central = Venue.objects.create(
            name="Central Gallery", address="50 Art Avenue", capacity=80
        )
        self.autumn = Event.objects.create(
            name="Autumn Conference",
            starts_at=timezone.make_aware(datetime(2026, 10, 10, 9, 0)),
            description="Conference programme.",
            venue=self.riverside,
        )
        self.spring = Event.objects.create(
            name="Spring Forum",
            starts_at=timezone.make_aware(datetime(2026, 4, 10, 9, 0)),
            description="Forum programme.",
            venue=self.central,
        )

    def test_event_search_and_venue_filter_use_get_parameters(self):
        search_response = self.client.get(
            reverse("events:event_list"), {"q": "autumn"}
        )
        venue_response = self.client.get(
            reverse("events:event_list"), {"venue": self.central.pk}
        )

        self.assertEqual(list(search_response.context["events"]), [self.autumn])
        self.assertEqual(list(venue_response.context["events"]), [self.spring])
        self.assertContains(search_response, 'name="q"')
        self.assertContains(venue_response, 'name="venue"')

    def test_event_sorting_is_chronological_in_both_directions(self):
        earliest_response = self.client.get(reverse("events:event_list"))
        latest_response = self.client.get(
            reverse("events:event_list"), {"sort": "-date"}
        )

        self.assertEqual(list(earliest_response.context["events"]), [self.spring, self.autumn])
        self.assertEqual(list(latest_response.context["events"]), [self.autumn, self.spring])

    def test_venue_search_matches_name_or_address(self):
        name_response = self.client.get(reverse("events:venue_list"), {"q": "central"})
        address_response = self.client.get(reverse("events:venue_list"), {"q": "main street"})

        self.assertEqual(list(name_response.context["venues"]), [self.central])
        self.assertEqual(list(address_response.context["venues"]), [self.riverside])

    def test_list_templates_include_labeled_controls_and_valid_actions(self):
        event_response = self.client.get(reverse("events:event_list"))
        venue_response = self.client.get(reverse("events:venue_list"))

        self.assertContains(event_response, "Event name")
        self.assertContains(event_response, "Description")
        self.assertContains(event_response, reverse("events:event_create"))
        self.assertContains(event_response, reverse("events:event_detail", args=[self.autumn.pk]))
        self.assertContains(event_response, reverse("events:event_update", args=[self.autumn.pk]))
        self.assertContains(event_response, reverse("events:event_delete", args=[self.autumn.pk]))
        self.assertContains(venue_response, "Venue name")
        self.assertContains(venue_response, "Event count")
        self.assertContains(venue_response, reverse("events:venue_create"))
        self.assertContains(venue_response, reverse("events:venue_detail", args=[self.riverside.pk]))
        self.assertContains(venue_response, reverse("events:venue_update", args=[self.riverside.pk]))
        self.assertContains(venue_response, reverse("events:venue_delete", args=[self.riverside.pk]))
