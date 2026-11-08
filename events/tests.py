from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.utils import timezone

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
