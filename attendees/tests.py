from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, Venue
from ticketing.models import Ticket

from .forms import AttendeeForm
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


class AttendeeFormTests(TestCase):
    def form_data(self, **overrides):
        data = {
            "name": "  Alex   Morgan  ",
            "email": "Alex.Morgan@Example.COM",
            "phone": "+44 20 7946 0958",
        }
        data.update(overrides)
        return data

    def create_attendee(self, **overrides):
        data = {
            "name": "Alex Morgan",
            "email": "alex@example.com",
            "phone": "+44 20 7946 0958",
        }
        data.update(overrides)
        return Attendee.objects.create(**data)

    def test_valid_form_normalizes_name_and_email(self):
        form = AttendeeForm(data=self.form_data())

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["name"], "Alex Morgan")
        self.assertEqual(form.cleaned_data["email"], "alex.morgan@example.com")

    def test_name_is_required_and_cannot_be_whitespace_only(self):
        missing_form = AttendeeForm(data=self.form_data(name=""))
        whitespace_form = AttendeeForm(data=self.form_data(name="   \t  "))

        self.assertFalse(missing_form.is_valid())
        self.assertEqual(missing_form.errors["name"], ["Enter the attendee's name."])
        self.assertFalse(whitespace_form.is_valid())
        self.assertEqual(whitespace_form.errors["name"], ["Enter the attendee's name."])

    def test_email_is_required_and_must_be_valid(self):
        missing_form = AttendeeForm(data=self.form_data(email=""))
        invalid_form = AttendeeForm(data=self.form_data(email="not-an-email"))

        self.assertFalse(missing_form.is_valid())
        self.assertEqual(missing_form.errors["email"], ["Enter an email address."])
        self.assertFalse(invalid_form.is_valid())
        self.assertEqual(invalid_form.errors["email"], ["Enter a valid email address."])

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.create_attendee()

        exact_form = AttendeeForm(data=self.form_data(email="alex@example.com"))
        different_case_form = AttendeeForm(data=self.form_data(email="ALEX@EXAMPLE.COM"))

        for form in (exact_form, different_case_form):
            self.assertFalse(form.is_valid())
            self.assertEqual(
                form.errors["email"],
                ["An attendee with this email address already exists."],
            )

    def test_editing_with_the_same_email_is_valid(self):
        attendee = self.create_attendee()

        form = AttendeeForm(
            data=self.form_data(email="ALEX@EXAMPLE.COM"), instance=attendee
        )

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["email"], "alex@example.com")

    def test_common_international_phone_formats_are_valid(self):
        phone_numbers = [
            "+44 20 7946 0958",
            "+1 (212) 555-0123",
            "+359 (2) 123-4567",
            "00359 2 123 4567",
        ]

        for phone_number in phone_numbers:
            with self.subTest(phone_number=phone_number):
                self.assertTrue(AttendeeForm(data=self.form_data(phone=phone_number)).is_valid())

    def test_invalid_phone_input_is_rejected(self):
        form = AttendeeForm(data=self.form_data(phone="call Alex"))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["phone"], ["Enter a valid phone number."])

    def test_field_labels_and_error_messages_are_clear(self):
        form = AttendeeForm(data=self.form_data(phone=""))

        self.assertEqual(form.fields["name"].label, "Full name")
        self.assertEqual(form.fields["email"].label, "Email address")
        self.assertEqual(form.fields["phone"].label, "Phone number")
        self.assertEqual(
            form.fields["name"].widget.attrs["placeholder"], "e.g. Alex Morgan"
        )
        self.assertEqual(
            form.fields["email"].help_text,
            "Use an email address the attendee can access.",
        )
        self.assertEqual(
            form.fields["phone"].help_text,
            "Include the country code when available.",
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["phone"], ["Enter a phone number."])


class AttendeeCrudViewTests(TestCase):
    def create_attendee(self, **overrides):
        values = {
            "name": "Alex Morgan",
            "email": "alex@example.com",
            "phone": "+44 20 7946 0958",
        }
        values.update(overrides)
        return Attendee.objects.create(**values)

    def create_ticket_for(self, attendee):
        venue = Venue.objects.create(
            name="Riverside Hall", address="1 Main Street", capacity=100
        )
        event = Event.objects.create(
            name="Autumn Conference",
            starts_at=timezone.now(),
            description="A one-day conference.",
            venue=venue,
        )
        return Ticket.objects.create(event=event, attendee=attendee, price=Decimal("25.00"))

    def test_empty_list_offers_add_action_and_navigation(self):
        response = self.client.get(reverse("attendees:attendee_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create your first attendee")
        self.assertContains(response, reverse("attendees:attendee_create"))
        self.assertContains(response, reverse("events:event_list"))
        self.assertContains(response, 'aria-current="page"')

    def test_list_and_detail_show_attendee_and_persisted_ticket(self):
        attendee = self.create_attendee()
        ticket = self.create_ticket_for(attendee)

        list_response = self.client.get(reverse("attendees:attendee_list"))
        detail_response = self.client.get(
            reverse("attendees:attendee_detail", args=[attendee.pk])
        )

        self.assertContains(list_response, attendee.name)
        self.assertContains(list_response, attendee.email)
        self.assertContains(list_response, attendee.phone)
        self.assertContains(detail_response, ticket.event.name)
        self.assertContains(detail_response, "Unpaid")

    def test_detail_shows_empty_ticket_state(self):
        attendee = self.create_attendee()

        response = self.client.get(reverse("attendees:attendee_detail", args=[attendee.pk]))

        self.assertContains(response, "does not have any tickets yet")

    def test_create_normalizes_data_redirects_and_sets_success_message(self):
        response = self.client.post(
            reverse("attendees:attendee_create"),
            {
                "name": "  Alex   Morgan ",
                "email": "ALEX@EXAMPLE.COM",
                "phone": "+44 20 7946 0958",
            },
            follow=True,
        )

        attendee = Attendee.objects.get()
        self.assertEqual(attendee.name, "Alex Morgan")
        self.assertEqual(attendee.email, "alex@example.com")
        self.assertRedirects(
            response, reverse("attendees:attendee_detail", args=[attendee.pk]), 302, 200
        )
        self.assertContains(response, "Attendee created successfully.")

    def test_update_persists_changes_redirects_and_sets_success_message(self):
        attendee = self.create_attendee()

        response = self.client.post(
            reverse("attendees:attendee_update", args=[attendee.pk]),
            {
                "name": "Alexandra Morgan",
                "email": "alexandra@example.com",
                "phone": "+359 (2) 123-4567",
            },
            follow=True,
        )

        attendee.refresh_from_db()
        self.assertRedirects(
            response, reverse("attendees:attendee_detail", args=[attendee.pk]), 302, 200
        )
        self.assertEqual(attendee.name, "Alexandra Morgan")
        self.assertEqual(attendee.email, "alexandra@example.com")
        self.assertContains(response, "Attendee updated successfully.")

    def test_invalid_submission_does_not_save(self):
        response = self.client.post(
            reverse("attendees:attendee_create"),
            {"name": "", "email": "not-an-email", "phone": "invalid"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter the attendee")
        self.assertContains(response, "Enter a valid email address.")
        self.assertContains(response, "Enter a valid phone number.")
        self.assertFalse(Attendee.objects.exists())

    def test_delete_requires_post_and_deletes_an_attendee_without_tickets(self):
        attendee = self.create_attendee()
        delete_url = reverse("attendees:attendee_delete", args=[attendee.pk])

        get_response = self.client.get(delete_url)
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Confirm deletion")
        self.assertTrue(Attendee.objects.filter(pk=attendee.pk).exists())

        post_response = self.client.post(delete_url, follow=True)
        self.assertRedirects(post_response, reverse("attendees:attendee_list"), 302, 200)
        self.assertFalse(Attendee.objects.filter(pk=attendee.pk).exists())
        self.assertContains(post_response, "Attendee deleted successfully.")

    def test_delete_with_associated_ticket_is_rejected_without_modifying_ticket(self):
        attendee = self.create_attendee()
        ticket = self.create_ticket_for(attendee)

        response = self.client.post(
            reverse("attendees:attendee_delete", args=[attendee.pk]), follow=True
        )

        self.assertRedirects(
            response, reverse("attendees:attendee_detail", args=[attendee.pk]), 302, 200
        )
        self.assertTrue(Attendee.objects.filter(pk=attendee.pk).exists())
        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())
        self.assertContains(response, "cannot be deleted because one or more tickets reference them")

    def test_delete_is_protected_when_ticket_is_added_after_confirmation(self):
        attendee = self.create_attendee()
        delete_url = reverse("attendees:attendee_delete", args=[attendee.pk])

        self.client.get(delete_url)
        ticket = self.create_ticket_for(attendee)
        response = self.client.post(delete_url, follow=True)

        self.assertRedirects(
            response, reverse("attendees:attendee_detail", args=[attendee.pk]), 302, 200
        )
        self.assertTrue(Attendee.objects.filter(pk=attendee.pk).exists())
        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())
        self.assertContains(response, "cannot be deleted because one or more tickets reference them")

    def test_missing_attendee_returns_404(self):
        response = self.client.get(reverse("attendees:attendee_detail", args=[999]))

        self.assertEqual(response.status_code, 404)


class AttendeeListControlsTests(TestCase):
    def setUp(self):
        self.alex = Attendee.objects.create(
            name="Alex Morgan", email="alex@example.com", phone="+44 20 7946 0958"
        )
        self.blair = Attendee.objects.create(
            name="Blair Stone", email="blair@example.com", phone="+359 2 123 4567"
        )
        self.zoe = Attendee.objects.create(
            name="Zoe Archer", email="zoe@example.com", phone="+1 212 555 0123"
        )

    def test_search_matches_name_email_phone_and_case_insensitive_text(self):
        name_response = self.client.get(reverse("attendees:attendee_list"), {"q": "MORGAN"})
        email_response = self.client.get(
            reverse("attendees:attendee_list"), {"q": "BLAIR@EXAMPLE.COM"}
        )
        phone_response = self.client.get(
            reverse("attendees:attendee_list"), {"q": "359 2"}
        )

        self.assertEqual(list(name_response.context["attendees"]), [self.alex])
        self.assertEqual(list(email_response.context["attendees"]), [self.blair])
        self.assertEqual(list(phone_response.context["attendees"]), [self.blair])

    def test_no_results_state_offers_clear_search(self):
        response = self.client.get(reverse("attendees:attendee_list"), {"q": "nobody"})

        self.assertEqual(list(response.context["attendees"]), [])
        self.assertContains(response, "No attendees match this search")
        self.assertContains(response, "Clear search")

    def test_allowlisted_sorting_orders_attendees_correctly(self):
        expected_orderings = {
            "name": [self.alex, self.blair, self.zoe],
            "-name": [self.zoe, self.blair, self.alex],
            "email": [self.alex, self.blair, self.zoe],
            "-email": [self.zoe, self.blair, self.alex],
        }

        for sort_option, expected_attendees in expected_orderings.items():
            with self.subTest(sort_option=sort_option):
                response = self.client.get(
                    reverse("attendees:attendee_list"), {"sort": sort_option}
                )
                self.assertEqual(list(response.context["attendees"]), expected_attendees)
                self.assertEqual(response.context["sort"], sort_option)

    def test_invalid_sorting_falls_back_to_name_ascending(self):
        response = self.client.get(
            reverse("attendees:attendee_list"), {"sort": "name; DROP TABLE attendees"}
        )

        self.assertEqual(list(response.context["attendees"]), [self.alex, self.blair, self.zoe])
        self.assertEqual(response.context["sort"], "name")

    def test_search_query_is_preserved_when_sorting(self):
        response = self.client.get(
            reverse("attendees:attendee_list"), {"q": "Alex", "sort": "-email"}
        )

        self.assertEqual(list(response.context["attendees"]), [self.alex])
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'value="Alex"')
        self.assertContains(response, '<option value="-email" selected>')

    def test_list_uses_accessible_responsive_table_and_navigation_markup(self):
        response = self.client.get(reverse("attendees:attendee_list"))

        self.assertContains(response, 'aria-label="Search and sort attendees"')
        self.assertContains(response, 'for="attendee-search"')
        self.assertContains(response, 'class="table-wrap"')
        self.assertContains(response, 'data-label="Actions"')
        self.assertContains(response, 'aria-current="page"')
