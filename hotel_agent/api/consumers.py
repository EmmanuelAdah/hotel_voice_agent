"""
Django Channels WebSocket consumer for real-time voice sessions.
Streams STT, LLM, and TTS responses over WebSocket for low-latency UX.
"""
import json
import base64
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError
from hotel_agent.services.voice_agent import HotelVoiceAgentService, ConversationMessage
from hotel_agent.monitoring.metrics import ACTIVE_VOICE_SESSIONS

logger = logging.getLogger("hotel_agent.consumers")


class VoiceSessionConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time voice interaction.

    Protocol:
      Client → Server: {"type": "voice_input", "text": "...", "generate_audio": true}
      Client → Server: {"type": "audio_input", "audio_b64": "<base64>", "format": "webm"}
      Server → Client: {"type": "response_text", "text": "...", "session_id": "..."}
      Server → Client: {"type": "response_audio", "audio_b64": "...", "format": "mp3"}
      Server → Client: {"type": "service_request_created", "data": {...}}
      Server → Client: {"type": "error", "message": "..."}
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id: str | None = None
        self.user = None
        self.conversation_history: list[ConversationMessage] = []
        self.agent = HotelVoiceAgentService()
        self.group_name: str | None = None

    async def connect(self):
        """Authenticate JWT from query string and establish connection."""
        token_str = self.scope["query_string"].decode().split("token=")[-1].split("&")[0]
        self.user = await self._authenticate_token(token_str)

        if isinstance(self.user, AnonymousUser) or self.user is None:
            await self.close(code=4001)
            return

        self.session_id = self.scope["url_route"]["kwargs"].get("session_id")
        self.group_name = f"guest_{self.user.id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        ACTIVE_VOICE_SESSIONS.inc()
        logger.info("ws_connected", extra={"user_id": str(self.user.id), "session_id": self.session_id})

        await self.send(json.dumps({
            "type": "connected",
            "session_id": self.session_id,
            "message": "Voice session ready. How can I assist you?",
        }))

    async def disconnect(self, close_code):
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        ACTIVE_VOICE_SESSIONS.dec()
        logger.info("ws_disconnected", extra={"close_code": close_code, "session_id": self.session_id})

    async def receive(self, text_data: str | None = None, bytes_data: bytes | None = None):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            await self._send_error("Invalid JSON payload.")
            return

        msg_type = data.get("type")

        if msg_type == "voice_input":
            await self._handle_text_input(data)
        elif msg_type == "audio_input":
            await self._handle_audio_input(data)
        elif msg_type == "ping":
            await self.send(json.dumps({"type": "pong"}))
        else:
            await self._send_error(f"Unknown message type: {msg_type}")

    async def _handle_text_input(self, data: dict):
        text = data.get("text", "").strip()
        if not text:
            await self._send_error("Empty text input.")
            return

        generate_audio = data.get("generate_audio", True)
        guest_context = await self._get_guest_context()

        try:
            result = await self.agent.process_voice_turn(
                text_input=text,
                conversation_history=self.conversation_history,
                guest_context=guest_context,
                generate_audio=generate_audio,
            )
        except Exception as e:
            logger.error("voice_turn_ws_error", extra={"error": str(e)})
            await self._send_error("Processing failed. Please try again.")
            return

        self.conversation_history.extend([
            ConversationMessage(role="user", content=text),
            ConversationMessage(role="assistant", content=result.text),
        ])

        await self.send(json.dumps({"type": "response_text", "text": result.text}))

        if result.audio_data:
            await self.send(json.dumps({
                "type": "response_audio",
                "audio_b64": base64.b64encode(result.audio_data).decode(),
                "format": "mp3",
            }))

        if result.service_request:
            await self.send(json.dumps({
                "type": "service_request_detected",
                "data": result.service_request,
            }))

    async def _handle_audio_input(self, data: dict):
        audio_b64 = data.get("audio_b64", "")
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception:
            await self._send_error("Invalid base64 audio data.")
            return

        await self._handle_text_input({
            **data,
            "type": "voice_input",
            "_audio_bytes": audio_bytes,
            "text": None,
        })

    async def _send_error(self, message: str):
        await self.send(json.dumps({"type": "error", "message": message}))

    # Channel layer message handlers (for group push)
    async def notification_message(self, event):
        """Push notifications from Kafka → WebSocket."""
        await self.send(json.dumps({
            "type": "notification",
            "message": event["message"],
            "data": event.get("data", {}),
        }))

    @database_sync_to_async
    def _authenticate_token(self, token_str: str):
        from hotel_agent.core.models import User
        try:
            token = AccessToken(token_str)
            return User.objects.get(id=token["user_id"])
        except (TokenError, User.DoesNotExist, KeyError):
            return AnonymousUser()

    @database_sync_to_async
    def _get_guest_context(self) -> dict:
        from hotel_agent.core.models import Booking
        ctx = {"name": self.user.full_name, "preferences": self.user.preferences}
        if self.session_id:
            from hotel_agent.core.models import VoiceSession
            try:
                session = VoiceSession.objects.select_related(
                    "booking__room"
                ).get(id=self.session_id, guest=self.user)
                if session.booking:
                    ctx.update({
                        "room_number": session.booking.room.number,
                        "room_type": session.booking.room.get_room_type_display(),
                        "check_out": str(session.booking.check_out),
                    })
            except VoiceSession.DoesNotExist:
                pass
        return ctx


async def push_notification_to_guest(guest_id: str, message: str, data: dict):
    """Push a notification to a guest's WebSocket group."""
    from channels.layers import get_channel_layer
    channel_layer = get_channel_layer()
    group_name = f"guest_{guest_id}"
    await channel_layer.group_send(group_name, {
        "type": "notification_message",
        "message": message,
        "data": data,
    })
