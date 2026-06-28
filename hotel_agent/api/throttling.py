
from rest_framework.throttling import UserRateThrottle


class VoiceSessionThrottle(UserRateThrottle):
    scope = "voice_session"