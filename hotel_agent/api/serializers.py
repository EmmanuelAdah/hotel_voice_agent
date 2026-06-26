"""API serializers for Hotel Voice Agent."""
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from hotel_agent.core.models import User, Room, Booking, ServiceRequest, VoiceSession


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["role"] = user.role
        token["name"] = user.full_name
        return token


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "phone",
            "role", "preferences", "password", "confirm_password", "created_at",
        ]
        read_only_fields = ["id", "role", "created_at"]

    def validate(self, attrs):
        if attrs.get("password") != attrs.pop("confirm_password", None):
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UserBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "full_name", "role"]
        read_only_fields = fields


class RoomSerializer(serializers.ModelSerializer):
    room_type_display = serializers.CharField(source="get_room_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Room
        fields = [
            "id", "number", "floor", "room_type", "room_type_display",
            "status", "status_display", "capacity", "price_per_night",
            "amenities", "description",
        ]


class BookingSerializer(serializers.ModelSerializer):
    guest = UserBriefSerializer(read_only=True)
    room = RoomSerializer(read_only=True)
    room_id = serializers.UUIDField(write_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    nights = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id", "confirmation_code", "guest", "room", "room_id",
            "check_in", "check_out", "status", "status_display",
            "adults", "children", "total_price", "special_requests",
            "nights", "created_at",
        ]
        read_only_fields = ["id", "confirmation_code", "total_price", "status", "created_at"]

    def get_nights(self, obj) -> int:
        return (obj.check_out - obj.check_in).days

    def validate(self, attrs):
        check_in = attrs.get("check_in")
        check_out = attrs.get("check_out")
        if check_in and check_out and check_out <= check_in:
            raise serializers.ValidationError("Check-out must be after check-in.")
        return attrs

    def create(self, validated_data):
        room_id = validated_data.pop("room_id")
        try:
            room = Room.objects.get(id=room_id, status=Room.Status.AVAILABLE, is_active=True)
        except Room.DoesNotExist:
            raise serializers.ValidationError({"room_id": "Room not available."})

        nights = (validated_data["check_out"] - validated_data["check_in"]).days
        total_price = room.price_per_night * nights

        return Booking.objects.create(
            guest=self.context["request"].user,
            room=room,
            total_price=total_price,
            **validated_data,
        )


class ServiceRequestSerializer(serializers.ModelSerializer):
    guest = UserBriefSerializer(read_only=True)
    assigned_to = UserBriefSerializer(read_only=True)
    service_type_display = serializers.CharField(source="get_service_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)

    class Meta:
        model = ServiceRequest
        fields = [
            "id", "booking", "guest", "assigned_to", "service_type",
            "service_type_display", "priority", "priority_display",
            "status", "status_display", "description", "notes",
            "scheduled_at", "completed_at", "rating", "feedback",
            "voice_session_id", "created_at",
        ]
        read_only_fields = ["id", "guest", "assigned_to", "completed_at", "voice_session_id", "created_at"]


class VoiceSessionSerializer(serializers.ModelSerializer):
    guest = UserBriefSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    turn_count = serializers.SerializerMethodField()

    class Meta:
        model = VoiceSession
        fields = [
            "id", "guest", "booking", "status", "status_display",
            "started_at", "ended_at", "duration_seconds",
            "tokens_used", "tts_characters", "turn_count",
            "intent_detected", "metadata",
        ]
        read_only_fields = fields

    def get_turn_count(self, obj) -> int:
        return len([m for m in obj.transcript if m.get("role") == "user"])


class VoiceInputSerializer(serializers.Serializer):
    text = serializers.CharField(required=False, max_length=2000)
    generate_audio = serializers.BooleanField(default=True)
    language = serializers.CharField(default="en", max_length=5)
