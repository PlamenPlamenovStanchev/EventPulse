# EventPulse v1.0 Release Notes

## Scope

EventPulse v1.0 is a local, single-operator Django application for managing event operations and reviewing ticket, payment, revenue, and occupancy information. It is an academic/local-development release, not a public production deployment.

## Implemented modules

- **Events:** venue and event CRUD, scheduling, search/filter/sort controls, capacity context, and delete confirmations.
- **Attendees:** reusable attendee CRUD with unique email and phone validation.
- **Ticketing:** ticket CRUD, event/attendee uniqueness, capacity enforcement, manual payment-status actions, and protected destructive workflows.
- **Reporting:** Dashboard, Financial Tracker, Insights comparisons/charts, event filtering, and occupancy-based Event Health.

## Main architectural decisions

- The Django configuration package remains `eventpulse`.
- The application is separated into `events`, `attendees`, and `ticketing` apps.
- `Ticket` is the explicit many-to-many through model between `Event` and `Attendee`.
- SQLite is used for local persistence and migrations provide schema without business seed data.
- Shared templates, navigation, footer, CSS, and a custom 404 handler provide consistent UI behavior.
- The custom `money` template filter centralizes monetary display formatting.

## Analytics capabilities

- Expected revenue sums every ticket price.
- Collected revenue sums paid-ticket prices only.
- Outstanding revenue is expected minus collected revenue.
- Dashboard and Insights show per-event occupancy, revenue, and collection information.
- Event Health is descriptive occupancy classification: Needs Attention below 30%, On Track from 30% to below 80%, Near Capacity from 80% to below 100%, and Full at 100%.

## QA evidence

- The latest independently verified pre-documentation baseline reported 158 passing Django tests, successful `python manage.py check`, and no pending migrations.
- Source includes focused tests for data integrity, CRUD, payment actions, reporting metrics, empty states, custom template filter behavior, and custom 404 rendering with `DEBUG=False`.
- Day 10 source review found nine local commits on nine distinct dates.

This documentation task did not run a new test suite. Use the commands in [README.md](../README.md#verification) if a fresh verification result is required.

## Known limitations

- SQLite count-then-insert capacity validation is not race-free for simultaneous ticket allocation by multiple writers.
- Payments are manually recorded; there is no payment gateway.
- The application stores current payment metadata, not a payment-history audit trail.
- Event Health is occupancy-based and descriptive, not predictive.
- `DEBUG=True`, empty `ALLOWED_HOSTS`, and the local secret-key fallback make the included configuration unsuitable for public production deployment.

## Release checks still owned by the repository owner

- Intentionally version the documentation files before release.
- Confirm the configured GitHub repository is publicly accessible and the intended commits are pushed.
