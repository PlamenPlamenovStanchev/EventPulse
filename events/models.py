from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class Venue(models.Model):
    """A location that can host one or more events.

    Capacity cannot be reduced below tickets issued across its events.
    """

    name = models.CharField(
        max_length=150,
        verbose_name="venue name",
        help_text="The public name of this venue.",
        error_messages={"blank": "Enter a venue name."},
    )
    address = models.CharField(
        max_length=255,
        verbose_name="address",
        help_text="The venue's street address or location details.",
        error_messages={"blank": "Enter the venue address."},
    )
    capacity = models.PositiveIntegerField(
        verbose_name="capacity",
        help_text="Maximum number of ticket reservations. It must be at least 1.",
        validators=[MinValueValidator(1, message="Venue capacity must be at least 1.")],
        error_messages={"blank": "Enter the venue capacity."},
    )
    description = models.TextField(
        blank=True,
        verbose_name="description",
        help_text="Optional details that help identify or operate the venue.",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "venue"
        verbose_name_plural = "venues"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(capacity__gte=1),
                name="venue_capacity_at_least_one",
            )
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.pk and self.events.filter(tickets__isnull=False).count() > self.capacity:
            raise ValidationError(
                {"capacity": "Capacity cannot be lower than tickets already issued."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Event(models.Model):
    """A scheduled event hosted at a venue."""

    name = models.CharField(
        max_length=180,
        verbose_name="event name",
        help_text="The name displayed for this event.",
        error_messages={"blank": "Enter an event name."},
    )
    starts_at = models.DateTimeField(
        verbose_name="starts at",
        help_text="The scheduled start date and time for the event.",
        error_messages={"blank": "Enter when the event starts."},
    )
    description = models.TextField(
        verbose_name="description",
        help_text="Details attendees and staff need about this event.",
        error_messages={"blank": "Enter an event description."},
    )
    venue = models.ForeignKey(
        Venue,
        on_delete=models.PROTECT,
        related_name="events",
        verbose_name="venue",
        help_text="The venue hosting this event.",
    )
    attendees = models.ManyToManyField(
        "attendees.Attendee",
        through="ticketing.Ticket",
        related_name="events",
        verbose_name="attendees",
        help_text="Attendees with tickets for this event.",
    )

    class Meta:
        ordering = ["starts_at", "name"]
        verbose_name = "event"
        verbose_name_plural = "events"

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.pk and self.tickets.count() > self.venue.capacity:
            raise ValidationError(
                {"venue": "The selected venue cannot hold this event's issued tickets."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
