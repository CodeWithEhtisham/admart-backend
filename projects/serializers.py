import re

from rest_framework import serializers

from projects.models import AdAccount, AdBoostJob, Project, PublishJob, SocialAccount


HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_SHORT = 40  # font names, tone ids, roles and generation defaults
BRAND_TEXT_KEYS = {"headingFont": _SHORT, "bodyFont": _SHORT, "tone": _SHORT, "toneText": 2000}
BRAND_URL_KEYS = ("iconUrl", "watermarkUrl")
BRAND_DEFAULT_KEYS = ("aspect", "style", "voice", "watermark")


def validate_brand_settings(value):
    """Allow only the Brand Kit page's known keys, with bounded sizes."""
    if not isinstance(value, dict):
        raise serializers.ValidationError("Must be an object.")
    allowed = {*BRAND_TEXT_KEYS, *BRAND_URL_KEYS, "colors", "defaults"}
    unknown = set(value) - allowed
    if unknown:
        raise serializers.ValidationError(f"Unknown keys: {', '.join(sorted(unknown))}.")
    for key, limit in BRAND_TEXT_KEYS.items():
        if key in value and (not isinstance(value[key], str) or len(value[key]) > limit):
            raise serializers.ValidationError(f"{key} must be text up to {limit} characters.")
    url_field = serializers.URLField(max_length=1000)
    for key in BRAND_URL_KEYS:
        if value.get(key):
            url_field.run_validation(value[key])
    colors = value.get("colors", [])
    if not isinstance(colors, list) or len(colors) > 8:
        raise serializers.ValidationError("colors must be a list of up to 8 colors.")
    for color in colors:
        if (
            not isinstance(color, dict)
            or set(color) - {"hex", "role"}
            or not HEX_COLOR.match(str(color.get("hex", "")))
            or not isinstance(color.get("role", ""), str)
            or len(color.get("role", "")) > _SHORT
        ):
            raise serializers.ValidationError("Each color needs a #RRGGBB hex and a short role.")
    defaults = value.get("defaults", {})
    if not isinstance(defaults, dict) or set(defaults) - set(BRAND_DEFAULT_KEYS):
        raise serializers.ValidationError(f"defaults may only contain {', '.join(BRAND_DEFAULT_KEYS)}.")
    if any(not isinstance(v, str) or len(v) > _SHORT for v in defaults.values()):
        raise serializers.ValidationError("defaults values must be short text.")
    return value


class ProjectSerializer(serializers.ModelSerializer):
    """Serializer for a Project in camelCase, matching the frontend shape.

    Exposes the per-project brand kit and accepts the snake_case brand fields the
    onboarding flow sends.
    """

    lastAccessedAt = serializers.DateTimeField(source="last_accessed_at", read_only=True, allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)
    brandKit = serializers.SerializerMethodField(read_only=True)

    def get_brandKit(self, obj: Project) -> dict:
        """Return the project's brand kit dict."""
        return obj.brand_kit

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "icon",
            "color",
            "org",
            "brandKit",
            "lastAccessedAt",
            "createdAt",
            "updatedAt",
            # Writable brand kit fields (snake_case, as sent by frontend onboarding).
            "brand_name",
            "brand_industry",
            "brand_color_hex",
            "brand_logo_url",
            "brand_settings",
        ]
        read_only_fields = ["id", "brandKit", "lastAccessedAt", "createdAt", "updatedAt"]
        extra_kwargs = {
            "name": {"required": True, "min_length": 1, "max_length": 80},
            "icon": {"required": False, "allow_blank": True},
            "color": {"required": False, "allow_blank": True},
            "org": {"required": False, "allow_blank": True},
            "brand_name": {"required": False, "allow_blank": True, "write_only": True},
            "brand_industry": {"required": False, "allow_blank": True, "write_only": True},
            "brand_color_hex": {"required": False, "write_only": True},
            "brand_logo_url": {"required": False, "allow_null": True, "write_only": True},
            "brand_settings": {"required": False, "write_only": True, "validators": [validate_brand_settings]},
        }

    def validate_brand_color_hex(self, value):
        if value and not HEX_COLOR.match(value):
            raise serializers.ValidationError("Use a #RRGGBB color.")
        return value


class SocialAccountSerializer(serializers.ModelSerializer):
    """Serializer for a connected social media account scoped to a project."""

    projectId = serializers.UUIDField(source="project_id", read_only=True)
    tokenExpiresAt = serializers.DateTimeField(source="token_expires_at", read_only=True, allow_null=True)
    displayName = serializers.CharField(source="display_name", required=False, allow_blank=True)
    avatarUrl = serializers.URLField(source="avatar_url", required=False, allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = SocialAccount
        fields = [
            "id",
            "projectId",
            "platform",
            "handle",
            "displayName",
            "connected",
            "avatarUrl",
            "tokenExpiresAt",
            "createdAt",
        ]
        read_only_fields = ["id", "projectId", "createdAt", "tokenExpiresAt"]


class PublishJobSerializer(serializers.ModelSerializer):
    assetId = serializers.UUIDField(source="library_asset_id", read_only=True, allow_null=True)
    sourceUrl = serializers.CharField(source="source_url", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    scheduledAt = serializers.DateTimeField(source="scheduled_at", read_only=True, allow_null=True)

    class Meta:
        model = PublishJob
        fields = [
            "id",
            "assetId",
            "kind",
            "sourceUrl",
            "title",
            "platforms",
            "results",
            "status",
            "error",
            "scheduledAt",
            "createdAt",
        ]
        read_only_fields = fields


class AdAccountSerializer(serializers.ModelSerializer):
    projectId = serializers.UUIDField(source="project_id", read_only=True)
    displayName = serializers.CharField(source="display_name", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = AdAccount
        fields = ["id", "projectId", "provider", "handle", "displayName", "connected", "createdAt"]
        read_only_fields = fields


class AdBoostJobSerializer(serializers.ModelSerializer):
    provider = serializers.CharField(source="ad_account.provider", read_only=True)
    assetId = serializers.UUIDField(source="library_asset_id", read_only=True, allow_null=True)
    startDate = serializers.DateField(source="start_date", read_only=True, allow_null=True)
    endDate = serializers.DateField(source="end_date", read_only=True, allow_null=True)
    externalId = serializers.CharField(source="external_id", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = AdBoostJob
        fields = [
            "id",
            "provider",
            "assetId",
            "kind",
            "title",
            "placements",
            "budget",
            "startDate",
            "endDate",
            "status",
            "externalId",
            "error",
            "createdAt",
        ]
        read_only_fields = fields

