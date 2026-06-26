"""
Pytest configuration and shared fixtures for Hotel Voice Agent tests.
"""
import pytest
import uuid
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture(autouse=True)
def reset_cache(settings):
    """Clear cache between tests."""
    from django.core.cache import cache
    yield
    cache.clear()


@pytest.fixture
def guest_user(db):
    return User.objects.create_user(
        email=f"guest_{uuid.uuid4().hex[:6]}@test.com",
        password="TestPass123!",
        first_name="Test",
        last_name="Guest",
        role="guest",
    )


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        email=f"staff_{uuid.uuid4().hex[:6]}@test.com",
        password="TestPass123!",
        first_name="Staff",
        last_name="Member",
        role="staff",
    )


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        email=f"admin_{uuid.uuid4().hex[:6]}@test.com",
        password="AdminPass123!",
    )


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def guest_client(api_client, guest_user):
    api_client.force_authenticate(user=guest_user)
    return api_client


@pytest.fixture
def staff_client(api_client, staff_user):
    api_client.force_authenticate(user=staff_user)
    return api_client


@pytest.fixture
def room(db):
    from hotel_agent.core.models import Room
    return Room.objects.create(
        number=f"R{uuid.uuid4().hex[:3].upper()}",
        floor=3,
        room_type=Room.RoomType.DELUXE,
        status=Room.Status.AVAILABLE,
        capacity=2,
        price_per_night="200.00",
        amenities=["wifi", "minibar", "safe"],
        description="Deluxe room with city view",
    )


@pytest.fixture
def booking(db, guest_user, room):
    from hotel_agent.core.models import Booking
    from datetime import date, timedelta
    return Booking.objects.create(
        guest=guest_user,
        room=room,
        check_in=date.today(),
        check_out=date.today() + timedelta(days=3),
        adults=2,
        total_price="600.00",
        status=Booking.Status.CHECKED_IN,
    )


@pytest.fixture
def voice_session(db, guest_user, booking):
    from hotel_agent.core.models import VoiceSession
    return VoiceSession.objects.create(
        guest=guest_user,
        booking=booking,
        status=VoiceSession.Status.ACTIVE,
    )
