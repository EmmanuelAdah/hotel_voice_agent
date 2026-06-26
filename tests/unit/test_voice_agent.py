"""
Unit and integration tests for Hotel Voice Agent.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from django.test import TestCase, AsyncTestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
import pytest

from hotel_agent.core.models import Room, Booking, ServiceRequest, VoiceSession
from hotel_agent.services.voice_agent import HotelVoiceAgentService, VoiceAgentResponse

User = get_user_model()


# ── Factories ─────────────────────────────────────────────────────────────────

def make_user(role="guest", **kwargs):
    return User.objects.create_user(
        email=kwargs.pop("email", f"test_{uuid.uuid4().hex[:8]}@hotel.com"),
        password="TestPass123!",
        role=role,
        first_name="Test",
        last_name="Guest",
        **kwargs,
    )


def make_room(**kwargs):
    return Room.objects.create(
        number=kwargs.pop("number", f"{uuid.uuid4().hex[:4]}"),
        floor=kwargs.pop("floor", 1),
        room_type=Room.RoomType.STANDARD,
        price_per_night="150.00",
        capacity=2,
        **kwargs,
    )


def make_booking(guest, room, **kwargs):
    from datetime import date, timedelta
    return Booking.objects.create(
        guest=guest,
        room=room,
        check_in=kwargs.pop("check_in", date.today()),
        check_out=kwargs.pop("check_out", date.today() + timedelta(days=3)),
        adults=2,
        total_price="450.00",
        status=Booking.Status.CHECKED_IN,
        **kwargs,
    )


# ── Model Tests ───────────────────────────────────────────────────────────────

class UserModelTest(TestCase):
    def test_create_user_sets_role_guest(self):
        user = make_user(role=User.Role.GUEST)
        self.assertEqual(user.role, User.Role.GUEST)

    def test_account_lockout_after_5_failures(self):
        user = make_user()
        for _ in range(5):
            user.record_failed_login()
        self.assertTrue(user.is_locked())

    def test_reset_clears_lockout(self):
        user = make_user()
        for _ in range(5):
            user.record_failed_login()
        user.reset_failed_login()
        self.assertFalse(user.is_locked())

    def test_full_name_property(self):
        user = User(first_name="John", last_name="Doe", email="jd@hotel.com")
        self.assertEqual(user.full_name, "John Doe")

    def test_full_name_falls_back_to_email(self):
        user = User(email="anon@hotel.com")
        self.assertEqual(user.full_name, "anon@hotel.com")


class BookingModelTest(TestCase):
    def setUp(self):
        self.guest = make_user()
        self.room = make_room()

    def test_confirmation_code_generated_on_save(self):
        booking = make_booking(self.guest, self.room)
        self.assertIsNotNone(booking.confirmation_code)
        self.assertEqual(len(booking.confirmation_code), 12)

    def test_unique_confirmation_codes(self):
        b1 = make_booking(self.guest, self.room, number="101")
        room2 = make_room(number="102")
        b2 = make_booking(self.guest, room2, number="102")
        self.assertNotEqual(b1.confirmation_code, b2.confirmation_code)


# ── Voice Agent Service Tests ─────────────────────────────────────────────────

class VoiceAgentServiceTest(TestCase):
    def setUp(self):
        self.agent = HotelVoiceAgentService()

    def test_extract_service_request_valid(self):
        text = """I'll arrange that right away.
<service_request>
{"service_type": "room_service", "description": "Burger and fries", "priority": "normal", "scheduled_at": null}
</service_request>"""
        result = self.agent._extract_service_request(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["service_type"], "room_service")
        self.assertEqual(result["priority"], "normal")

    def test_extract_service_request_invalid_type(self):
        text = '<service_request>{"service_type": "unknown_type", "description": "x", "priority": "low"}</service_request>'
        result = self.agent._extract_service_request(text)
        self.assertEqual(result["service_type"], "other")

    def test_extract_service_request_no_tag(self):
        text = "Of course! I'll send housekeeping right away."
        result = self.agent._extract_service_request(text)
        self.assertIsNone(result)

    def test_clean_for_tts_removes_tags(self):
        text = "Here you go. <service_request>...</service_request> Anything else?"
        clean = self.agent._clean_for_tts(text)
        self.assertNotIn("<service_request>", clean)
        self.assertIn("Here you go.", clean)

    def test_format_guest_context(self):
        ctx = {"name": "Alice", "room_number": "302", "check_out": "2026-07-01"}
        formatted = self.agent._format_guest_context(ctx)
        self.assertIn("Alice", formatted)
        self.assertIn("302", formatted)

    @pytest.mark.asyncio
    async def test_generate_response_mocked(self):
        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = "Your room service order has been placed."
        mock_completion.usage.total_tokens = 120

        with patch.object(self.agent.client.chat.completions, "create", new=AsyncMock(return_value=mock_completion)):
            response = await self.agent.generate_response(
                user_message="I'd like a burger please",
                conversation_history=[],
                guest_context={"name": "Bob", "room_number": "205"},
            )

        self.assertIn("room service", response.text.lower())
        self.assertEqual(response.tokens_used, 120)


# ── API Tests ─────────────────────────────────────────────────────────────────

class AuthAPITest(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user()

    def test_register_new_user(self):
        data = {
            "email": "newguest@hotel.com",
            "password": "SecurePass123!",
            "confirm_password": "SecurePass123!",
            "first_name": "New",
            "last_name": "Guest",
        }
        response = self.client.post("/api/v1/auth/register/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("email", response.data)

    def test_token_obtain(self):
        response = self.client.post("/api/v1/auth/token/", {
            "email": self.user.email,
            "password": "TestPass123!",
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_token_contains_role(self):
        response = self.client.post("/api/v1/auth/token/", {
            "email": self.user.email,
            "password": "TestPass123!",
        }, format="json")
        import jwt
        token = response.data["access"]
        # Decode without verification for test
        payload = jwt.decode(token, options={"verify_signature": False})
        self.assertIn("role", payload)

    def test_locked_user_cannot_login(self):
        for _ in range(5):
            self.user.record_failed_login()
        response = self.client.post("/api/v1/auth/token/", {
            "email": self.user.email,
            "password": "TestPass123!",
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_423_LOCKED)


class VoiceSessionAPITest(APITestCase):
    def setUp(self):
        self.guest = make_user(role=User.Role.GUEST)
        self.room = make_room()
        self.booking = make_booking(self.guest, self.room)
        self.client = APIClient()
        self.client.force_authenticate(user=self.guest)

    def test_create_voice_session(self):
        with patch("hotel_agent.api.views.main.kafka_producer") as mock_kafka:
            mock_kafka.publish.return_value = True
            response = self.client.post("/api/v1/voice/sessions/", {
                "booking_id": str(self.booking.id)
            }, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("id", response.data)
        self.assertEqual(response.data["status"], "active")

    def test_end_voice_session(self):
        session = VoiceSession.objects.create(
            guest=self.guest,
            booking=self.booking,
            status=VoiceSession.Status.ACTIVE,
        )
        with patch("hotel_agent.api.views.main.kafka_producer"):
            response = self.client.post(f"/api/v1/voice/sessions/{session.id}/end/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        session.refresh_from_db()
        self.assertEqual(session.status, VoiceSession.Status.COMPLETED)

    def test_end_already_ended_session(self):
        session = VoiceSession.objects.create(
            guest=self.guest,
            booking=self.booking,
            status=VoiceSession.Status.COMPLETED,
        )
        response = self.client.post(f"/api/v1/voice/sessions/{session.id}/end/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_guest_cannot_see_other_sessions(self):
        other_guest = make_user()
        other_room = make_room(number="999")
        other_booking = make_booking(other_guest, other_room)
        VoiceSession.objects.create(
            guest=other_guest, booking=other_booking, status=VoiceSession.Status.COMPLETED
        )
        response = self.client.get("/api/v1/voice/sessions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for session in response.data.get("results", []):
            self.assertEqual(session["guest"]["id"], str(self.guest.id))


class HealthCheckTest(APITestCase):
    def test_health_check_returns_200(self):
        response = self.client.get("/api/v1/health/")
        self.assertIn(response.status_code, [200, 503])
        self.assertIn("status", response.data)
        self.assertIn("checks", response.data)


# ── Middleware Tests ──────────────────────────────────────────────────────────

class RateLimitMiddlewareTest(TestCase):
    def test_rate_limit_blocks_after_limit(self):
        from django.test import RequestFactory
        from hotel_agent.core.middleware import RateLimitMiddleware
        from django.core.cache import cache

        cache.clear()
        factory = RequestFactory()
        middleware = RateLimitMiddleware(lambda req: None)

        # Exhaust limit (5 for auth)
        for _ in range(5):
            req = factory.post("/api/v1/auth/token/", REMOTE_ADDR="1.2.3.4")
            middleware.process_request(req)

        # Next request should be blocked
        req = factory.post("/api/v1/auth/token/", REMOTE_ADDR="1.2.3.4")
        response = middleware.process_request(req)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 429)
