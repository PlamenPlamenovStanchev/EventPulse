from django.test import SimpleTestCase, override_settings
from django.urls import reverse


class InterfaceFoundationTests(SimpleTestCase):
    navigation_routes = (
        'ticketing:dashboard',
        'events:event_list',
        'attendees:attendee_list',
        'events:venue_list',
        'ticketing:ticket_list',
        'ticketing:tracker',
        'ticketing:insights',
    )

    def test_dashboard_returns_success(self):
        response = self.client.get(reverse('ticketing:dashboard'))

        self.assertEqual(response.status_code, 200)

    def test_every_navigation_destination_returns_success(self):
        for route_name in self.navigation_routes:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)

    def test_shared_navigation_and_footer_appear_on_every_destination(self):
        for route_name in self.navigation_routes:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertContains(response, 'Primary navigation')
                self.assertContains(response, 'Built for clearer operations.')

    def test_homepage_contains_eventpulse_identity(self):
        response = self.client.get(reverse('ticketing:dashboard'))

        self.assertContains(response, 'Welcome to EventPulse')
        self.assertContains(response, 'Every event. Every attendee. Every insight.')

    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
    def test_custom_404_handler_renders_when_debug_is_disabled(self):
        response = self.client.get('/not-a-real-route/')

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'This route is not on the event plan.', status_code=404)
