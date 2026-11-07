# EventPulse

EventPulse is an Event Operations & Revenue Intelligence Platform for a single event organizer. It brings event planning, venue capacity, attendee records, ticket sales, payment tracking, and operational reporting into one Django application.

The project deliberately has no authentication or user-management feature. It is intended to support one organizer through a focused operational workspace.

## Planned capabilities

- Manage venues and events, including venue capacity and event schedules.
- Maintain a reusable attendee directory.
- Issue one ticket per attendee per event and track its payment state.
- Protect capacity, pricing, payment-data, and deletion rules on the server.
- Present dashboard KPIs, revenue and occupancy metrics, event-health indicators, and operational insights.
- Provide search, filtering, sorting, confirmations for destructive actions, accessible navigation, and an empty-database creation flow.

## Architecture

The Django configuration package is `eventpulse` and must remain unchanged in name. The product is organized into three applications:

| Application | Responsibility |
| --- | --- |
| `events` | Venue and event management |
| `attendees` | Attendee management |
| `ticketing` | Tickets, payments, analytics, tracker, insights, and dashboard |

The core relationships are:

```text
Venue 1 ──< Event 1 ──< Ticket >── 1 Attendee
                         ^
                         └── Event and Attendee are many-to-many through Ticket
```

See [the product specification](docs/PRODUCT_SPEC.md) for the full domain and [the requirements matrix](docs/REQUIREMENTS_MATRIX.md) for delivery criteria.

## Local development

Prerequisites:

- Python 3.13.17 (64-bit)
- Project-local `.venv`
- Django 6.1.3
- SQLite (included with Python)

From the project root in PowerShell, create and activate a project-local virtual environment:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Apply the database migrations and start the development server:

```powershell
python manage.py migrate
python manage.py runserver
```

Open `http://127.0.0.1:8000/` after routes have been implemented. The application must remain usable with an empty database; create venues, events, attendees, and tickets from the UI rather than relying on seed data.

Run the local verification suite with:

```powershell
python manage.py check
python manage.py test
```

No `.env` file, external service, or external credential is required for this standard local workflow. A local development secret-key fallback is included in settings; deployments must set `DJANGO_SECRET_KEY` through the environment.

## Data and operating rules

- A ticket reserves one place whether paid or unpaid.
- A ticket price cannot be negative.
- Each attendee may hold only one ticket for a given event.
- Ticket count may not exceed the event venue’s capacity.
- A paid ticket requires a payment date and payment method; an unpaid ticket stores neither as active payment metadata.
- Event deletion removes its tickets but preserves the related venue and attendees.
- A venue with events and an attendee with tickets cannot be deleted.
- Expected revenue is the total ticket value; collected revenue is the paid-ticket value.

## Security and source control

Never commit secrets or `.env` files. Use environment variables for deployment-specific settings and retain only a safe example file when one is needed. The repository should be public only after sensitive settings have been reviewed.

The academic delivery also requires at least five genuine Git commits made on five different days. Do not create commits automatically; commits, pushes, and destructive repository operations require explicit approval.
