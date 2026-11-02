from __future__ import annotations

import re
import uuid
from copy import deepcopy

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from content.models import Template
from content.template_seed_data import TEMPLATE_SEEDS

PLACEHOLDER_PATTERN = re.compile(r"\[([A-Z0-9_]+)\]")

SAMPLE_VALUES = {
    "AGENT_NAME": "Sara Khan",
    "BACKGROUND_COLOR": "soft charcoal",
    "BENEFIT": "Hydrates for 24 hours",
    "BENEFIT_1": "Fast setup",
    "BENEFIT_2": "Premium quality",
    "BENEFIT_3": "Trusted results",
    "BRAND_COLOR": "emerald green",
    "BRAND_NAME": "Admart Studio",
    "BRAND_STYLE": "minimal premium",
    "CAFE_NAME": "Bean House",
    "CATEGORY_NAME": "Signature Burgers",
    "CHALLENGE_NAME": "30 Day Strength Challenge",
    "CLOTHING_ITEM": "embroidered cotton shirt",
    "COMBO_NAME": "Zinger Combo",
    "CONTACT": "0300 0000000",
    "CORE_OFFER": "AI social content creation",
    "COURSE_NAME": "AI Marketing",
    "CTA": "Order Now",
    "DATE": "30 August",
    "DATE_TIME": "Sunday, 7 PM",
    "DEADLINE": "30 August",
    "DEAL_NAME": "Burger Fries Drink Deal",
    "DISCOUNT_TEXT": "Up to 40% off",
    "EVENT_NAME": "Creator Meetup",
    "EVENT_OR_DROP": "New Collection",
    "FEATURE_1": "3 Bedrooms",
    "FEATURE_2": "Corner Location",
    "FEATURE_3": "Modern Kitchen",
    "GADGET_NAME": "AeroPods Pro",
    "GYM_NAME": "Iron Club",
    "INSTITUTE_NAME": "Admart Academy",
    "ITEM_1": "Beef Burger",
    "ITEM_2": "Loaded Fries",
    "ITEM_3": "Cold Coffee",
    "JOINING_DETAILS": "Register today",
    "LOCATION": "Quetta",
    "OFFER_TEXT": "Burger, fries, and drink",
    "PERSON_NAME": "Ehtisham Khan",
    "PRICE": "Rs 999",
    "PRICE_OR_RENT": "PKR 85,000/month",
    "PROGRAM_NAME": "AI Training Program",
    "PROPERTY_NAME": "Green View Homes",
    "PROPERTY_TYPE": "Apartment",
    "RESTAURANT_NAME": "Burger Lab",
    "RESULT_BENEFIT": "Cleaner, brighter finish",
    "SERVICE_NAME": "Studio Makeover",
    "SHIRT_COLOR": "Pakistan green",
    "SIGNATURE_DRINK": "caramel latte",
    "START_DATE": "1 September",
    "STORE_NAME": "Urban Wear",
    "SURFACE_MATERIAL": "brushed metal",
    "TAGLINE": "Launches Today",
    "TEAM_OR_NAME": "Pakistan",
    "TESTIMONIAL_LINE": "The campaign doubled our inquiries",
    "VALID_UNTIL": "Valid till Eid night",
    "VENUE": "BUITEMS CARL Lab",
}


class Command(BaseCommand):
    help = "Seed or update the owned Admart template gallery."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument(
            "--generate-previews",
            action="store_true",
            help="Generate missing preview URLs with Runware.",
        )
        parser.add_argument(
            "--refresh-previews",
            action="store_true",
            help="Regenerate previews even when a seed already has preview_url.",
        )
        parser.add_argument(
            "--deactivate-missing",
            action="store_true",
            help="Deactivate active templates that are not present in the seed bank.",
        )

    def handle(self, *args, **options):
        seeds = TEMPLATE_SEEDS[: options["limit"]] if options.get("limit") else TEMPLATE_SEEDS
        generate_previews = bool(options["generate_previews"])
        refresh_previews = bool(options["refresh_previews"])

        if generate_previews:
            self._validate_runware_config()

        seen_titles: list[str] = []
        created = 0
        updated = 0

        for seed in seeds:
            payload = deepcopy(seed)
            config = payload["template_config"]
            config["seedKey"] = payload["id"]
            config.setdefault("source", "owned")

            preview_url = payload.get("preview_url", "")
            if generate_previews and (refresh_previews or not preview_url):
                preview_url = self._generate_preview(payload)

            defaults = {
                "category": payload["category"],
                "format": payload["format"],
                "is_video": payload["is_video"],
                "preview_url": preview_url,
                "template_config": config,
                "is_active": True,
            }
            if "uses_count" in payload:
                defaults["uses_count"] = int(payload.get("uses_count") or 0)
            if "uses_last_7d" in payload:
                defaults["uses_last_7d"] = int(payload.get("uses_last_7d") or 0)
            _, was_created = Template.objects.update_or_create(
                title=payload["title"],
                defaults=defaults,
            )
            seen_titles.append(payload["title"])
            created += int(was_created)
            updated += int(not was_created)

        if options["deactivate_missing"]:
            Template.objects.exclude(title__in=seen_titles).update(is_active=False)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded templates: {created} created, {updated} updated, {len(seen_titles)} active seed rows."
            )
        )

    def _validate_runware_config(self):
        if not getattr(settings, "RUNWARE_API_KEY", ""):
            raise CommandError("RUNWARE_API_KEY is required for --generate-previews.")
        if not getattr(settings, "RUNWARE_PREVIEW_MODEL", ""):
            raise CommandError("RUNWARE_PREVIEW_MODEL is required for --generate-previews.")

    def _generate_preview(self, seed: dict) -> str:
        task_uuid = str(uuid.uuid4())
        width, height = _dimensions_for_seed(seed)
        task = {
            "taskType": "imageInference",
            "taskUUID": task_uuid,
            "model": settings.RUNWARE_PREVIEW_MODEL,
            "positivePrompt": _preview_prompt(seed),
            "negativePrompt": seed["template_config"].get("negativePrompt", ""),
            "width": width,
            "height": height,
            "numberResults": 1,
            "includeCost": True,
        }

        response = requests.post(
            getattr(settings, "RUNWARE_API_URL", "https://api.runware.ai/v1"),
            headers={
                "Authorization": f"Bearer {settings.RUNWARE_API_KEY}",
                "Content-Type": "application/json",
            },
            json=[task],
            timeout=getattr(settings, "RUNWARE_TIMEOUT", 60),
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            first = payload["errors"][0]
            raise CommandError(first.get("message") or "Runware preview generation failed.")
        for item in payload.get("data", []):
            if item.get("taskUUID") == task_uuid and item.get("imageURL"):
                self.stdout.write(f"Generated preview for {seed['title']} cost={item.get('cost', 'unknown')}")
                return item["imageURL"]
        raise CommandError(f"Runware did not return an imageURL for {seed['title']}.")


def _preview_prompt(seed: dict) -> str:
    config = seed["template_config"]
    prompt = config.get("previewPrompt") or config.get("prompt") or seed["title"]

    def replace(match):
        key = match.group(1)
        return SAMPLE_VALUES.get(key, key.replace("_", " ").lower())

    return PLACEHOLDER_PATTERN.sub(replace, prompt)


def _dimensions_for_seed(seed: dict) -> tuple[int, int]:
    settings_data = seed["template_config"].get("settings") or {}
    aspect = str(settings_data.get("aspectRatio") or seed.get("format") or "").lower()
    if "9:16" in aspect:
        return 768, 1344
    if "16:9" in aspect:
        return 1344, 768
    if "4:5" in aspect:
        return 1024, 1280
    return 1024, 1024
