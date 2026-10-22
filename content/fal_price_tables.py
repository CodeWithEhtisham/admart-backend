"""fal price data for the curated catalog: last known unit prices, overrides, and option rates.

content.pricing reads live prices from fal (via the FalPriceSnapshot table) and uses these
tables to (a) fall back when fal is unreachable, (b) replace prices fal's pricing API cannot
express, and (c) scale a unit price by the options a user picks (resolution, audio, quality).

Option rates are copied from each model's fal.ai page. They are stored as fal publishes them,
next to a "base": the option that fal's pricing API price refers to. The billed price is
live unit price x (option rate / base), so when fal changes its price every option follows.
"""

from __future__ import annotations

# Values from fal's /v1/models/pricing endpoint on 2026-10-20, fetched for every catalog
# model. Used when FAL_KEY/network is unavailable and as the reference for the price guard
# in content.pricing.resolve_price. Models fal only returns a "$1 per unit" placeholder for
# are in PRICE_OVERRIDES instead.
FALLBACK_PRICES: dict[str, dict[str, str]] = {
    "fal-ai/flux/dev": {"unit_price": "0.025", "unit": "megapixels", "currency": "USD"},
    "fal-ai/flux/schnell": {"unit_price": "0.003", "unit": "megapixels", "currency": "USD"},
    "fal-ai/flux-2-pro": {"unit_price": "0.03", "unit": "processed megapixels", "currency": "USD"},
    "fal-ai/flux-pro/v1.1": {"unit_price": "0.04", "unit": "megapixels", "currency": "USD"},
    "fal-ai/nano-banana-2": {"unit_price": "0.08", "unit": "images", "currency": "USD"},
    "fal-ai/nano-banana-pro": {"unit_price": "0.15", "unit": "images", "currency": "USD"},
    "fal-ai/nano-banana": {"unit_price": "0.0398", "unit": "images", "currency": "USD"},
    "fal-ai/ideogram/v3": {"unit_price": "0.03", "unit": "images", "currency": "USD"},
    "bytedance/seedream/v5/pro/text-to-image": {"unit_price": "0.0675", "unit": "units", "currency": "USD"},
    "fal-ai/nano-banana-2/edit": {"unit_price": "0.08", "unit": "images", "currency": "USD"},
    "fal-ai/nano-banana-pro/edit": {"unit_price": "0.15", "unit": "images", "currency": "USD"},
    "fal-ai/nano-banana/edit": {"unit_price": "0.0398", "unit": "images", "currency": "USD"},
    "fal-ai/flux-pro/kontext": {"unit_price": "0.04", "unit": "images", "currency": "USD"},
    "bytedance/seedream/v5/pro/edit": {"unit_price": "0.0675", "unit": "units", "currency": "USD"},
    "wan/v2.6/image-to-image": {"unit_price": "0.03", "unit": "images", "currency": "USD"},
    "fal-ai/esrgan": {"unit_price": "0.000575", "unit": "compute seconds", "currency": "USD"},
    "fal-ai/seedvr/upscale/image": {"unit_price": "0.001", "unit": "megapixels", "currency": "USD"},
    "fal-ai/topaz/upscale/image": {"unit_price": "0.01", "unit": "megapixels", "currency": "USD"},
    "fal-ai/recraft/upscale/crisp": {"unit_price": "0.004", "unit": "images", "currency": "USD"},
    "fal-ai/ideogram/upscale": {"unit_price": "0.06", "unit": "images", "currency": "USD"},
    "fal-ai/birefnet/v2": {"unit_price": "0.000575", "unit": "compute seconds", "currency": "USD"},
    "fal-ai/birefnet": {"unit_price": "0.000575", "unit": "compute seconds", "currency": "USD"},
    "fal-ai/bria/background/remove": {"unit_price": "0.018", "unit": "generations", "currency": "USD"},
    "fal-ai/veo3.1": {"unit_price": "0.4", "unit": "seconds", "currency": "USD"},
    "fal-ai/veo3.1/image-to-video": {"unit_price": "0.4", "unit": "seconds", "currency": "USD"},
    "fal-ai/veo3.1/first-last-frame-to-video": {"unit_price": "0.4", "unit": "seconds", "currency": "USD"},
    "fal-ai/veo3.1/fast": {"unit_price": "0.15", "unit": "seconds", "currency": "USD"},
    "fal-ai/veo3.1/fast/image-to-video": {"unit_price": "0.15", "unit": "seconds", "currency": "USD"},
    "fal-ai/veo3.1/fast/first-last-frame-to-video": {"unit_price": "0.15", "unit": "seconds", "currency": "USD"},
    "bytedance/seedance-2.0/text-to-video": {"unit_price": "0.014", "unit": "1000 tokens", "currency": "USD"},
    "bytedance/seedance-2.0/image-to-video": {"unit_price": "0.014", "unit": "1000 tokens", "currency": "USD"},
    "bytedance/seedance-2.5/text-to-video": {"unit_price": "0.0214", "unit": "1000 tokens", "currency": "USD"},
    "bytedance/seedance-2.5/image-to-video": {"unit_price": "0.0214", "unit": "1000 tokens", "currency": "USD"},
    "fal-ai/kling-video/v2.5-turbo/pro/text-to-video": {"unit_price": "0.07", "unit": "seconds", "currency": "USD"},
    "fal-ai/kling-video/v2.5-turbo/pro/image-to-video": {"unit_price": "0.07", "unit": "seconds", "currency": "USD"},
    "fal-ai/kling-video/v2.1/master/text-to-video": {"unit_price": "0.28", "unit": "seconds", "currency": "USD"},
    "fal-ai/kling-video/v2.1/master/image-to-video": {"unit_price": "0.28", "unit": "seconds", "currency": "USD"},
    "fal-ai/kling-video/v2.6/pro/image-to-video": {"unit_price": "0.07", "unit": "seconds", "currency": "USD"},
    "fal-ai/kling-video/v3/pro/text-to-video": {"unit_price": "0.14", "unit": "seconds", "currency": "USD"},
    "fal-ai/kling-video/v3/pro/image-to-video": {"unit_price": "0.14", "unit": "seconds", "currency": "USD"},
    "fal-ai/kling-video/v3/standard/text-to-video": {"unit_price": "0.14", "unit": "seconds", "currency": "USD"},
    "fal-ai/kling-video/v3/standard/image-to-video": {"unit_price": "0.14", "unit": "seconds", "currency": "USD"},
    "fal-ai/minimax/hailuo-02/standard/text-to-video": {"unit_price": "0.045", "unit": "seconds", "currency": "USD"},
    "fal-ai/minimax/hailuo-02/standard/image-to-video": {"unit_price": "0.045", "unit": "seconds", "currency": "USD"},
    # fal returns a 35%-off promotion (0.0325 / 0.01625) that ends 2026-10-31; the fallback is the
    # list price so an offline server never bills below cost after the promotion.
    "minimax/h3-max/text-to-video": {"unit_price": "0.05", "unit": "seconds", "currency": "USD"},
    "minimax/h3-max/image-to-video": {"unit_price": "0.05", "unit": "seconds", "currency": "USD"},
    "minimax/h3-max-turbo/text-to-video": {"unit_price": "0.025", "unit": "seconds", "currency": "USD"},
    "wan/v2.6/text-to-video": {"unit_price": "0.1", "unit": "seconds", "currency": "USD"},
    "wan/v2.6/image-to-video": {"unit_price": "0.1", "unit": "seconds", "currency": "USD"},
    "alibaba/wan-3.0/text-to-video": {"unit_price": "0.05", "unit": "seconds", "currency": "USD"},
    "fal-ai/pixverse/v5/text-to-video": {"unit_price": "0.05", "unit": "video segments", "currency": "USD"},
    "fal-ai/pixverse/v5/image-to-video": {"unit_price": "0.05", "unit": "video segments", "currency": "USD"},
    "fal-ai/ltx-video-13b-distilled": {"unit_price": "0.04", "unit": "videos", "currency": "USD"},
    # Added to the catalog 2026-10-20 (same source).
    "blackforestlabs/flux-3/text-to-image": {"unit_price": "0.048", "unit": "megapixels", "currency": "USD"},
    "fal-ai/flux-pro/v1.1-ultra": {"unit_price": "0.06", "unit": "images", "currency": "USD"},
    "fal-ai/flux-2": {"unit_price": "0.012", "unit": "megapixels", "currency": "USD"},
    "fal-ai/z-image/turbo": {"unit_price": "0.005", "unit": "megapixels", "currency": "USD"},
    "fal-ai/bytedance/seedream/v4.5/text-to-image": {"unit_price": "0.04", "unit": "images", "currency": "USD"},
    "fal-ai/bytedance/seedream/v4.5/edit": {"unit_price": "0.04", "unit": "images", "currency": "USD"},
    "xai/grok-imagine-image": {"unit_price": "0.02", "unit": "images", "currency": "USD"},
    "xai/grok-imagine-image/edit": {"unit_price": "0.02", "unit": "images", "currency": "USD"},
    "google/gemini-omni-flash/v1.1/text-to-video": {"unit_price": "0.03", "unit": "seconds", "currency": "USD"},
    "google/gemini-omni-flash/v1.1/image-to-video": {"unit_price": "0.03", "unit": "seconds", "currency": "USD"},
    "bytedance/seedance-2.0/fast/text-to-video": {"unit_price": "0.0112", "unit": "1000 tokens", "currency": "USD"},
    "bytedance/seedance-2.0/fast/image-to-video": {"unit_price": "0.0112", "unit": "1000 tokens", "currency": "USD"},
    "bytedance/seedance-2.0/mini/text-to-video": {"unit_price": "0.007", "unit": "1000 tokens", "currency": "USD"},
    "fal-ai/kling-video/o3/pro/text-to-video": {"unit_price": "0.14", "unit": "seconds", "currency": "USD"},
    "fal-ai/kling-video/o3/pro/image-to-video": {"unit_price": "0.14", "unit": "seconds", "currency": "USD"},
    "fal-ai/kling-video/v2.6/pro/text-to-video": {"unit_price": "0.07", "unit": "seconds", "currency": "USD"},
    "fal-ai/pixverse/v6/text-to-video": {"unit_price": "0.005", "unit": "seconds", "currency": "USD"},
    "fal-ai/pixverse/v6/image-to-video": {"unit_price": "0.005", "unit": "seconds", "currency": "USD"},
    "minimax/h3/text-to-video": {"unit_price": "0.05", "unit": "seconds", "currency": "USD"},
    "minimax/h3/image-to-video": {"unit_price": "0.05", "unit": "seconds", "currency": "USD"},
    # List price; fal shows a 35%-off promotion (0.01625) that ends 2026-10-31.
    "minimax/h3-max-turbo/image-to-video": {"unit_price": "0.025", "unit": "seconds", "currency": "USD"},
    "xai/grok-imagine-video/text-to-video": {"unit_price": "0.05", "unit": "seconds", "currency": "USD"},
    "xai/grok-imagine-video/image-to-video": {"unit_price": "0.05", "unit": "seconds", "currency": "USD"},
    "alibaba/wan-3.0/image-to-video": {"unit_price": "0.05", "unit": "seconds", "currency": "USD"},
}

# fal's pricing API answers "$1 per unit" for these token-billed models, so the live value is
# never used. Prices from the fal model pages on 2026-10-20: GPT Image is USD per 1024x1024
# image at high quality (fal's default); Nano Banana 2.1 is USD per 1K image.
_GPT_IMAGE_2 = {"unit_price": "0.211", "unit": "images", "currency": "USD"}
_GPT_IMAGE_2_5 = {"unit_price": "0.05268", "unit": "images", "currency": "USD"}
_NANO_BANANA_2_1 = {"unit_price": "0.04", "unit": "images", "currency": "USD"}
PRICE_OVERRIDES: dict[str, dict[str, str]] = {
    "openai/gpt-image-2": _GPT_IMAGE_2,
    "openai/gpt-image-2/edit": _GPT_IMAGE_2,
    "openai/gpt-image-2.5/flare/text-to-image": _GPT_IMAGE_2_5,
    "openai/gpt-image-2.5/flare/edit": _GPT_IMAGE_2_5,
    "openai/gpt-image-2.5/sunburst/text-to-image": _GPT_IMAGE_2_5,
    "openai/gpt-image-2.5/sunburst/edit": _GPT_IMAGE_2_5,
    "google/nano-banana-2.1": _NANO_BANANA_2_1,
    "google/nano-banana-2.1/edit": _NANO_BANANA_2_1,
}

# GPT Image: USD per image by quality, for three output-size buckets (fal model pages):
# up to 1920x1080 (the 1024x1024 row is the dearest of these), up to 2560x1440, and 3840x2160.
GPT_IMAGE_BUCKET_PIXELS = (1920 * 1080, 2560 * 1440)
_GPT_2_RATES = {
    "low": ("0.006", "0.007", "0.012"),
    "medium": ("0.053", "0.056", "0.101"),
    "high": ("0.211", "0.222", "0.401"),
}
_GPT_2_5_RATES = {
    "low": ("0.00588", "0.00615", "0.01113"),
    "medium": ("0.01317", "0.01434", "0.02595"),
    "high": ("0.05268", "0.05529", "0.10008"),
}
GPT_IMAGE_RATES: dict[str, dict[str, tuple[str, str, str]]] = {
    "openai/gpt-image-2": _GPT_2_RATES,
    "openai/gpt-image-2/edit": _GPT_2_RATES,
    "openai/gpt-image-2.5/flare/text-to-image": _GPT_2_5_RATES,
    "openai/gpt-image-2.5/flare/edit": _GPT_2_5_RATES,
    "openai/gpt-image-2.5/sunburst/text-to-image": _GPT_2_5_RATES,
    "openai/gpt-image-2.5/sunburst/edit": _GPT_2_5_RATES,
}

# Per-image options, keyed by the Admart setting that changes the price (fal model pages).
_NANO_2 = {"option": "resolution", "base": "0.08", "default": "1k",
           "rates": {"0.5k": "0.06", "1k": "0.08", "2k": "0.12", "4k": "0.16"}}
_NANO_PRO = {"option": "resolution", "base": "0.15", "default": "1k",
             "rates": {"1k": "0.15", "2k": "0.15", "4k": "0.30"}}
_NANO_2_1 = {"option": "resolution", "base": "0.04", "default": "1k",
             "rates": {"0.5k": "0.04", "1k": "0.04", "2k": "0.059", "4k": "0.134"}}
IMAGE_OPTION_RATES: dict[str, dict] = {
    "fal-ai/nano-banana-2": _NANO_2,
    "fal-ai/nano-banana-2/edit": _NANO_2,
    "fal-ai/nano-banana-pro": _NANO_PRO,
    "fal-ai/nano-banana-pro/edit": _NANO_PRO,
    "google/nano-banana-2.1": _NANO_2_1,
    "google/nano-banana-2.1/edit": _NANO_2_1,
    "fal-ai/ideogram/v3": {"option": "renderingSpeed", "base": "0.03", "default": "balanced",
                           "rates": {"turbo": "0.03", "balanced": "0.06", "quality": "0.09"}},
    # Flux 3 bills per megapixel and sizes its 1K output from the aspect ratio (e.g. 1376x768 for
    # 16:9). Admart sends no resolution, so bill 2 MP: covers any 1K shape if fal rounds MP up.
    "blackforestlabs/flux-3/text-to-image": {"option": "resolution", "base": "0.048", "default": "1k",
                                             "rates": {"1k": "0.096"}},
}

# Flat USD surcharges per output image (fal model pages).
WEB_SEARCH_USD = {
    "fal-ai/nano-banana-2": "0.015", "fal-ai/nano-banana-2/edit": "0.015",
    "fal-ai/nano-banana-pro": "0.015", "fal-ai/nano-banana-pro/edit": "0.015",
}
HIGH_THINKING_USD = {"fal-ai/nano-banana-2": "0.002", "fal-ai/nano-banana-2/edit": "0.002"}
# USD per input image of an edit. GPT Image bills input image tokens ($8 per 1M): ~5k tokens
# for a high-fidelity 1024x1024 input. Nano Banana 2.1: +$0.004 for two 1K inputs.
INPUT_IMAGE_USD = {
    "openai/gpt-image-2/edit": "0.04",
    "openai/gpt-image-2.5/flare/edit": "0.04",
    "openai/gpt-image-2.5/sunburst/edit": "0.04",
    "google/nano-banana-2.1/edit": "0.002",
    "xai/grok-imagine-image/edit": "0.002",
}

# Seedream 5 Pro: $0.0675 up to 1536x1536 pixels, $0.135 up to 2048x2048 (fal model page).
SEEDREAM_AREA_MODELS = {"bytedance/seedream/v5/pro/text-to-image", "bytedance/seedream/v5/pro/edit"}
SEEDREAM_TIER_PIXELS = (1536 * 1536, 2048 * 2048)

# Video options: USD per billed unit by resolution -> (with audio, without audio). "" is the key
# for a model without a resolution choice; "default" is what fal renders when none is sent.
_VEO = {"base": "0.40", "default": "720p",
        "rates": {"720p": ("0.40", "0.20"), "1080p": ("0.40", "0.20"), "4k": ("0.60", "0.40")}}
_VEO_FAST = {"base": "0.15", "default": "720p",
             "rates": {"720p": ("0.15", "0.10"), "1080p": ("0.15", "0.10"), "4k": ("0.35", "0.30")}}
# Kling 3: fal's model pages say Pro $0.112/$0.168 and Standard $0.084/$0.126 per second
# (audio off/on), the API says $0.14, and fal.ai/kling-3 quotes twice the model-page rates
# (up to $0.392/s). Until a real invoice settles it, bill the highest published rate.
_KLING_3_PRO = {"base": "0.14", "default": "", "rates": {"": ("0.336", "0.224")}}
_KLING_3_STANDARD = {"base": "0.14", "default": "", "rates": {"": ("0.252", "0.168")}}
_KLING_2_6 = {"base": "0.07", "default": "", "rates": {"": ("0.14", "0.07")}}
# Seedance bills per 1000 tokens: 2.0 has a cheaper 4K rate; 2.5 publishes none (480p/720p only).
_SEEDANCE_2_0 = {"base": "0.014", "default": "720p",
                 "rates": {"480p": ("0.014", "0.014"), "720p": ("0.014", "0.014"),
                           "1080p": ("0.014", "0.014"), "4k": ("0.008", "0.008")}}
# Admart sends no resolution for these, so the defaults are worst cases or fal's form default.
_WAN_2_6 = {"base": "0.10", "default": "1080p", "rates": {"720p": ("0.10", "0.10"), "1080p": ("0.15", "0.15")}}
_WAN_3_0 = {"base": "0.05", "default": "1080p",
            "rates": {"480p": ("0.05", "0.05"), "720p": ("0.10", "0.10"), "1080p": ("0.20", "0.20")}}
_H3_MAX = {"base": "0.05", "default": "768p",
           "rates": {"480p": ("0.05", "0.05"), "768p": ("0.08", "0.08"), "1080p": ("0.16", "0.16")}}
_H3_MAX_TURBO = {"base": "0.025", "default": "768p",
                 "rates": {"480p": ("0.025", "0.025"), "768p": ("0.04", "0.04"), "1080p": ("0.08", "0.08")}}
# Models added 2026-10-20 (fal model pages). fal's pricing API reports the cheapest resolution.
_GEMINI_OMNI = {"base": "0.03", "default": "720p",
                "rates": {"360p": ("0.03", "0.03"), "720p": ("0.10", "0.10"),
                          "1080p": ("0.15", "0.15"), "4k": ("0.30", "0.30")}}
_KLING_O3_PRO = {"base": "0.14", "default": "", "rates": {"": ("0.14", "0.112")}}
# PixVerse v6 audio is off unless generate_audio_switch is sent, which Admart never does.
_PIXVERSE_6 = {"base": "0.005", "default": "720p",
               "rates": {"360p": ("0.025", "0.025"), "540p": ("0.035", "0.035"),
                         "720p": ("0.045", "0.045"), "1080p": ("0.09", "0.09")}}
_H3 = {"base": "0.05", "default": "2k",
       "rates": {"480p": ("0.05", "0.05"), "768p": ("0.06", "0.06"), "2k": ("0.13", "0.13"), "4k": ("0.16", "0.16")}}
_GROK_VIDEO = {"base": "0.05", "default": "720p", "rates": {"480p": ("0.05", "0.05"), "720p": ("0.07", "0.07")}}
VIDEO_OPTION_RATES: dict[str, dict] = {
    "fal-ai/veo3.1": _VEO,
    "fal-ai/veo3.1/image-to-video": _VEO,
    "fal-ai/veo3.1/first-last-frame-to-video": _VEO,
    "fal-ai/veo3.1/fast": _VEO_FAST,
    "fal-ai/veo3.1/fast/image-to-video": _VEO_FAST,
    "fal-ai/veo3.1/fast/first-last-frame-to-video": _VEO_FAST,
    "fal-ai/kling-video/v3/pro/text-to-video": _KLING_3_PRO,
    "fal-ai/kling-video/v3/pro/image-to-video": _KLING_3_PRO,
    "fal-ai/kling-video/v3/standard/text-to-video": _KLING_3_STANDARD,
    "fal-ai/kling-video/v3/standard/image-to-video": _KLING_3_STANDARD,
    "fal-ai/kling-video/v2.6/pro/image-to-video": _KLING_2_6,
    "bytedance/seedance-2.0/text-to-video": _SEEDANCE_2_0,
    "bytedance/seedance-2.0/image-to-video": _SEEDANCE_2_0,
    "wan/v2.6/text-to-video": _WAN_2_6,
    "wan/v2.6/image-to-video": _WAN_2_6,
    "alibaba/wan-3.0/text-to-video": _WAN_3_0,
    "minimax/h3-max/text-to-video": _H3_MAX,
    "minimax/h3-max/image-to-video": _H3_MAX,
    "minimax/h3-max-turbo/text-to-video": _H3_MAX_TURBO,
    "minimax/h3-max-turbo/image-to-video": _H3_MAX_TURBO,
    "google/gemini-omni-flash/v1.1/text-to-video": _GEMINI_OMNI,
    "google/gemini-omni-flash/v1.1/image-to-video": _GEMINI_OMNI,
    "fal-ai/kling-video/o3/pro/text-to-video": _KLING_O3_PRO,
    "fal-ai/kling-video/o3/pro/image-to-video": _KLING_O3_PRO,
    "fal-ai/kling-video/v2.6/pro/text-to-video": _KLING_2_6,
    "fal-ai/pixverse/v6/text-to-video": _PIXVERSE_6,
    "fal-ai/pixverse/v6/image-to-video": _PIXVERSE_6,
    "minimax/h3/text-to-video": _H3,
    "minimax/h3/image-to-video": _H3,
    "xai/grok-imagine-video/text-to-video": _GROK_VIDEO,
    "xai/grok-imagine-video/image-to-video": _GROK_VIDEO,
    "alibaba/wan-3.0/image-to-video": _WAN_3_0,
}

# Longest clip fal may render for duration "auto" (fal input schemas: 2.0 up to 15 s, 2.5 up to 30 s).
AUTO_DURATION_SECONDS = {
    "bytedance/seedance-2.0/text-to-video": 15,
    "bytedance/seedance-2.0/image-to-video": 15,
    "bytedance/seedance-2.5/text-to-video": 30,
    "bytedance/seedance-2.5/image-to-video": 30,
    "bytedance/seedance-2.0/fast/text-to-video": 15,
    "bytedance/seedance-2.0/fast/image-to-video": 15,
    "bytedance/seedance-2.0/mini/text-to-video": 15,
}

# PixVerse v5 bills $0.05 "video segments": a 5 s clip is $0.15 at 360p/540p, $0.20 at 720p
# (fal's default) and $0.40 at 1080p, i.e. 3/4/8 segments; 8 s clips cost twice as much.
PIXVERSE_SEGMENTS = {"360p": 3, "540p": 3, "720p": 4, "1080p": 8}
PIXVERSE_DEFAULT_RESOLUTION = "720p"
