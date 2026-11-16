# EventPulse Product Specification

## 1. Product overview

EventPulse is an internal Event Operations & Revenue Intelligence Platform for a single event organizer. It centralizes the data needed to plan events, allocate finite venue capacity, register attendees, issue tickets, record payments, and assess operational health.

The system has no authentication, roles, or user-management workflows. Its scope is a single organizer’s operational environment.

## 2. Goals

- Give the organizer a reliable record of venues, events, attendees, tickets, and payments.
- Prevent overselling and invalid payment records before data is saved.
- Make expected revenue, collected revenue, unpaid exposure, and occupancy visible.
- Support day-to-day operation with searchable, filterable, sortable list views and clear creation flows.
- Keep destructive actions deliberate through confirmation pages.

## 3. Application boundaries

| Application | Owns | Key responsibilities |
| --- | --- | --- |
| `events` | `Venue`, `Event` | Venue records, event scheduling, event capacity context |
| `attendees` | `Attendee` | Reusable attendee directory and attendee lifecycle |
| `ticketing` | `Ticket` and reporting UI | Ticket issuance, payments, dashboard, tracker, and insights |

The project configuration package is `eventpulse`. It is generated project infrastructure, not a feature app, and must not be renamed.

## 4. Domain model

### Venue

| Field | Type/constraint | Purpose |
| --- | --- | --- |
| `name` | required | Venue display name |
| `address` | required | Venue location |
| `capacity` | required positive integer (minimum 1) | Maximum number of ticket reservations |
| `description` | optional | Supplemental venue details |

### Event

| Field | Type/constraint | Purpose |
| --- | --- | --- |
| `name` | required | Event name |
| `starts_at` | required datetime | Scheduled start |
| `description` | required | Event details |
| `venue` | required foreign key, `PROTECT` | Venue hosting the event |

### Attendee

| Field | Type/constraint | Purpose |
| --- | --- | --- |
| `name` | required | Attendee name |
| `email` | required, unique | Primary attendee contact and identifier |
| `phone` | required | Attendee phone number |

### Ticket

| Field | Type/constraint | Purpose |
| --- | --- | --- |
| `event` | required foreign key, `CASCADE` | Event reserved by the ticket |
| `attendee` | required foreign key, `PROTECT` | Ticket holder |
| `price` | required, decimal, non-negative | Ticket value |
| `status` | required: `PAID` or `UNPAID` | Payment state |
| `payment_date` | nullable date | Date payment was received |
| `payment_method` | nullable | Payment channel or method |
| `created_at` | auto-created timestamp | Audit and ordering data |

`Ticket` is the explicit many-to-many join between `Event` and `Attendee`. It carries the ticket and payment attributes, so it must be the relationship’s `through` model. An event owns many tickets and an attendee can hold tickets for multiple events.

### Implemented data-layer safeguards

- `Event.attendees` uses `Ticket` as its explicit through model. A database unique constraint permits at most one ticket for an attendee/event pair.
- `Ticket.event` cascades on event deletion; `Ticket.attendee` and `Event.venue` use `PROTECT`.
- Venue capacity is at least one at model and database levels. Ticket price is nonnegative at model and database levels.
- Ticket model validation counts every ticket status for capacity. It validates creates and event changes, excluding the edited ticket from its own capacity count.
- A venue cannot be reduced below its issued-ticket count, and an event cannot move to a venue too small for its existing tickets.
- Paid tickets require both payment date and method. Unpaid tickets reject payment metadata; the data layer does not silently clear it.
- Ordinary `save()` paths call `full_clean()` for `Venue`, `Event`, and `Ticket`; database constraints provide a backstop for direct bulk writes where applicable. Queryset updates and bulk writes are not supported ticket-issuance paths because they bypass model validation.
- The local SQLite count-then-insert capacity check is not race-free for concurrent writers. A future multi-writer deployment requires database-level locking or an equivalent transactional allocation strategy.
- Migrations create schema only and do not seed business objects.

## 5. Business rules

| Rule | Enforcement expectation |
| --- | --- |
| One ticket per attendee per event | Database uniqueness constraint and form/model validation |
| Every ticket reserves a place | Capacity calculations count all ticket statuses |
| Capacity cannot be exceeded | Server-side validation when issuing or changing a ticket |
| Ticket price is non-negative | Decimal validation and database constraint where appropriate |
| Paid tickets require date and method | Cross-field server-side validation |
| Unpaid tickets have no active payment metadata | Reject payment data in server-side validation |
| Event deletion removes tickets | `Ticket.event` uses `CASCADE` |
| Attendees and venues remain protected | `Ticket.attendee` and `Event.venue` use `PROTECT` |
| Expected revenue | Sum of all ticket prices |
| Collected revenue | Sum of prices for paid tickets only |
| Event Health is transparent | A documented, deterministic occupancy-based indicator whose status drivers are visible in the UI |
| Destructive operations are confirmed | Confirmation page before a permitted delete action |

Capacity validation must account for updates correctly: editing an existing ticket must not count that same ticket twice. All business rules are enforced server-side; UI hints are helpful but never sufficient.

## 6. Navigation and screens

Primary navigation is: Dashboard, Events, Attendees, Venues, Tickets, Tracker, and Insights. Every page includes accessible navigation and a shared footer.

The delivered screen set includes:

1. Dashboard
2. Event list
3. Event detail
4. Event create/edit form
5. Event delete confirmation
6. Venue list
7. Venue detail
8. Venue create/edit form
9. Venue delete confirmation
10. Attendee list
11. Attendee detail
12. Attendee create/edit form
13. Attendee delete confirmation
14. Ticket list
15. Ticket create/edit form
16. Ticket detail
17. Ticket delete confirmation
18. Ticket payment-status form (mark paid / mark unpaid)
19. Tracker
20. Insights
21. Custom 404 page

This exceeds the minimum of twelve page templates. The list, detail, form, confirmation, dashboard, tracker, and insights pages render database-backed content or database-dependent empty states.

## 7. Reporting definitions

| Metric | Definition |
| --- | --- |
| Tickets reserved | Count of all tickets, paid and unpaid |
| Tickets paid | Count of tickets with `PAID` status |
| Expected revenue | Sum of every ticket price |
| Collected revenue | Sum of prices of `PAID` tickets |
| Outstanding revenue | Expected revenue minus collected revenue |
| Occupancy | Reserved tickets divided by venue capacity; show a safe empty/zero-capacity state |
| Event health | Occupancy-only classification based on issued tickets divided by the selected event venue capacity |

Event Health uses unrounded occupancy: below 30% is Needs Attention; 30% to below 80% is On Track; 80% to below 100% is Near Capacity; exactly 100% is Full. It is a descriptive current-state classification, not a prediction and not a measure of schedule or payment exposure.

## 8. UX and quality requirements

- The interface works with an empty database and offers clear creation links from empty states.
- Five Django forms provide appropriate field and cross-field validation: `VenueForm`, `EventForm`, `AttendeeForm`, `TicketForm`, and `PaymentForm`.
- At least one field is read-only or disabled where it improves clarity without weakening server-side validation.
- Search, filtering, and sorting are available on relevant listing/reporting views.
- Custom template filters or tags format or calculate reusable presentation logic.
- A custom 404 template is configured and reachable.
- Use Django conventions, reusable templates/partials, semantic HTML, labelled controls, keyboard-friendly navigation, and descriptive feedback.
- Use SQLite for local data storage.

## 9. Non-goals

- Authentication, roles, permissions, and user profiles.
- Multi-organizer or multi-tenant support.
- Payment gateway processing.
- Payment-history audit trails; only the ticket's current payment status, date, and method are stored.
- Email delivery, marketing automation, and external calendar synchronization.
- Inventory beyond one reservable place per ticket.
