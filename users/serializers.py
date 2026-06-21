from typing import Any, Dict
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Serializer representing the user profile in camelCase format."""

    firstName = serializers.CharField(source="first_name", required=False, allow_blank=True)
    lastName = serializers.CharField(source="last_name", required=False, allow_blank=True)
    avatarUrl = serializers.URLField(source="avatar_url", required=False, allow_null=True)
    googleId = serializers.CharField(source="google_id", required=False, allow_null=True)
    creditsTotal = serializers.IntegerField(source="credits_total", read_only=True)
    creditsUsed = serializers.IntegerField(source="credits_used", read_only=True)
    creditsRemaining = serializers.IntegerField(source="credits_remaining", read_only=True)
    creditsResetAt = serializers.DateTimeField(source="credits_reset_at", read_only=True, allow_null=True)
    onboardingCompleted = serializers.BooleanField(source="onboarding_completed", default=False)
    brandKit = serializers.DictField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "firstName",
            "lastName",
            "avatarUrl",
            "googleId",
            "plan",
            "creditsTotal",
            "creditsUsed",
            "creditsRemaining",
            "creditsResetAt",
            "onboardingCompleted",
            "brandKit",
        ]
        read_only_fields = ["id", "email", "plan", "creditsTotal", "creditsUsed", "creditsRemaining", "creditsResetAt", "brandKit"]


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for registering a new user with 5 free credits."""

    firstName = serializers.CharField(source="first_name", required=True)
    lastName = serializers.CharField(source="last_name", required=True)
    password = serializers.CharField(write_only=True, required=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["email", "password", "firstName", "lastName"]

    def validate_password(self, value: str) -> str:
        """Validate that the password is strong enough according to standard rules."""
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def create(self, validated_data: Dict[str, Any]) -> Any:
        """Create a user with 5 initial free credits."""
        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data.get("first_name", ""),
            last_name=validated_data.get("last_name", ""),
            plan="free",
            credits_total=5,
            credits_remaining=5,
        )
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom Token Obtain Pair Serializer that adds user profile to the response."""

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate credentials and return access/refresh tokens alongside user info."""
        data = super().validate(attrs)
        data["accessToken"] = data.pop("access")
        data["refreshToken"] = data.pop("refresh")
        data["user"] = UserSerializer(self.user).data
        return data


class ForgotPasswordSerializer(serializers.Serializer):
    """Serializer for password reset request."""

    email = serializers.EmailField(required=True)


class ResetPasswordSerializer(serializers.Serializer):
    """Serializer for resetting password using a secure token."""

    token = serializers.CharField(required=True)
    newPassword = serializers.CharField(
        write_only=True, required=True, style={"input_type": "password"}
    )

    def validate_newPassword(self, value: str) -> str:
        """Validate the new password strength."""
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value


class GoogleAuthSerializer(serializers.Serializer):
    """Serializer for Google OAuth 2.0 exchange."""

    code = serializers.CharField(required=True)


class AuthResponseSerializer(serializers.Serializer):
    """Schema for authentication responses containing tokens and user profile."""

    accessToken = serializers.CharField()
    refreshToken = serializers.CharField()
    user = UserSerializer()


class MessageSerializer(serializers.Serializer):
    """Schema for generic API message responses."""

    message = serializers.CharField()

