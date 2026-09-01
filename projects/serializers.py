from rest_framework import serializers

from projects.models import AdAccount, AdBoostJob, Project, PublishJob, SocialAccount


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
        }


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

