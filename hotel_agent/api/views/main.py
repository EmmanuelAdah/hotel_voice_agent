"""
API views for Hotel Voice Agent.
Covers voice sessions, service requests, bookings, and authentication.
"""
import base64
import logging
from django.conf import settings
from django.db import transaction, connection
from django.core.cache import cache
from django.utils import timezone
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework_simplejwt.views import TokenObtainPairView
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from hotel_agent.core.models import (
    User, Room, Booking, ServiceRequest, VoiceSession, AuditLog
)
from hotel_agent.api.serializers import (
    UserSerializer, RoomSerializer, BookingSerializer,
    ServiceRequestSerializer, VoiceSessionSerializer,
    VoiceInputSerializer, CustomTokenObtainPairSerializer,
)
from hotel_agent.api.permissions import (
    IsGuestOrStaff, IsStaffOrAdmin, IsOwnerOrStaff,
)
from hotel_agent.api.throttling import VoiceSessionThrottle
from hotel_agent.services.voice_agent import HotelVoiceAgentService, ConversationMessage
from hotel_agent.kafka.producer_consumer import KafkaProducerService
from hotel_agent.kafka.producer_consumer import (
    VoiceSessionEvent, ServiceRequestEvent, NotificationEvent
)
from hotel_agent.monitoring.metrics import (
    VOICE_SESSION_COUNTER, ACTIVE_VOICE_SESSIONS, SERVICE_REQUEST_COUNTER, AUTH_ATTEMPTS
)

logger = logging.getLogger("hotel_agent.api.views")
kafka_producer = KafkaProducerService()


# ── Authentication ────────────────────────────────────────────────────────────

class CustomTokenObtainPairView(TokenObtainPairView):
    """JWT login with account lockout protection."""
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = []  # Handled by middleware

    def post(self, request, *args, **kwargs):
        try:
            user = User.objects.get(email=request.data.get("email", ""))
            if user.is_locked():
                AUTH_ATTEMPTS.labels(result="locked").inc()
                return Response(
                    {"error": "Account locked. Try again in 30 minutes."},
                    status=status.HTTP_423_LOCKED,
                )
        except User.DoesNotExist:
            pass

        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            AUTH_ATTEMPTS.labels(result="success").inc()
            try:
                user = User.objects.get(email=request.data.get("email"))
                user.reset_failed_login()
                user.last_login_ip = request.META.get("REMOTE_ADDR")
                user.save(update_fields=["last_login_ip"])
            except User.DoesNotExist:
                pass
        else:
            AUTH_ATTEMPTS.labels(result="failure").inc()
            try:
                user = User.objects.get(email=request.data.get("email", ""))
                user.record_failed_login()
            except User.DoesNotExist:
                pass

        return response


class RegisterView(generics.CreateAPIView):
    """Guest self-registration."""
    serializer_class = UserSerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        user = serializer.save(role=User.Role.GUEST)
        AuditLog.objects.create(
            user=user,
            action="user.registered",
            resource_type="user",
            resource_id=str(user.id),
            ip_address=self.request.META.get("REMOTE_ADDR"),
        )


# ── Voice Session ─────────────────────────────────────────────────────────────

class VoiceSessionViewSet(viewsets.ModelViewSet):
    """
    Voice session management.
    POST /voice/sessions/ - start session
    POST /voice/sessions/{id}/turn/ - process a voice turn
    POST /voice/sessions/{id}/end/ - end session
    GET  /voice/sessions/{id}/transcript/ - full transcript
    """
    serializer_class = VoiceSessionSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [VoiceSessionThrottle]
    parser_classes = [JSONParser, MultiPartParser]

    def get_queryset(self):
        user = self.request.user
        qs = VoiceSession.objects.select_related("guest", "booking__room")
        if user.role in (User.Role.GUEST,):
            qs = qs.filter(guest=user)
        return qs.order_by("-started_at")

    def create(self, request, *args, **kwargs):
        """Start a new voice session."""
        booking_id = request.data.get("booking_id")
        booking = None

        if booking_id:
            try:
                booking = Booking.objects.select_related("room").get(
                    id=booking_id, guest=request.user, status=Booking.Status.CHECKED_IN
                )
            except Booking.DoesNotExist:
                return Response({"error": "Active booking not found."}, status=400)

        session = VoiceSession.objects.create(
            guest=request.user,
            booking=booking,
            status=VoiceSession.Status.ACTIVE,
        )

        VOICE_SESSION_COUNTER.labels(
            status="started",
            room_type=booking.room.room_type if booking else "unknown"
        ).inc()
        ACTIVE_VOICE_SESSIONS.inc()

        kafka_producer.publish(
            "VOICE_SESSIONS",
            VoiceSessionEvent.started(
                str(session.id), str(request.user.id),
                booking.room.number if booking else "N/A"
            )
        )

        serializer = self.get_serializer(session)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="turn")
    def process_turn(self, request, pk=None):
        """
        Process a single voice turn.
        Accepts: JSON {text: "..."} or multipart {audio: <file>}
        Returns: {text, audio_base64?, service_request?}
        """
        session = self.get_object()
        if session.status != VoiceSession.Status.ACTIVE:
            return Response({"error": "Session is not active."}, status=400)

        serializer = VoiceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        text_input = serializer.validated_data.get("text")
        audio_file = request.FILES.get("audio")
        generate_audio = serializer.validated_data.get("generate_audio", True)

        if not text_input and not audio_file:
            return Response({"error": "Provide 'text' or 'audio' file."}, status=400)

        audio_bytes = audio_file.read() if audio_file else None

        # Build guest context
        guest_context = self._build_guest_context(session)

        # Build conversation history from session transcript
        history = [
            ConversationMessage(role=msg["role"], content=msg["content"])
            for msg in session.transcript[-10:]
        ]

        # Run voice agent (sync wrapper for async service)
        agent = HotelVoiceAgentService()
        try:
            result = async_to_sync(agent.process_voice_turn)(
                audio_bytes=audio_bytes,
                text_input=text_input,
                conversation_history=history,
                guest_context=guest_context,
                generate_audio=generate_audio,
            )
        except Exception as e:
            logger.error("voice_turn_error", extra={"session_id": str(session.id), "error": str(e)})
            session.status = VoiceSession.Status.FAILED
            session.save(update_fields=["status"])
            return Response({"error": "Voice processing failed."}, status=500)

        # Update transcript
        now_ts = timezone.now().isoformat()
        user_content = text_input or "[audio input]"
        session.transcript.extend([
            {"role": "user", "content": user_content, "timestamp": now_ts},
            {"role": "assistant", "content": result.text, "timestamp": now_ts},
        ])
        session.tokens_used += result.tokens_used
        session.tts_characters += result.tts_chars
        session.save(update_fields=["transcript", "tokens_used", "tts_characters"])

        # Create service request if detected
        service_request_data = None
        if result.service_request and session.booking:
            with transaction.atomic():
                sr = ServiceRequest.objects.create(
                    booking=session.booking,
                    guest=request.user,
                    service_type=result.service_request.get("service_type", "other"),
                    priority=result.service_request.get("priority", "normal"),
                    description=result.service_request.get("description", ""),
                    voice_session_id=session.id,
                )
                session.service_requests_created.add(sr)
                SERVICE_REQUEST_COUNTER.labels(
                    service_type=sr.service_type, priority=sr.priority, source="voice"
                ).inc()
                kafka_producer.publish(
                    "SERVICE_REQUESTS",
                    ServiceRequestEvent.created(str(sr.id), sr.service_type, sr.priority, str(request.user.id))
                )
                service_request_data = ServiceRequestSerializer(sr).data

        response_data = {
            "session_id": str(session.id),
            "text": result.text,
            "latency_ms": round(result.latency_ms, 2),
        }
        if result.audio_data:
            response_data["audio_base64"] = base64.b64encode(result.audio_data).decode()
            response_data["audio_format"] = "mp3"
        if service_request_data:
            response_data["service_request_created"] = service_request_data

        return Response(response_data)

    @action(detail=True, methods=["post"], url_path="end")
    def end_session(self, request, pk=None):
        """End a voice session and publish analytics."""
        session = self.get_object()
        if session.status != VoiceSession.Status.ACTIVE:
            return Response({"error": "Session already ended."}, status=400)

        session.status = VoiceSession.Status.COMPLETED
        session.ended_at = timezone.now()
        duration = (session.ended_at - session.started_at).seconds
        session.duration_seconds = duration
        session.save(update_fields=["status", "ended_at", "duration_seconds"])

        ACTIVE_VOICE_SESSIONS.dec()
        kafka_producer.publish(
            "VOICE_SESSIONS",
            VoiceSessionEvent.completed(str(session.id), duration, session.tokens_used)
        )

        return Response({"status": "completed", "duration_seconds": duration})

    @action(detail=True, methods=["get"], url_path="transcript")
    def transcript(self, request, pk=None):
        session = self.get_object()
        return Response({
            "session_id": str(session.id),
            "transcript": session.transcript,
            "tokens_used": session.tokens_used,
            "tts_characters": session.tts_characters,
        })

    @staticmethod
    def _build_guest_context(session: VoiceSession) -> dict:
        ctx = {
            "name": session.guest.full_name,
            "preferences": session.guest.preferences,
        }
        if session.booking:
            ctx.update({
                "room_number": session.booking.room.number,
                "room_type": session.booking.room.get_room_type_display(),
                "check_out": str(session.booking.check_out),
                "confirmation_code": session.booking.confirmation_code,
            })
        return ctx


# ── Service Requests ──────────────────────────────────────────────────────────

class ServiceRequestViewSet(viewsets.ModelViewSet):
    serializer_class = ServiceRequestSerializer
    permission_classes = [IsOwnerOrStaff]

    def get_queryset(self):
        user = self.request.user
        qs = ServiceRequest.objects.select_related(
            "guest", "booking__room", "assigned_to"
        ).order_by("-created_at")

        if user.role == User.Role.GUEST:
            return qs.filter(guest=user)
        if user.role == User.Role.STAFF:
            return qs.filter(
                models.Q(assigned_to=user) | models.Q(status=ServiceRequest.Status.PENDING)
            )
        return qs  # Manager/Admin see all

    @action(detail=True, methods=["post"], url_path="assign")
    def assign(self, request, pk=None):
        """Staff self-assign a service request."""
        sr = self.get_object()
        if request.user.role not in (User.Role.STAFF, User.Role.MANAGER, User.Role.ADMIN):
            return Response({"error": "Insufficient permissions."}, status=403)

        sr.assigned_to = request.user
        sr.status = ServiceRequest.Status.ASSIGNED
        sr.save(update_fields=["assigned_to", "status"])

        kafka_producer.publish(
            "SERVICE_REQUESTS",
            ServiceRequestEvent.status_changed(str(sr.id), "pending", "assigned")
        )
        return Response(ServiceRequestSerializer(sr).data)

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, pk=None):
        """Mark service request as completed."""
        sr = self.get_object()
        sr.status = ServiceRequest.Status.COMPLETED
        sr.completed_at = timezone.now()
        sr.notes = request.data.get("notes", "")
        sr.save(update_fields=["status", "completed_at", "notes"])

        # Notify guest
        kafka_producer.publish(
            "NOTIFICATIONS",
            NotificationEvent.guest_notification(
                guest_id=str(sr.guest_id),
                channel="ws",
                message=f"Your {sr.get_service_type_display()} request has been completed.",
                data={"request_id": str(sr.id), "service_type": sr.service_type},
            )
        )
        return Response(ServiceRequestSerializer(sr).data)


# ── Rooms ─────────────────────────────────────────────────────────────────────

class RoomViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RoomSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["room_type", "status", "floor"]
    search_fields = ["number", "description"]

    def get_queryset(self):
        return Room.objects.filter(is_active=True).order_by("floor", "number")


# ── Bookings ──────────────────────────────────────────────────────────────────

class BookingViewSet(viewsets.ModelViewSet):
    serializer_class = BookingSerializer
    permission_classes = [IsOwnerOrStaff]
    filterset_fields = ["status", "room__room_type"]
    search_fields = ["confirmation_code", "guest__email"]

    def get_queryset(self):
        user = self.request.user
        qs = Booking.objects.select_related("guest", "room").prefetch_related(
            "service_requests"
        ).order_by("-created_at")

        if user.role == User.Role.GUEST:
            return qs.filter(guest=user)
        return qs


# ── Health Check ──────────────────────────────────────────────────────────────

class HealthCheckView(generics.GenericAPIView):
    permission_classes = [AllowAny]

    def get(self, request):
        checks = {}

        # Database
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "error"

        # Cache
        try:
            cache.set("health_check", "ok", 5)
            checks["cache"] = "ok" if cache.get("health_check") == "ok" else "error"
        except Exception:
            checks["cache"] = "error"

        all_ok = all(v == "ok" for v in checks.values())
        return Response(
            {"status": "healthy" if all_ok else "degraded", "checks": checks},
            status=200 if all_ok else 503,
        )
