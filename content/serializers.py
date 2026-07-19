from rest_framework import serializers

from content.catalog import CAPABILITIES, resolve_model
from content.models import ImageJob, LibraryAsset, VideoJob
from content.video_catalog import VIDEO_CAPABILITIES, get_model_entry, resolve_video_model

ALLOWED_ASPECT = {
    "auto",
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "3:2",
    "2:3",
    "21:9",
    "5:4",
    "4:5",
}


class ImageJobCreateSerializer(serializers.Serializer):
    capability = serializers.ChoiceField(choices=CAPABILITIES)
    model = serializers.CharField(required=False, allow_blank=True, max_length=200)
    prompt = serializers.CharField(required=False, allow_blank=True)
    negativePrompt = serializers.CharField(required=False, allow_blank=True)
    imageUrls = serializers.ListField(
        child=serializers.URLField(max_length=2000),
        required=False,
        allow_empty=True,
    )
    aspectRatio = serializers.CharField(required=False, allow_blank=True)
    imageSize = serializers.JSONField(required=False)
    numImages = serializers.IntegerField(required=False, min_value=1, max_value=4, default=1)
    seed = serializers.IntegerField(required=False, allow_null=True)
    outputFormat = serializers.ChoiceField(
        choices=["jpeg", "png", "webp"], required=False, allow_null=True
    )
    resolution = serializers.ChoiceField(
        choices=["0.5K", "1K", "2K", "4K"], required=False, allow_null=True
    )
    systemPrompt = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    enableWebSearch = serializers.BooleanField(required=False)
    thinkingLevel = serializers.ChoiceField(
        choices=["minimal", "high"], required=False, allow_null=True
    )
    numInferenceSteps = serializers.IntegerField(required=False, min_value=1, max_value=100)
    guidanceScale = serializers.FloatField(required=False)
    acceleration = serializers.ChoiceField(
        choices=["none", "regular", "high"], required=False, allow_null=True
    )
    enableSafetyChecker = serializers.BooleanField(required=False)
    style = serializers.CharField(required=False, allow_blank=True)
    stylePreset = serializers.CharField(required=False, allow_blank=True)
    renderingSpeed = serializers.ChoiceField(
        choices=["TURBO", "BALANCED", "QUALITY"], required=False, allow_null=True
    )
    expandPrompt = serializers.BooleanField(required=False)
    scale = serializers.FloatField(required=False, min_value=1, max_value=8)
    faceEnhance = serializers.BooleanField(required=False)
    upscaleModel = serializers.CharField(required=False, allow_blank=True)
    rembgModel = serializers.ChoiceField(
        choices=["light", "heavy", "portrait"], required=False, allow_null=True
    )
    operatingResolution = serializers.ChoiceField(
        choices=["1024x1024", "2048x2048"], required=False, allow_null=True
    )
    outputMask = serializers.BooleanField(required=False)
    refineForeground = serializers.BooleanField(required=False)
    # GPT Image 2
    quality = serializers.ChoiceField(
        choices=["auto", "low", "medium", "high"], required=False, allow_null=True
    )
    maskUrl = serializers.URLField(required=False, allow_blank=True, max_length=2000)

    def validate(self, attrs):
        capability = attrs["capability"]
        prompt = (attrs.get("prompt") or "").strip()
        urls = attrs.get("imageUrls") or []

        if capability == "textToImage":
            if not prompt:
                raise serializers.ValidationError({"prompt": "prompt is required"})
            attrs["prompt"] = prompt
        elif capability == "edit":
            if not prompt:
                raise serializers.ValidationError({"prompt": "prompt is required"})
            if not urls:
                raise serializers.ValidationError({"imageUrls": "imageUrls[0] is required"})
            attrs["prompt"] = prompt
        elif capability == "multiEdit":
            if not prompt:
                raise serializers.ValidationError({"prompt": "prompt is required"})
            if len(urls) < 2:
                raise serializers.ValidationError(
                    {"imageUrls": "multiEdit requires at least 2 imageUrls"}
                )
            if len(urls) > 6:
                raise serializers.ValidationError(
                    {"imageUrls": "multiEdit allows at most 6 imageUrls"}
                )
            attrs["prompt"] = prompt
        elif capability in ("upscale", "removeBackground"):
            if not urls:
                raise serializers.ValidationError({"imageUrls": "imageUrls[0] is required"})

        if attrs.get("aspectRatio") and attrs["aspectRatio"] not in ALLOWED_ASPECT:
            raise serializers.ValidationError({"aspectRatio": "Invalid aspectRatio"})

        try:
            attrs["model"] = resolve_model(capability, attrs.get("model"))
        except ValueError as exc:
            raise serializers.ValidationError({"model": str(exc)}) from exc

        for url in urls:
            if not str(url).startswith(("https://", "http://")):
                raise serializers.ValidationError(
                    {"imageUrls": "imageUrls must be http(s) URLs"}
                )

        attrs["imageUrls"] = urls
        attrs["numImages"] = attrs.get("numImages") or 1
        return attrs


class ImageJobSerializer(serializers.ModelSerializer):
    projectId = serializers.UUIDField(source="project_id", read_only=True)
    maskImage = serializers.JSONField(source="mask_image", read_only=True)
    creditsUsed = serializers.DecimalField(
        source="credits_used", max_digits=8, decimal_places=2, read_only=True, allow_null=True
    )
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = ImageJob
        fields = [
            "id",
            "projectId",
            "capability",
            "model",
            "status",
            "prompt",
            "images",
            "maskImage",
            "error",
            "creditsUsed",
            "seed",
            "createdAt",
            "updatedAt",
        ]


class VideoJobCreateSerializer(serializers.Serializer):
    capability = serializers.ChoiceField(choices=VIDEO_CAPABILITIES)
    model = serializers.CharField(required=False, allow_blank=True, max_length=200)
    prompt = serializers.CharField(required=False, allow_blank=True)
    negativePrompt = serializers.CharField(required=False, allow_blank=True)
    startImageUrl = serializers.URLField(required=False, allow_blank=True, max_length=2000)
    endImageUrl = serializers.URLField(required=False, allow_blank=True, max_length=2000)
    imageUrls = serializers.ListField(
        child=serializers.URLField(max_length=2000),
        required=False,
        allow_empty=True,
    )
    aspectRatio = serializers.CharField(required=False, allow_blank=True)
    duration = serializers.CharField(required=False, allow_blank=True, max_length=32)
    resolution = serializers.CharField(required=False, allow_blank=True, max_length=32)
    generateAudio = serializers.BooleanField(required=False)
    seed = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        capability = attrs["capability"]
        prompt = (attrs.get("prompt") or "").strip()
        if not prompt:
            raise serializers.ValidationError({"prompt": "prompt is required"})
        attrs["prompt"] = prompt

        try:
            attrs["model"] = resolve_video_model(capability, attrs.get("model"))
        except ValueError as exc:
            raise serializers.ValidationError({"model": str(exc)}) from exc

        entry = get_model_entry(capability, attrs["model"]) or {}
        inputs = entry.get("inputs") or "text"
        urls = list(attrs.get("imageUrls") or [])
        start = (attrs.get("startImageUrl") or "").strip()
        end = (attrs.get("endImageUrl") or "").strip()
        if not start and urls:
            start = urls[0]
        if not end and len(urls) > 1:
            end = urls[1]

        for label, url in (("startImageUrl", start), ("endImageUrl", end)):
            if url and not str(url).startswith(("https://", "http://")):
                raise serializers.ValidationError({label: "must be an http(s) URL"})

        if inputs == "image":
            if not start:
                raise serializers.ValidationError(
                    {"startImageUrl": "This model requires a start image"}
                )
        elif inputs == "firstLast":
            if not start:
                raise serializers.ValidationError(
                    {"startImageUrl": "This model requires a start frame"}
                )
            if not end:
                raise serializers.ValidationError(
                    {"endImageUrl": "This model requires an end frame"}
                )

        attrs["startImageUrl"] = start or None
        attrs["endImageUrl"] = end or None
        attrs["imageUrls"] = [u for u in [start, end] if u]

        # Soft-check duration/aspect against catalog options when provided
        fields = entry.get("fields") or {}
        if attrs.get("duration") and "duration" in fields:
            allowed = fields["duration"]
            if attrs["duration"] not in allowed:
                raise serializers.ValidationError(
                    {"duration": f"Must be one of: {', '.join(allowed)}"}
                )
        if attrs.get("aspectRatio") and "aspectRatio" in fields:
            allowed = fields["aspectRatio"]
            if attrs["aspectRatio"] not in allowed:
                raise serializers.ValidationError(
                    {"aspectRatio": f"Must be one of: {', '.join(allowed)}"}
                )
        if attrs.get("resolution") and "resolution" in fields:
            allowed = fields["resolution"]
            if attrs["resolution"] not in allowed:
                raise serializers.ValidationError(
                    {"resolution": f"Must be one of: {', '.join(allowed)}"}
                )

        return attrs


class VideoJobSerializer(serializers.ModelSerializer):
    projectId = serializers.UUIDField(source="project_id", read_only=True)
    creditsUsed = serializers.DecimalField(
        source="credits_used", max_digits=8, decimal_places=2, read_only=True, allow_null=True
    )
    durationSeconds = serializers.IntegerField(
        source="duration_seconds", read_only=True, allow_null=True
    )
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = VideoJob
        fields = [
            "id",
            "projectId",
            "capability",
            "model",
            "status",
            "prompt",
            "video",
            "error",
            "creditsUsed",
            "seed",
            "durationSeconds",
            "createdAt",
            "updatedAt",
        ]


class LibraryAssetSerializer(serializers.ModelSerializer):
    projectId = serializers.UUIDField(source="project_id", read_only=True)
    mediaType = serializers.CharField(source="media_type", read_only=True)
    thumbnailUrl = serializers.CharField(source="thumbnail_url", read_only=True, allow_null=True)
    sourceUrl = serializers.CharField(source="source_url", read_only=True)
    durationSeconds = serializers.IntegerField(
        source="duration_seconds", read_only=True, allow_null=True
    )
    jobId = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = LibraryAsset
        fields = [
            "id",
            "projectId",
            "mediaType",
            "title",
            "status",
            "thumbnailUrl",
            "sourceUrl",
            "prompt",
            "model",
            "capability",
            "durationSeconds",
            "width",
            "height",
            "jobId",
            "createdAt",
            "updatedAt",
        ]

    def get_jobId(self, obj) -> str | None:
        if obj.video_job_id:
            return str(obj.video_job_id)
        if obj.image_job_id:
            return str(obj.image_job_id)
        return None
