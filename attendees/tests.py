from django.test import TestCase
from django.core.exceptions import ValidationError

from .models import Attendee



class AttendeeModelTests(TestCase):
    def test_required_fields_are_validated(self):
        attendee = Attendee()

        with self.assertRaises(ValidationError) as context:
            attendee.full_clean()

        self.assertIn("name", context.exception.message_dict)
        self.assertIn("email", context.exception.message_dict)
        self.assertIn("phone", context.exception.message_dict)

    def test_email_is_unique(self):
        Attendee.objects.create(
            name="Alex Morgan", email="alex@example.com", phone="555-0100"
        )
        duplicate = Attendee(
            name="Alexandra Morgan", email="alex@example.com", phone="555-0101"
        )

        with self.assertRaises(ValidationError) as context:
            duplicate.full_clean()

        self.assertIn("email", context.exception.message_dict)

    def test_string_representation_is_name(self):
        attendee = Attendee.objects.create(
            name="Alex Morgan", email="alex@example.com", phone="555-0100"
        )

        self.assertEqual(str(attendee), "Alex Morgan")
