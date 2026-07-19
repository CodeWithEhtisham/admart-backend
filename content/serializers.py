from rest_framework import serializers

from content.catalog import CAPABILITIES, resolve_model
from content.models import ImageJob

MAX_PROMPT_LEN = 2000
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
    prompt = serializers.CharField(required=False, allow_blank=True, max_length=MAX_PROMPT_LEN)
    negativePrompt = serializers.CharField(required=False, allow_blank=True, max_length=MAX_PROMPT_LEN)
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
