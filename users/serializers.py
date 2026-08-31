from typing import Any, Dict
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from users.plans import serialize_plan

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Serializer representing the user profile in camelCase format.

    Accepts both camelCase and snake_case brand fields for write operations
    (the frontend onboarding sends snake_case: brand_name, brand_industry, brand_color_hex).
    """

    firstName = serializers.CharField(source="first_name", required=False, allow_blank=True)
    lastName = serializers.CharField(source="last_name", required=False, allow_blank=True)
    avatarUrl = serializers.URLField(source="avatar_url", required=False, allow_null=True)
    googleId = serializers.CharField(source="google_id", required=False, allow_null=True)
    emailVerified = serializers.BooleanField(source="email_verified", read_only=True)
    creditsTotal = serializers.DecimalField(
        source="credits_total", max_digits=10, decimal_places=4, read_only=True, coerce_to_string=False
    )
    creditsUsed = serializers.DecimalField(
        source="credits_used", max_digits=10, decimal_places=4, read_only=True, coerce_to_string=False
    )
    creditsRemaining = serializers.DecimalField(
        source="credits_remaining", max_digits=10, decimal_places=4, read_only=True, coerce_to_string=False
    )
    creditsResetAt = serializers.DateTimeField(source="credits_reset_at", read_only=True, allow_null=True)
    onboardingCompleted = serializers.BooleanField(source="onboarding_completed", default=False)
    isStaff = serializers.BooleanField(source="is_staff", read_only=True)
    isSuperuser = serializers.BooleanField(source="is_superuser", read_only=True)
    lastActiveAt = serializers.DateTimeField(source="last_active_at", read_only=True, allow_null=True)
    brandKit = serializers.SerializerMethodField(read_only=True)
    projectCount = serializers.SerializerMethodField(read_only=True)
    activeProjectId = serializers.SerializerMethodField(read_only=True)
    planDetails = serializers.SerializerMethodField(read_only=True)

    def get_brandKit(self, obj) -> dict:
        """Return the brand kit dict from the model property."""
        return obj.brand_kit

    def get_projectCount(self, obj) -> int:
        """Number of projects the user owns (frontend routing signal)."""
        return obj.projects.count()

    def get_activeProjectId(self, obj) -> str | None:
        """Resolved active project id (explicit selection or most recent)."""
        from projects.views import resolve_active_project_id

        return resolve_active_project_id(obj)

    def get_planDetails(self, obj) -> dict:
        """Return the public business plan details for the user."""
        return serialize_plan(obj.plan)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "firstName",
            "lastName",
            "avatarUrl",
            "googleId",
            "emailVerified",
            "plan",
            "creditsTotal",
            "creditsUsed",
            "creditsRemaining",
            "creditsResetAt",
            "onboardingCompleted",
            "planDetails",
            "brandKit",
            "projectCount",
            "activeProjectId",
            "isStaff",
            "isSuperuser",
            "lastActiveAt",
            # Writable brand kit fields (snake_case, as sent by frontend onboarding)
            "brand_name",
            "brand_industry",
            "brand_color_hex",
        ]
        read_only_fields = ["id", "email", "plan", "creditsTotal", "creditsUsed", "creditsRemaining", "creditsResetAt", "planDetails", "brandKit", "projectCount", "activeProjectId", "emailVerified"]
        extra_kwargs = {
            "brand_name": {"required": False, "allow_blank": True},
            "brand_industry": {"required": False, "allow_blank": True},
            "brand_color_hex": {"required": False},
        }


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for registering a new user on the free plan."""

    firstName = serializers.CharField(source="first_name", required=False, allow_blank=True)
    lastName = serializers.CharField(source="last_name", required=False, allow_blank=True)
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
        """Create a free-plan user without a paid generation budget."""
        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data.get("first_name", ""),
            last_name=validated_data.get("last_name", ""),
            plan="free",
            credits_total=50,
            credits_remaining=50,
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
    """Serializer for Google OAuth 2.0 code exchange (web) or id_token (mobile)."""

    code = serializers.CharField(required=False, allow_blank=True, default="")
    redirectUri = serializers.CharField(required=False, allow_blank=True, default="")
    redirect_uri = serializers.CharField(required=False, allow_blank=True, default="")
    idToken = serializers.CharField(required=False, allow_blank=True, default="")
    id_token = serializers.CharField(required=False, allow_blank=True, default="")
    intent = serializers.CharField(required=False, allow_blank=True, default="")
    createAccount = serializers.BooleanField(required=False, allow_null=True, default=None)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        code = (attrs.get("code") or "").strip()
        id_token = (attrs.get("idToken") or attrs.get("id_token") or "").strip()
        redirect_uri = (attrs.get("redirectUri") or attrs.get("redirect_uri") or "").strip()
        intent = (attrs.get("intent") or "").strip().lower()
        if intent and intent not in ("login", "register"):
            raise serializers.ValidationError({"intent": "Must be login or register."})
        if not code and not id_token:
            raise serializers.ValidationError({"code": "This field is required."})
        if code and not redirect_uri:
            raise serializers.ValidationError({"redirectUri": "This field is required."})
        return {
            "code": code,
            "redirect_uri": redirect_uri,
            "id_token": id_token,
            "intent": intent,
            "create_account": attrs.get("createAccount"),
        }


class AuthResponseSerializer(serializers.Serializer):
    """Schema for authentication responses containing tokens and user profile."""

    accessToken = serializers.CharField()
    refreshToken = serializers.CharField()
    user = UserSerializer()


class MessageSerializer(serializers.Serializer):
    """Schema for generic API message responses."""

    message = serializers.CharField()


class OnboardingCompleteSerializer(serializers.Serializer):
    """Serializer for completing onboarding — saves platforms, brand info, and optional prompt."""

    connectedPlatforms = serializers.ListField(
        child=serializers.ChoiceField(choices=["tiktok", "youtube", "instagram", "facebook"]),
        required=False,
        default=list,
    )
    projectName = serializers.CharField(required=False, allow_blank=True, default="", max_length=80)
    brandName = serializers.CharField(required=False, allow_blank=True, default="")
    industry = serializers.CharField(required=False, allow_blank=True, default="")
    brandColorHex = serializers.CharField(required=False, default="#2563eb")
    prompt = serializers.CharField(required=False, allow_blank=True, default="")
    template = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
