"""
OpenAI-powered voice agent service for hotel operations.
Handles speech-to-text (Whisper), intent classification, response generation (GPT-4o),
and text-to-speech (TTS-1-HD).
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from django.conf import settings
from openai import AsyncOpenAI, OpenAIError

logger = logging.getLogger("hotel_agent.services.voice")

SYSTEM_PROMPT = """You are ARIA (Automated Room Intelligence Assistant), a professional and
friendly AI voice concierge for a luxury hotel. You help guests with:

1. Room service orders (food & beverages)
2. Housekeeping requests (fresh towels, cleaning, turndown service)
3. Maintenance requests (AC, TV, plumbing issues)
4. Concierge services (restaurant reservations, taxi, tour bookings)
5. Wake-up call scheduling
6. General hotel information (amenities, facilities, check-out time)
7. Spa and wellness bookings
8. Laundry services

Guidelines:
- Always be warm, professional, and efficient
- Confirm details before creating any service request
- If a request is urgent (safety/emergency), escalate immediately
- Extract: service_type, description, priority, scheduled_time from each request
- Respond in the guest's language when possible
- Keep responses concise for voice output (under 80 words)
- End service requests with a confirmation and estimated wait time

When you identify a service request, include a structured tag at the end:
<service_request>
{
  "service_type": "<type>",
  "description": "<detailed description>",
  "priority": "<low|normal|high|urgent>",
  "scheduled_at": "<ISO datetime or null>"
}
</service_request>
"""

VALID_SERVICE_TYPES = {
    "room_service", "housekeeping", "maintenance", "concierge",
    "wake_up_call", "transport", "spa", "dining", "laundry", "other"
}


@dataclass
class VoiceAgentResponse:
    text: str
    audio_data: bytes | None = None
    service_request: dict | None = None
    tokens_used: int = 0
    tts_chars: int = 0
    latency_ms: float = 0.0


@dataclass
class ConversationMessage:
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)


class HotelVoiceAgentService:
    """
    Core service for AI-powered hotel voice interactions.
    Integrates Whisper STT, GPT-4o response generation, and TTS-1-HD.
    """

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.OPENAI_MODEL
        self.whisper_model = settings.OPENAI_WHISPER_MODEL
        self.tts_model = settings.OPENAI_TTS_MODEL
        self.tts_voice = settings.OPENAI_TTS_VOICE

    async def transcribe_audio(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        """Transcribe audio to text using Whisper."""
        import io
        start = time.monotonic()
        try:
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = filename
            transcript = await self.client.audio.transcriptions.create(
                model=self.whisper_model,
                file=audio_file,
                language="en",
                response_format="text",
            )
            latency = (time.monotonic() - start) * 1000
            logger.info("whisper_transcribed", extra={"latency_ms": latency, "chars": len(transcript)})
            return transcript.strip()
        except OpenAIError as e:
            logger.error("whisper_error", extra={"error": str(e)})
            raise

    async def generate_response(
        self,
        user_message: str,
        conversation_history: list[ConversationMessage],
        guest_context: dict[str, Any] | None = None,
    ) -> VoiceAgentResponse:
        """Generate a response using GPT-4o with full conversation context."""
        start = time.monotonic()

        # Build messages for OpenAI
        system_content = SYSTEM_PROMPT
        if guest_context:
            system_content += f"\n\nGuest Context:\n{self._format_guest_context(guest_context)}"

        messages = [{"role": "system", "content": system_content}]

        # Add conversation history (last 10 turns to stay within context)
        for msg in conversation_history[-10:]:
            messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": user_message})

        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=settings.OPENAI_MAX_TOKENS,
                temperature=settings.OPENAI_TEMPERATURE,
                stream=False,
            )
        except OpenAIError as e:
            logger.error("gpt_error", extra={"error": str(e)})
            raise

        response_text = completion.choices[0].message.content or ""
        tokens_used = completion.usage.total_tokens if completion.usage else 0

        # Extract service request JSON if present
        service_request = self._extract_service_request(response_text)
        # Clean text for TTS (remove XML tags)
        clean_text = self._clean_for_tts(response_text)

        latency = (time.monotonic() - start) * 1000
        logger.info("gpt_response", extra={"latency_ms": latency, "tokens": tokens_used})

        return VoiceAgentResponse(
            text=clean_text,
            service_request=service_request,
            tokens_used=tokens_used,
            latency_ms=latency,
        )

    async def synthesize_speech(self, text: str) -> bytes:
        """Convert text to speech using TTS-1-HD."""
        start = time.monotonic()
        try:
            response = await self.client.audio.speech.create(
                model=self.tts_model,
                voice=self.tts_voice,
                input=text[:4096],  # TTS limit
                response_format="mp3",
            )
            audio_data = response.content
            latency = (time.monotonic() - start) * 1000
            logger.info("tts_synthesized", extra={"latency_ms": latency, "chars": len(text)})
            return audio_data
        except OpenAIError as e:
            logger.error("tts_error", extra={"error": str(e)})
            raise

    async def process_voice_turn(
        self,
        audio_bytes: bytes | None = None,
        text_input: str | None = None,
        conversation_history: list[ConversationMessage] | None = None,
        guest_context: dict[str, Any] | None = None,
        generate_audio: bool = True,
    ) -> VoiceAgentResponse:
        """
        Full pipeline: STT → GPT-4o → TTS.
        Accepts either raw audio bytes or pre-transcribed text.
        """
        if conversation_history is None:
            conversation_history = []

        # Step 1: STT
        if audio_bytes and not text_input:
            text_input = await self.transcribe_audio(audio_bytes)

        if not text_input:
            raise ValueError("Either audio_bytes or text_input must be provided")

        # Step 2: LLM Response
        response = await self.generate_response(text_input, conversation_history, guest_context)

        # Step 3: TTS
        if generate_audio and response.text:
            audio_data = await self.synthesize_speech(response.text)
            response.audio_data = audio_data
            response.tts_chars = len(response.text)

        return response

    @staticmethod
    def _format_guest_context(context: dict) -> str:
        lines = []
        if name := context.get("name"):
            lines.append(f"- Guest Name: {name}")
        if room := context.get("room_number"):
            lines.append(f"- Room Number: {room}")
        if check_out := context.get("check_out"):
            lines.append(f"- Check-out: {check_out}")
        if prefs := context.get("preferences"):
            lines.append(f"- Preferences: {prefs}")
        return "\n".join(lines)

    @staticmethod
    def _extract_service_request(text: str) -> dict | None:
        """Parse <service_request>{...}</service_request> from LLM output."""
        import re, json
        pattern = r"<service_request>(.*?)</service_request>"
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(1).strip())
            # Validate service_type
            if data.get("service_type") not in VALID_SERVICE_TYPES:
                data["service_type"] = "other"
            return data
        except (json.JSONDecodeError, KeyError):
            logger.warning("service_request_parse_error", extra={"raw": match.group(1)[:200]})
            return None

    @staticmethod
    def _clean_for_tts(text: str) -> str:
        """Strip XML tags from response text before TTS."""
        import re
        text = re.sub(r"<service_request>.*?</service_request>", "", text, flags=re.DOTALL)
        return text.strip()
