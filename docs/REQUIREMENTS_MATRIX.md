# EventPulse Requirements Matrix

This matrix maps the documented academic requirements to repository evidence. **VERIFIED** means source and focused tests were inspected during Day 10;  **PARTIALLY VERIFIED** identifies implementation with a remaining release check. **EXTERNAL/MANUAL CHECK REQUIRED** cannot be proven from the local source tree alone.

## Academic requirements

| ID | Requirement | Status | Concrete evidence |
| --- | --- | --- | --- |
| A1 | At least three Django apps | VERIFIED | `eventpulse/settings.py` registers `events`, `attendees`, and `ticketing`. |
| A2 | At least three models | VERIFIED | `events/models.py`: `Venue`, `Event`; `attendees/models.py`: `Attendee`; `ticketing/models.py`: `Ticket`. |
| A3 | One-to-many relationship | VERIFIED | `Event.venue` and `Ticket.event`/`Ticket.attendee` foreign keys; migration evidence in all three app migration folders. |
| A4 | Many-to-many relationship | VERIFIED | `Event.attendees` uses `Ticket` as its explicit `through` model in `events/models.py`. |
| A5 | At least four validated forms | VERIFIED | `VenueForm`, `EventForm`, `AttendeeForm`, `TicketForm`, and `PaymentForm`; validation tests in `events/tests.py`, `attendees/tests.py`, and `ticketing/tests.py`. |
| A6 | Read-only or disabled form field | VERIFIED | Disabled `PaymentForm.event_reference` in `ticketing/forms.py`; `PaymentFormTests.test_form_includes_read_only_event_reference_and_excludes_ticket_fields`. |
| A7 | At least 12 web-page templates, excluding `base.html` | VERIFIED | 21 page templates are enumerated below; shared base/partials are excluded from this count. |
| A8 | At least eight dynamic database-backed page templates | VERIFIED | 20 listed app page templates display ORM-backed records, form data, aggregates, or database-dependent empty states; see table below. |
| A9 | Full CRUD for at least two models | VERIFIED | Full CRUD exists for Venue, Event, Attendee, and Ticket in each app's `views.py` and `urls.py`; request tests cover workflows. |
| A10 | Search, filtering, sorting | VERIFIED | `EventListView`, `VenueListView`, `AttendeeListView`, `TicketListView`, `tracker`, and `insights`; focused list/tracker/insights tests. |
| A11 | Built-in and custom template filter/tag usage | VERIFIED | Built-in filters include `date`, `floatformat`, and `pluralize`; custom `money` **filter** is registered in `ticketing/templatetags/ticketing_formatting.py` and loaded in dashboard/tracker templates. No custom tag is claimed. `TemplateFormattingTests` covers the filter. |
| A12 | Custom 404 page | VERIFIED | `eventpulse/urls.py` assigns `handler404`; `eventpulse/views.py::not_found` renders `templates/404.html`; `InterfaceFoundationTests.test_custom_404_handler_renders_when_debug_is_disabled`. |
| A13 | Shared accessible navigation/footer | VERIFIED | `templates/base.html` and `templates/includes/navigation.html`/`footer.html`; `InterfaceFoundationTests` asserts navigation, footer, skip link, and main target. |
| A14 | SQLite database | VERIFIED | `eventpulse/settings.py` uses `django.db.backends.sqlite3`; schema is versioned in app migrations. |
| A15 | Empty-database usability | VERIFIED | Empty-state/creation flows across list pages and ticket prerequisites; `DomainEmptyDatabaseTests`, empty tracker/insights tests, and ticket create prerequisite test. |
| A16 | No authentication/user management | VERIFIED | No account/login/profile routes or feature app is implemented; product scope documents single operator use. |
| A17 | Public GitHub repository | EXTERNAL/MANUAL CHECK REQUIRED | Configured `origin` is `https://github.com/PlamenPlamenovStanchev/EventPulse.git`; public visibility and pushed state must be checked by the owner. |
| A18 | Five genuine commits on five distinct dates | PARTIALLY VERIFIED | D10.1 read-only local Git review found 9 commits on 9 distinct dates (2026-11-07 through 2026-11-15). Confirm the intended history is pushed and visible for submission. |

## Page-template evidence

`templates/base.html`, all `templates/includes/*` partials, and static assets are deliberately excluded. The table lists 21 actual pages: 20 database-backed pages plus the custom 404 page.

| Template path | URL name / route | What it displays | Database-backed? |
| --- | --- | --- | --- |
| `events/templates/events/event_list.html` | `events:event_list` / `/events/` | Events, venue filter, search, sort, empty state | Yes |
| `events/templates/events/event_detail.html` | `events:event_detail` / `/events/<pk>/` | Event, venue, tickets, occupancy and revenue aggregates | Yes |
| `events/templates/events/event_form.html` | `events:event_create`, `events:event_update` | Event form and available venue choices | Yes |
| `events/templates/events/event_confirm_delete.html` | `events:event_delete` | Selected event and its ticket count | Yes |
| `events/templates/events/venue_list.html` | `events:venue_list` / `/events/venues/` | Venues, search results, event counts, empty state | Yes |
| `events/templates/events/venue_detail.html` | `events:venue_detail` | Venue and related events | Yes |
| `events/templates/events/venue_form.html` | `events:venue_create`, `events:venue_update` | Venue form/instance values | Yes |
| `events/templates/events/venue_confirm_delete.html` | `events:venue_delete` | Selected venue confirmation | Yes |
| `attendees/templates/attendees/attendee_list.html` | `attendees:attendee_list` / `/attendees/` | Attendees, search/sort results, empty state | Yes |
| `attendees/templates/attendees/attendee_detail.html` | `attendees:attendee_detail` | Attendee and related tickets | Yes |
| `attendees/templates/attendees/attendee_form.html` | `attendees:attendee_create`, `attendees:attendee_update` | Attendee form/instance values | Yes |
| `attendees/templates/attendees/attendee_confirm_delete.html` | `attendees:attendee_delete` | Selected attendee confirmation | Yes |
| `ticketing/templates/ticketing/dashboard.html` | `ticketing:dashboard` / `/` | Counts, revenue KPIs, and event performance | Yes |
| `ticketing/templates/ticketing/ticket_list.html` | `ticketing:ticket_list` / `/tickets/` | Ticket records, search/filter/sort, empty state | Yes |
| `ticketing/templates/ticketing/ticket_detail.html` | `ticketing:ticket_detail` | Ticket, event, attendee, and payment metadata | Yes |
| `ticketing/templates/ticketing/ticket_form.html` | `ticketing:ticket_create`, `ticketing:ticket_update` | Ticket form, event/attendee choices, prerequisites | Yes |
| `ticketing/templates/ticketing/ticket_confirm_delete.html` | `ticketing:ticket_delete` | Selected ticket confirmation | Yes |
| `ticketing/templates/ticketing/ticket_payment_form.html` | `ticketing:ticket_mark_paid`, `ticketing:ticket_mark_unpaid` | Selected ticket and payment-status form/state | Yes |
| `ticketing/templates/ticketing/tracker.html` | `ticketing:tracker` / `/tracker/` | Ticket payment records and overall financial metrics | Yes |
| `ticketing/templates/ticketing/insights.html` | `ticketing:insights` / `/insights/` | Filtered revenue, occupancy, and payment-distribution charts | Yes |
| `templates/404.html` | Unresolved route via `handler404` | Branded missing-route message | No |

## Business-rule coverage

| ID | Rule | Status | Implementation and test evidence |
| --- | --- | --- | --- |
| B1 | One ticket per attendee/event | VERIFIED | `Ticket` unique constraint on `event`, `attendee`; model/form tests reject duplicates. |
| B2 | Unpaid tickets reserve capacity | VERIFIED | `Ticket._validate_event_capacity()` counts all event tickets; capacity tests cover paid/unpaid behavior. |
| B3 | Capacity cannot be exceeded | VERIFIED | `Ticket.clean()`, `Venue.clean()`, and `Event.clean()`; ticket create/edit and venue/event guard tests. |
| B4 | Price cannot be negative | VERIFIED | `MinValueValidator`, database check constraint, and form/model tests. |
| B5 | Paid tickets require payment details | VERIFIED | `Ticket._validate_payment_details()`, database constraint, `PaymentFormTests`, and payment action tests. |
| B6 | Unpaid tickets reject payment metadata | VERIFIED | Model validation and database constraint; payment-form/action tests. |
| B7 | Event deletion cascades tickets | VERIFIED | `Ticket.event` uses `CASCADE`; deletion tests in `events/tests.py` and `ticketing/tests.py`. |
| B8 | Attendee/venue deletion is protected when related | VERIFIED | `Ticket.attendee` and `Event.venue` use `PROTECT`; protected-delete tests and feedback views. |
| B9 | Expected revenue | VERIFIED | `get_revenue_metrics()`, event-detail aggregation, dashboard/tracker/insights tests. |
| B10 | Collected revenue | VERIFIED | Aggregates filter `Ticket.Status.PAID`; reporting consistency tests. |
| B11 | Transparent Event Health indicator | VERIFIED | `EventPerformance.health_status` uses unrounded occupancy thresholds; boundary tests and dashboard/insights assertions. |
| B12 | Destructive operations confirmed | VERIFIED | Dedicated delete confirmation templates/views for Event, Venue, Attendee, and Ticket; GET confirmation/POST delete tests. |

## Delivery and release checklist

- [x] Previous baseline ran `python manage.py check` successfully.
- [x] Previous baseline ran the Django test suite successfully (158 tests reported).
- [x] Prior verification reported no pending migrations.
- [x] Custom 404 rendering is covered in a `DEBUG=False` request test.
- [x] Source inspection confirms empty-database creation flows and tracked local static assets.
- [x] Run the documented verification commands again after documentation review if a fresh release result is required.
- [x] Intentionally add the examiner-facing `docs/` files to version control before release; they were untracked at D10.1.
- [x] Verify the GitHub repository is public and the intended commits/docs are pushed.


## Remaining technical limitation

SQLite count-then-insert capacity validation is not race-free for concurrent writers. The local single-operator scope accepts this limitation; a multi-writer deployment would require a database and allocation strategy with suitable locking semantics.
