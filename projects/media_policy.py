"""What each platform can post (organic) or run as an ad.

Keep this map in lockstep with Admart-frontend/src/utils/platformMedia.js.
"""

PLATFORM_ACCEPTS = {
    "youtube": ["video"],
    "tiktok": ["video"],
    "instagram": ["image", "video"],
    "facebook": ["image", "video"],
    "snapchat": ["image", "video"],
}

ORGANIC_PLATFORMS = ("youtube", "tiktok", "instagram", "facebook")
ADS_PLACEMENTS = ("instagram", "facebook", "tiktok", "snapchat", "youtube")
ADS_PROVIDERS = ("meta", "tiktok", "snap", "google")

PROVIDER_PLACEMENTS = {
    "meta": ("facebook", "instagram"),
    "tiktok": ("tiktok",),
    "snap": ("snapchat",),
    "google": ("youtube",),
}


def platform_accepts(platform: str, kind: str) -> bool:
    return kind in PLATFORM_ACCEPTS.get(platform, [])


def media_block_reason(platform: str, kind: str) -> str:
    if platform_accepts(platform, kind):
        return ""
    accepts = PLATFORM_ACCEPTS.get(platform, [])
    if accepts == ["video"]:
        return "Video only — images cannot be posted here"
    if accepts == ["image"]:
        return "Image only — videos cannot be posted here"
    return f"Does not accept {kind}s"


def validate_organic_platforms(kind: str, platforms: list[str]) -> str:
    """Return an error message, or empty string if ok."""
    if kind not in ("image", "video"):
        return "kind must be image or video"
    if not platforms:
        return "Select at least one platform"
    for platform in platforms:
        if platform == "snapchat":
            return "Snapchat does not support organic posts. Use as ad instead."
        if platform not in ORGANIC_PLATFORMS:
            return f"Unsupported platform: {platform}"
        if not platform_accepts(platform, kind):
            return media_block_reason(platform, kind)
    return ""


def validate_ads_placements(kind: str, provider: str, placements: list[str]) -> str:
    if kind not in ("image", "video"):
        return "kind must be image or video"
    if provider not in ADS_PROVIDERS:
        return f"Unsupported ads provider: {provider}"
    allowed = PROVIDER_PLACEMENTS[provider]
    if not placements:
        return "Select at least one placement"
    for placement in placements:
        if placement not in allowed:
            return f"{provider} does not support placement {placement}"
        if not platform_accepts(placement, kind):
            return media_block_reason(placement, kind)
    return ""
