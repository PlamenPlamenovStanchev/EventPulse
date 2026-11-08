from django.db import models


class Attendee(models.Model):
    """A reusable contact record for a person attending events."""

    name = models.CharField(
        max_length=150,
        verbose_name="attendee name",
        help_text="The attendee's full name.",
        error_messages={"blank": "Enter the attendee's name."},
    )
    email = models.EmailField(
        unique=True,
        verbose_name="email address",
        help_text="The attendee's primary contact email address.",
        error_messages={
            "blank": "Enter an email address.",
            "invalid": "Enter a valid email address.",
            "unique": "An attendee with this email address already exists.",
        },
    )
    phone = models.CharField(
        max_length=30,
        verbose_name="phone number",
        help_text="The attendee's primary phone number.",
        error_messages={"blank": "Enter a phone number."},
    )

    class Meta:
        ordering = ["name", "email"]
        verbose_name = "attendee"
        verbose_name_plural = "attendees"

    def __str__(self):
        return self.name
