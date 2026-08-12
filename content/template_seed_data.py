"""Owned starter templates for the Admart template gallery."""

TEMPLATE_SEEDS = [
    {
        "id": "premium-product-hero",
        "title": "Premium Product Hero",
        "category": "product",
        "format": "1:1 image",
        "is_video": False,
        "preview_url": "/template-media/product-hero.png",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/nano-banana-2",
            "modelName": "Nano Banana 2",
            "prompt": (
                "Create a premium studio advertisement for [PRODUCT_NAME]. Place the product as the clean hero object "
                "on a refined [SURFACE_MATERIAL] surface, with [BRAND_COLOR] accent lighting, soft shadows, crisp texture, "
                "and empty negative space for a headline. Make it look like a modern ecommerce campaign for [BRAND_NAME]."
            ),
            "negativePrompt": "blurry, low quality, distorted product, extra labels, messy background, unreadable text",
            "settings": {"aspectRatio": "1:1", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "PRODUCT_NAME", "label": "Product name"},
                {"key": "BRAND_NAME", "label": "Brand name"},
                {"key": "BRAND_COLOR", "label": "Brand color"},
                {"key": "SURFACE_MATERIAL", "label": "Surface material"},
            ],
            "tags": ["product", "ecommerce", "hero"],
        },
    },
    {
        "id": "pakistani-shirt-edit",
        "title": "Pakistani Shirt Jersey Edit",
        "category": "product",
        "format": "image edit",
        "is_video": False,
        "preview_url": "/template-media/pakistani-shirt-edit.png",
        "template_config": {
            "kind": "image",
            "capability": "edit",
            "model": "fal-ai/nano-banana-2/edit",
            "modelName": "Nano Banana 2 Edit",
            "requiresSourceImage": True,
            "prompt": (
                "Using [PERSON_IMAGE] as the reference, transform the outfit into a stylish Pakistani cricket-inspired "
                "T-shirt in [SHIRT_COLOR]. Add [TEAM_OR_NAME] tastefully on the shirt, keep the person's face identity, "
                "pose, body proportions, and natural skin texture intact. Use clean streetwear lighting and a polished social post look."
            ),
            "negativePrompt": "changed face, distorted hands, warped logo, misspelled text, plastic skin, blur",
            "settings": {"aspectRatio": "1:1", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "PERSON_IMAGE", "label": "Person image"},
                {"key": "SHIRT_COLOR", "label": "Shirt color"},
                {"key": "TEAM_OR_NAME", "label": "Team or name"},
            ],
            "tags": ["personalization", "fashion", "edit"],
        },
    },
    {
        "id": "burger-deal-poster",
        "title": "Burger Deal Poster",
        "category": "ad",
        "format": "1:1 image",
        "is_video": False,
        "preview_url": "/template-media/burger-deal.png",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/nano-banana-2",
            "modelName": "Nano Banana 2",
            "prompt": (
                "Design a sharp fast-food social media poster for [RESTAURANT_NAME]. Show a juicy burger, crispy fries, "
                "and one chilled cold drink as a complete deal. Leave a clear headline area for [OFFER_TEXT] and a price badge "
                "reading [PRICE]. Use appetizing steam, condensation, bright commercial lighting, and a clean modern layout."
            ),
            "negativePrompt": "unreadable price, melted food, distorted burger, cluttered layout, blurry fries, bad typography",
            "settings": {"aspectRatio": "1:1", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "RESTAURANT_NAME", "label": "Restaurant name"},
                {"key": "OFFER_TEXT", "label": "Offer text"},
                {"key": "PRICE", "label": "Price"},
            ],
            "tags": ["food", "deal", "poster"],
        },
    },
    {
        "id": "training-admissions-open",
        "title": "Training Admissions Poster",
        "category": "announce",
        "format": "4:5 image",
        "is_video": False,
        "preview_url": "/template-media/training-admissions.png",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/ideogram/v3",
            "modelName": "Ideogram V3",
            "prompt": (
                "Create a professional admissions-open poster for [PROGRAM_NAME]. Use a modern training lab atmosphere, "
                "confident students, clean technology details, and organized space for [DEADLINE], [VENUE], and [CONTACT]. "
                "The design should feel credible for a university or institute campaign."
            ),
            "negativePrompt": "fake university logos, unreadable text, crowded poster, distorted people, low resolution",
            "settings": {"aspectRatio": "4:5", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "PROGRAM_NAME", "label": "Program name"},
                {"key": "DEADLINE", "label": "Deadline"},
                {"key": "VENUE", "label": "Venue"},
                {"key": "CONTACT", "label": "Contact"},
            ],
            "tags": ["education", "announcement", "poster"],
        },
    },
    {
        "id": "restaurant-menu-board",
        "title": "Restaurant Menu Board",
        "category": "ad",
        "format": "4:5 image",
        "is_video": False,
        "preview_url": "/template-media/menu-board.png",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/ideogram/v3",
            "modelName": "Ideogram V3",
            "prompt": (
                "Design a polished vertical menu board for [RESTAURANT_NAME]. Feature [ITEM_1], [ITEM_2], and [ITEM_3] "
                "with appetizing food photography, clean price blocks, readable typography areas, and a warm restaurant brand style "
                "using [BRAND_COLOR]."
            ),
            "negativePrompt": "misspelled food names, cluttered menu, unreadable prices, warped plates, dull food",
            "settings": {"aspectRatio": "4:5", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "RESTAURANT_NAME", "label": "Restaurant name"},
                {"key": "ITEM_1", "label": "Item 1"},
                {"key": "ITEM_2", "label": "Item 2"},
                {"key": "ITEM_3", "label": "Item 3"},
                {"key": "BRAND_COLOR", "label": "Brand color"},
            ],
            "tags": ["food", "menu", "local business"],
        },
    },
    {
        "id": "achievement-certificate-post",
        "title": "Certificate Achievement Post",
        "category": "announce",
        "format": "1:1 image",
        "is_video": False,
        "preview_url": "/template-media/certificate-post.png",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/ideogram/v3",
            "modelName": "Ideogram V3",
            "prompt": (
                "Create a clean announcement post celebrating [PERSON_NAME] for completing [COURSE_NAME]. Use an elegant certificate, "
                "soft professional lighting, [BRAND_COLOR] accents, and a clear area for the institute name [INSTITUTE_NAME]. "
                "Make it suitable for LinkedIn, Facebook, and Instagram."
            ),
            "negativePrompt": "wrong names, fake signatures, unreadable certificate text, distorted hands, messy background",
            "settings": {"aspectRatio": "1:1", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "PERSON_NAME", "label": "Person name"},
                {"key": "COURSE_NAME", "label": "Course name"},
                {"key": "INSTITUTE_NAME", "label": "Institute name"},
                {"key": "BRAND_COLOR", "label": "Brand color"},
            ],
            "tags": ["education", "certificate", "announcement"],
        },
    },
    {
        "id": "profile-headshot-refresh",
        "title": "Profile Headshot Refresh",
        "category": "story",
        "format": "image edit",
        "is_video": False,
        "preview_url": "/template-media/profile-headshot-edit.png",
        "template_config": {
            "kind": "image",
            "capability": "edit",
            "model": "fal-ai/nano-banana-2/edit",
            "modelName": "Nano Banana 2 Edit",
            "requiresSourceImage": True,
            "prompt": (
                "Improve [PERSON_IMAGE] into a clean professional headshot for [ROLE_OR_BRAND]. Preserve the person's identity, "
                "face shape, hair, and expression. Use a natural [BACKGROUND_COLOR] studio background, flattering soft light, "
                "sharp eyes, realistic skin texture, and a confident social profile composition."
            ),
            "negativePrompt": "changed face, fake skin, over-retouched, distorted eyes, bad teeth, blur",
            "settings": {"aspectRatio": "1:1", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "PERSON_IMAGE", "label": "Person image"},
                {"key": "ROLE_OR_BRAND", "label": "Role or brand"},
                {"key": "BACKGROUND_COLOR", "label": "Background color"},
            ],
            "tags": ["profile", "edit", "personal brand"],
        },
    },
    {
        "id": "product-hand-demo",
        "title": "Product In Hand Demo",
        "category": "product",
        "format": "image edit",
        "is_video": False,
        "preview_url": "/template-media/product-hand-demo.png",
        "template_config": {
            "kind": "image",
            "capability": "edit",
            "model": "fal-ai/nano-banana-pro/edit",
            "modelName": "Nano Banana Pro Edit",
            "requiresSourceImage": True,
            "prompt": (
                "Place [PRODUCT_IMAGE] naturally in a person's hand as if being demonstrated for a premium ad. Keep the exact product "
                "design, proportions, and label readable. Add realistic fingers, clean lifestyle lighting, and a minimal background "
                "matching [BRAND_STYLE]."
            ),
            "negativePrompt": "extra fingers, warped product, changed label, floating object, blurry hand, fake shadows",
            "settings": {"aspectRatio": "1:1", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "PRODUCT_IMAGE", "label": "Product image"},
                {"key": "BRAND_STYLE", "label": "Brand style"},
            ],
            "tags": ["product", "edit", "demo"],
        },
    },
    {
        "id": "fashion-drop-flat-lay",
        "title": "Fashion Drop Flat Lay",
        "category": "product",
        "format": "4:5 image",
        "is_video": False,
        "preview_url": "",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/flux/dev",
            "modelName": "Flux Dev",
            "prompt": (
                "Create a premium fashion flat lay for [CLOTHING_ITEM] from [BRAND_NAME]. Arrange the item with matching accessories, "
                "fabric texture closeups, clean tags, and [BRAND_COLOR] styling. Leave space for a short product caption."
            ),
            "negativePrompt": "wrinkled messy clothes, fake logos, unreadable tags, bad fabric texture, clutter",
            "settings": {"aspectRatio": "4:5", "numImages": 1},
            "quickFields": [
                {"key": "CLOTHING_ITEM", "label": "Clothing item"},
                {"key": "BRAND_NAME", "label": "Brand name"},
                {"key": "BRAND_COLOR", "label": "Brand color"},
            ],
            "tags": ["fashion", "flat lay", "ecommerce"],
        },
    },
    {
        "id": "real-estate-open-house",
        "title": "Real Estate Open House",
        "category": "ad",
        "format": "4:5 image",
        "is_video": False,
        "preview_url": "",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/ideogram/v3",
            "modelName": "Ideogram V3",
            "prompt": (
                "Design a professional real estate open house post for [PROPERTY_TYPE] in [LOCATION]. Show a bright premium interior, "
                "clean exterior detail, and organized typography areas for [DATE_TIME], [PRICE_OR_RENT], and [AGENT_NAME]."
            ),
            "negativePrompt": "fake address, unreadable details, distorted building, cluttered interior, low quality",
            "settings": {"aspectRatio": "4:5", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "PROPERTY_TYPE", "label": "Property type"},
                {"key": "LOCATION", "label": "Location"},
                {"key": "DATE_TIME", "label": "Date and time"},
                {"key": "PRICE_OR_RENT", "label": "Price or rent"},
                {"key": "AGENT_NAME", "label": "Agent name"},
            ],
            "tags": ["real estate", "open house", "ad"],
        },
    },
    {
        "id": "skincare-product-hero",
        "title": "Skincare Product Hero",
        "category": "product",
        "format": "1:1 image",
        "is_video": False,
        "preview_url": "",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/nano-banana-2",
            "modelName": "Nano Banana 2",
            "prompt": (
                "Create a luxury skincare product hero for [PRODUCT_NAME]. Use fresh water droplets, clean botanical accents, "
                "soft reflective surfaces, realistic packaging, and [BRAND_COLOR] highlights. Leave space for one short benefit line: [BENEFIT]."
            ),
            "negativePrompt": "warped bottle, unreadable label, oily mess, fake ingredients, blur, plastic texture",
            "settings": {"aspectRatio": "1:1", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "PRODUCT_NAME", "label": "Product name"},
                {"key": "BRAND_COLOR", "label": "Brand color"},
                {"key": "BENEFIT", "label": "Benefit"},
            ],
            "tags": ["beauty", "skincare", "product"],
        },
    },
    {
        "id": "tech-gadget-minimal-ad",
        "title": "Tech Gadget Minimal Ad",
        "category": "product",
        "format": "16:9 image",
        "is_video": False,
        "preview_url": "",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/flux/dev",
            "modelName": "Flux Dev",
            "prompt": (
                "Create a minimal technology ad for [GADGET_NAME]. Show the gadget floating slightly above a clean matte surface, "
                "with precise rim lighting, [BRAND_COLOR] UI glow, realistic shadows, and empty space for a product headline."
            ),
            "negativePrompt": "warped device, extra buttons, unreadable screens, noisy background, dull lighting",
            "settings": {"aspectRatio": "16:9", "numImages": 1},
            "quickFields": [
                {"key": "GADGET_NAME", "label": "Gadget name"},
                {"key": "BRAND_COLOR", "label": "Brand color"},
            ],
            "tags": ["technology", "product", "minimal"],
        },
    },
    {
        "id": "eid-sale-poster",
        "title": "Eid Sale Poster",
        "category": "ad",
        "format": "4:5 image",
        "is_video": False,
        "preview_url": "/template-media/offer-poster.png",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/ideogram/v3",
            "modelName": "Ideogram V3",
            "prompt": (
                "Design a festive Eid sale poster for [STORE_NAME]. Use elegant cultural patterns, premium product display, "
                "[BRAND_COLOR] accents, and a bold offer area for [DISCOUNT_TEXT]. Add a clean footer for [VALID_UNTIL]."
            ),
            "negativePrompt": "religious misuse, unreadable offer, clutter, fake logos, low quality text",
            "settings": {"aspectRatio": "4:5", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "STORE_NAME", "label": "Store name"},
                {"key": "DISCOUNT_TEXT", "label": "Discount text"},
                {"key": "VALID_UNTIL", "label": "Valid until"},
                {"key": "BRAND_COLOR", "label": "Brand color"},
            ],
            "tags": ["sale", "retail", "poster"],
        },
    },
    {
        "id": "fitness-challenge-poster",
        "title": "Fitness Challenge Poster",
        "category": "announce",
        "format": "9:16 image",
        "is_video": False,
        "preview_url": "",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/flux/dev",
            "modelName": "Flux Dev",
            "prompt": (
                "Create a vertical fitness challenge announcement for [GYM_NAME]. Show energetic athletes, bold lighting, "
                "clean space for [CHALLENGE_NAME], [START_DATE], and [JOINING_DETAILS]. Make it intense, modern, and motivating."
            ),
            "negativePrompt": "unsafe form, distorted bodies, unreadable text, clutter, dull colors",
            "settings": {"aspectRatio": "9:16", "numImages": 1},
            "quickFields": [
                {"key": "GYM_NAME", "label": "Gym name"},
                {"key": "CHALLENGE_NAME", "label": "Challenge name"},
                {"key": "START_DATE", "label": "Start date"},
                {"key": "JOINING_DETAILS", "label": "Joining details"},
            ],
            "tags": ["fitness", "announcement", "story"],
        },
    },
    {
        "id": "restaurant-story-combo",
        "title": "Restaurant Story Combo",
        "category": "story",
        "format": "9:16 image",
        "is_video": False,
        "preview_url": "",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/nano-banana-2",
            "modelName": "Nano Banana 2",
            "prompt": (
                "Create a vertical Instagram story for [RESTAURANT_NAME] promoting [COMBO_NAME]. Show the food close up, "
                "price sticker [PRICE], warm lighting, and a clear call-to-action area reading [CTA]."
            ),
            "negativePrompt": "messy food, unreadable CTA, warped drink, bad crop, low quality",
            "settings": {"aspectRatio": "9:16", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "RESTAURANT_NAME", "label": "Restaurant name"},
                {"key": "COMBO_NAME", "label": "Combo name"},
                {"key": "PRICE", "label": "Price"},
                {"key": "CTA", "label": "CTA"},
            ],
            "tags": ["food", "story", "deal"],
        },
    },
    {
        "id": "product-launch-reel",
        "title": "Product Launch Reel",
        "category": "reel",
        "format": "9:16 video",
        "is_video": True,
        "preview_url": "/template-media/launch-reel.png",
        "template_config": {
            "kind": "video",
            "videoUrl": "/template-media/launch-reel.mp4",
            "capability": "textToVideo",
            "model": "bytedance/seedance-2.0/text-to-video",
            "modelName": "Seedance 2.0",
            "prompt": (
                "Create an 8-second vertical product launch reel for [PRODUCT_NAME]. Start with a dark premium silhouette, "
                "reveal the product with a smooth light sweep, show two close-up detail shots, then end on a clean hero frame "
                "with space for [TAGLINE]. Use cinematic pacing and luxury commercial lighting."
            ),
            "negativePrompt": "flicker, shaky camera, unreadable text, warped product, abrupt cuts, low detail",
            "settings": {"duration": "8", "aspectRatio": "9:16", "resolution": "1080p", "generateAudio": False},
            "quickFields": [
                {"key": "PRODUCT_NAME", "label": "Product name"},
                {"key": "TAGLINE", "label": "Tagline"},
            ],
            "tags": ["launch", "reel", "product"],
        },
    },
    {
        "id": "food-deal-motion",
        "title": "Food Deal Motion",
        "category": "reel",
        "format": "9:16 video",
        "is_video": True,
        "preview_url": "/template-media/food-deal-motion.png",
        "template_config": {
            "kind": "video",
            "videoUrl": "/template-media/food-deal-motion.mp4",
            "capability": "textToVideo",
            "model": "bytedance/seedance-2.0/text-to-video",
            "modelName": "Seedance 2.0",
            "prompt": (
                "Create an 8-second food offer reel for [DEAL_NAME]. Show the burger landing on a tray, fries sliding beside it, "
                "a cold drink with condensation, then a final clean offer frame for [PRICE]. Use appetizing motion, warm highlights, "
                "and commercial fast-food pacing."
            ),
            "negativePrompt": "messy food, flicker, warped hands, unreadable price, bad liquid physics, blur",
            "settings": {"duration": "8", "aspectRatio": "9:16", "resolution": "1080p", "generateAudio": False},
            "quickFields": [
                {"key": "DEAL_NAME", "label": "Deal name"},
                {"key": "PRICE", "label": "Price"},
            ],
            "tags": ["food", "deal", "video"],
        },
    },
    {
        "id": "course-intro-reel",
        "title": "Course Intro Reel",
        "category": "reel",
        "format": "9:16 video",
        "is_video": True,
        "preview_url": "/template-media/course-intro.png",
        "template_config": {
            "kind": "video",
            "videoUrl": "/template-media/course-intro.mp4",
            "capability": "textToVideo",
            "model": "bytedance/seedance-2.0/text-to-video",
            "modelName": "Seedance 2.0",
            "prompt": (
                "Create a 10-second training program intro reel for [PROGRAM_NAME]. Show students entering a modern lab, "
                "hands-on learning scenes, instructor guidance, and a final enrollment frame with [DEADLINE] and [VENUE]. "
                "Make it energetic, professional, and trustworthy."
            ),
            "negativePrompt": "unreadable text, distorted people, chaotic classroom, flicker, low detail",
            "settings": {"duration": "10", "aspectRatio": "9:16", "resolution": "1080p", "generateAudio": False},
            "quickFields": [
                {"key": "PROGRAM_NAME", "label": "Program name"},
                {"key": "DEADLINE", "label": "Deadline"},
                {"key": "VENUE", "label": "Venue"},
            ],
            "tags": ["education", "course", "reel"],
        },
    },
    {
        "id": "countdown-teaser-video",
        "title": "Countdown Teaser Video",
        "category": "story",
        "format": "9:16 video",
        "is_video": True,
        "preview_url": "/template-media/countdown-video.png",
        "template_config": {
            "kind": "video",
            "videoUrl": "/template-media/countdown-video.mp4",
            "capability": "textToVideo",
            "model": "fal-ai/veo3.1",
            "modelName": "Veo 3.1",
            "prompt": (
                "Create a 6-second vertical countdown teaser for [EVENT_OR_DROP]. Show three quick cinematic beats: mystery detail, "
                "number countdown, and final reveal card with [DATE]. Use dramatic lighting, smooth camera movement, and high-end social pacing."
            ),
            "negativePrompt": "bad numbers, unreadable date, flicker, abrupt camera, low quality",
            "settings": {"duration": "6s", "aspectRatio": "9:16", "resolution": "1080p", "generateAudio": False},
            "quickFields": [
                {"key": "EVENT_OR_DROP", "label": "Event or drop"},
                {"key": "DATE", "label": "Date"},
            ],
            "tags": ["countdown", "story", "teaser"],
        },
    },
    {
        "id": "person-dance-video",
        "title": "Person Dance Video",
        "category": "reel",
        "format": "image to video",
        "is_video": True,
        "preview_url": "/template-media/dance-video-template.png",
        "template_config": {
            "kind": "video",
            "videoUrl": "/template-media/dance-video-template.mp4",
            "capability": "imageToVideo",
            "model": "bytedance/seedance-2.0/image-to-video",
            "modelName": "Seedance 2.0 I2V",
            "requiresSourceImage": True,
            "prompt": (
                "Animate [PERSON_IMAGE] into a confident short dance reel. Keep the face identity and outfit recognizable, "
                "add smooth upper-body movement, natural footwork, upbeat camera energy, and a clean social media background in [STYLE]."
            ),
            "negativePrompt": "changed face, extra limbs, broken anatomy, flicker, shaky camera, warped clothes",
            "settings": {"duration": "6", "aspectRatio": "9:16", "resolution": "1080p", "generateAudio": False},
            "quickFields": [
                {"key": "PERSON_IMAGE", "label": "Person image"},
                {"key": "STYLE", "label": "Style"},
            ],
            "tags": ["dance", "i2v", "personalization"],
        },
    },
    {
        "id": "cinematic-cafe-sequence",
        "title": "Cinematic Cafe Sequence",
        "category": "reel",
        "format": "16:9 video",
        "is_video": True,
        "preview_url": "",
        "template_config": {
            "kind": "video",
            "videoUrl": "/template-media/cinematic-cafe.mp4",
            "capability": "textToVideo",
            "model": "bytedance/seedance-2.0/text-to-video",
            "modelName": "Seedance 2.0",
            "prompt": (
                "Create an 8-second cinematic cafe sequence for [CAFE_NAME]. Start with a close-up of espresso pouring, "
                "cut to steam rising, show a barista finishing latte art, then end with a warm hero shot of [SIGNATURE_DRINK]."
            ),
            "negativePrompt": "watery coffee, warped cup, shaky camera, bad hands, flicker, low detail steam",
            "settings": {"duration": "8", "aspectRatio": "16:9", "resolution": "1080p", "generateAudio": False},
            "quickFields": [
                {"key": "CAFE_NAME", "label": "Cafe name"},
                {"key": "SIGNATURE_DRINK", "label": "Signature drink"},
            ],
            "tags": ["cafe", "food", "cinematic"],
        },
    },
    {
        "id": "clothing-spin-i2v",
        "title": "Clothing Try-On Spin",
        "category": "reel",
        "format": "image to video",
        "is_video": True,
        "preview_url": "",
        "template_config": {
            "kind": "video",
            "videoUrl": "/template-media/clothing-tryon.mp4",
            "capability": "imageToVideo",
            "model": "wan/v2.6/image-to-video",
            "modelName": "Wan 2.6 I2V",
            "requiresSourceImage": True,
            "prompt": (
                "Animate [MODEL_IMAGE] into a smooth fashion try-on spin for [CLOTHING_ITEM]. Keep identity and outfit details stable, "
                "show a subtle 180-degree turn, fabric movement, and clean studio lighting."
            ),
            "negativePrompt": "changed face, warped clothing, extra limbs, flicker, bad hands, unstable background",
            "settings": {"duration": "5", "resolution": "1080p"},
            "quickFields": [
                {"key": "MODEL_IMAGE", "label": "Model image"},
                {"key": "CLOTHING_ITEM", "label": "Clothing item"},
            ],
            "tags": ["fashion", "i2v", "try-on"],
        },
    },
    {
        "id": "before-after-reveal",
        "title": "Before After Reveal",
        "category": "reel",
        "format": "image to video",
        "is_video": True,
        "preview_url": "",
        "template_config": {
            "kind": "video",
            "videoUrl": "/template-media/before-after.mp4",
            "capability": "imageToVideo",
            "model": "fal-ai/kling-video/v2.5-turbo/pro/image-to-video",
            "modelName": "Kling 2.5 Turbo Pro I2V",
            "requiresSourceImage": True,
            "prompt": (
                "Animate [RESULT_IMAGE] into a polished before-after reveal for [SERVICE_NAME]. Use a clean wipe transition, "
                "subtle camera push-in, premium lighting, and a final frame that highlights [RESULT_BENEFIT]."
            ),
            "negativePrompt": "flicker, distorted result, messy transition, unreadable text, warped faces",
            "settings": {"duration": "5"},
            "quickFields": [
                {"key": "RESULT_IMAGE", "label": "Result image"},
                {"key": "SERVICE_NAME", "label": "Service name"},
                {"key": "RESULT_BENEFIT", "label": "Result benefit"},
            ],
            "tags": ["service", "before after", "i2v"],
        },
    },
    {
        "id": "product-unboxing-reel",
        "title": "Product Unboxing Reel",
        "category": "reel",
        "format": "9:16 video",
        "is_video": True,
        "preview_url": "",
        "template_config": {
            "kind": "video",
            "videoUrl": "/template-media/product-unboxing.mp4",
            "capability": "textToVideo",
            "model": "fal-ai/kling-video/v2.5-turbo/pro/text-to-video",
            "modelName": "Kling 2.5 Turbo Pro",
            "prompt": (
                "Create a 5-second unboxing reel for [PRODUCT_NAME]. Show the box opening, tissue paper moving, product reveal, "
                "and a final close-up with clean light reflections. Keep the motion smooth and premium."
            ),
            "negativePrompt": "warped box, unreadable label, extra hands, flicker, messy packaging",
            "settings": {"duration": "5", "aspectRatio": "9:16"},
            "quickFields": [{"key": "PRODUCT_NAME", "label": "Product name"}],
            "tags": ["unboxing", "product", "reel"],
        },
    },
    {
        "id": "event-invitation-story",
        "title": "Event Invitation Story",
        "category": "story",
        "format": "9:16 video",
        "is_video": True,
        "preview_url": "",
        "template_config": {
            "kind": "video",
            "videoUrl": "/template-media/event-invitation.mp4",
            "capability": "textToVideo",
            "model": "fal-ai/minimax/hailuo-02/standard/text-to-video",
            "modelName": "Hailuo 02 Standard",
            "prompt": (
                "Create a 6-second vertical event invitation story for [EVENT_NAME]. Show venue atmosphere, guests arriving, "
                "elegant motion graphics space for [DATE_TIME] and [LOCATION], and a final call to action: [CTA]."
            ),
            "negativePrompt": "unreadable details, distorted guests, flicker, chaotic camera, low quality",
            "settings": {"duration": "6"},
            "quickFields": [
                {"key": "EVENT_NAME", "label": "Event name"},
                {"key": "DATE_TIME", "label": "Date and time"},
                {"key": "LOCATION", "label": "Location"},
                {"key": "CTA", "label": "CTA"},
            ],
            "tags": ["event", "story", "invitation"],
        },
    },
    {
        "id": "brand-explainer-carousel",
        "title": "Brand Explainer Carousel",
        "category": "carousel",
        "format": "carousel image",
        "is_video": False,
        "preview_url": "",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/ideogram/v3",
            "modelName": "Ideogram V3",
            "prompt": (
                "Create a clean carousel cover and visual system for [BRAND_NAME]. The first slide should introduce [CORE_OFFER], "
                "with three visual content blocks for problem, solution, and proof. Use [BRAND_COLOR], readable hierarchy, and modern SaaS-style polish."
            ),
            "negativePrompt": "unreadable text, cluttered layout, fake charts, distorted icons, low quality",
            "settings": {"aspectRatio": "1:1", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "BRAND_NAME", "label": "Brand name"},
                {"key": "CORE_OFFER", "label": "Core offer"},
                {"key": "BRAND_COLOR", "label": "Brand color"},
            ],
            "tags": ["carousel", "brand", "explainer"],
        },
    },
    {
        "id": "product-benefits-carousel",
        "title": "Product Benefits Carousel",
        "category": "carousel",
        "format": "carousel image",
        "is_video": False,
        "preview_url": "",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/nano-banana-2",
            "modelName": "Nano Banana 2",
            "prompt": (
                "Create a carousel cover for [PRODUCT_NAME] showing three clear benefits: [BENEFIT_1], [BENEFIT_2], and [BENEFIT_3]. "
                "Use product closeups, clean typography areas, [BRAND_COLOR] accents, and a polished ecommerce campaign style."
            ),
            "negativePrompt": "unreadable benefits, warped product, clutter, fake label, low resolution",
            "settings": {"aspectRatio": "1:1", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "PRODUCT_NAME", "label": "Product name"},
                {"key": "BENEFIT_1", "label": "Benefit 1"},
                {"key": "BENEFIT_2", "label": "Benefit 2"},
                {"key": "BENEFIT_3", "label": "Benefit 3"},
                {"key": "BRAND_COLOR", "label": "Brand color"},
            ],
            "tags": ["carousel", "product", "benefits"],
        },
    },
    {
        "id": "client-testimonial-carousel",
        "title": "Client Testimonial Carousel",
        "category": "carousel",
        "format": "carousel image",
        "is_video": False,
        "preview_url": "",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/ideogram/v3",
            "modelName": "Ideogram V3",
            "prompt": (
                "Create a professional testimonial carousel cover for [BRAND_NAME]. Include a polished portrait area, quote card space "
                "for [TESTIMONIAL_LINE], star rating details, and a clean brand footer. Use [BRAND_COLOR] accents and social proof styling."
            ),
            "negativePrompt": "fake faces, unreadable quote, cluttered cards, distorted stars, low quality",
            "settings": {"aspectRatio": "1:1", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "BRAND_NAME", "label": "Brand name"},
                {"key": "TESTIMONIAL_LINE", "label": "Testimonial line"},
                {"key": "BRAND_COLOR", "label": "Brand color"},
            ],
            "tags": ["carousel", "testimonial", "social proof"],
        },
    },
    {
        "id": "menu-carousel",
        "title": "Menu Carousel",
        "category": "carousel",
        "format": "carousel image",
        "is_video": False,
        "preview_url": "",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/nano-banana-2",
            "modelName": "Nano Banana 2",
            "prompt": (
                "Create a restaurant carousel cover for [RESTAURANT_NAME] featuring [CATEGORY_NAME]. Show multiple dishes, clean section titles, "
                "price label space, warm food photography, and a polished brand look."
            ),
            "negativePrompt": "messy dishes, unreadable prices, fake food, warped plates, cluttered layout",
            "settings": {"aspectRatio": "1:1", "resolution": "1K", "numImages": 1},
            "quickFields": [
                {"key": "RESTAURANT_NAME", "label": "Restaurant name"},
                {"key": "CATEGORY_NAME", "label": "Category name"},
            ],
            "tags": ["carousel", "food", "menu"],
        },
    },
    {
        "id": "real-estate-carousel",
        "title": "Real Estate Listing Carousel",
        "category": "carousel",
        "format": "carousel image",
        "is_video": False,
        "preview_url": "",
        "template_config": {
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/flux/dev",
            "modelName": "Flux Dev",
            "prompt": (
                "Create a real estate listing carousel cover for [PROPERTY_NAME]. Show exterior, interior, and key feature tiles for "
                "[FEATURE_1], [FEATURE_2], and [FEATURE_3]. Use clean premium layout, neutral lighting, and clear agent branding."
            ),
            "negativePrompt": "fake address, distorted rooms, unreadable feature text, cluttered collage, low quality",
            "settings": {"aspectRatio": "1:1", "numImages": 1},
            "quickFields": [
                {"key": "PROPERTY_NAME", "label": "Property name"},
                {"key": "FEATURE_1", "label": "Feature 1"},
                {"key": "FEATURE_2", "label": "Feature 2"},
                {"key": "FEATURE_3", "label": "Feature 3"},
            ],
            "tags": ["carousel", "real estate", "listing"],
        },
    },
]


def _source_field(key: str, label: str, default: str) -> dict:
    return {
        "key": key,
        "label": label,
        "default": default,
        "placeholder": default,
        "type": "text",
    }


def _source_template(
    *,
    id: str,
    title: str,
    category: str,
    aspect_ratio: str,
    preview_url: str,
    source_url: str,
    source_model: str,
    source_category: str,
    uses_count: int,
    uses_last_7d: int,
    description: str,
    prompt: str,
    negative_prompt: str,
    variables: list[dict],
    tags: list[str],
    guidance_scale: float = 7.0,
    inference_steps: int = 30,
    seed: int | None = None,
) -> dict:
    prompt_template = prompt
    for variable in variables:
        key = variable["key"]
        prompt_template = prompt_template.replace(f"[{key}]", "{{" + key.lower() + "}}")

    settings = {
        "aspectRatio": aspect_ratio,
        "resolution": "1K",
        "numImages": 1,
        "guidanceScale": guidance_scale,
        "numInferenceSteps": inference_steps,
    }
    if seed is not None:
        settings["seed"] = seed

    return {
        "id": id,
        "title": title,
        "category": category,
        "format": f"{aspect_ratio} image",
        "is_video": False,
        "preview_url": preview_url,
        "uses_count": uses_count,
        "uses_last_7d": uses_last_7d,
        "template_config": {
            "source": "civitai",
            "kind": "image",
            "capability": "textToImage",
            "model": "fal-ai/nano-banana-2",
            "modelName": "Nano Banana 2",
            "description": description,
            "sourceUrl": source_url,
            "sourceModel": source_model,
            "sourceModelName": source_model,
            "sourceCategory": source_category,
            "sourceUsesCount": uses_count,
            "sourceUsesLast7d": uses_last_7d,
            "systemPrompt": (
                "Write commercial image-generation prompts with clear subject, camera, lighting, "
                "composition, texture, and brand-safe production details."
            ),
            "prompt": prompt,
            "prompt_template": prompt_template,
            "negativePrompt": negative_prompt,
            "negative_prompt": negative_prompt,
            "variables": [
                {
                    "key": variable["key"].lower(),
                    "default": variable.get("default", ""),
                    "label": variable.get("label", variable["key"].title()),
                    "type": variable.get("type", "text"),
                }
                for variable in variables
            ],
            "quickFields": variables,
            "style_preset": id,
            "parameters": {
                "guidance_scale": guidance_scale,
                "inference_steps": inference_steps,
                "sampler": "Euler a",
                "seed_mode": "fixed" if seed is not None else "random",
            },
            "settings": settings,
            "tags": tags,
        },
    }


SOURCE_BACKED_TEMPLATE_SEEDS = [
    _source_template(
        id="source-minimal-product-vehicle",
        title="Minimal Product Vehicle Render",
        category="product",
        aspect_ratio="16:9",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/d2c49e2f-6ef1-4ab0-8d51-37b0848e06a3/original=true/973643.jpeg",
        source_url="https://civitai.com/images/973643",
        source_model="Product Design minimalism eddiemauro / eddiemauro 2.0",
        source_category="E-Commerce & Ads",
        uses_count=28955,
        uses_last_7d=2848,
        description="Minimal 3D product-design render for futuristic vehicles, gadgets, and industrial concepts.",
        prompt=(
            "Create a polished 3D product render of a futuristic [PRODUCT_TYPE] in [COLOR], built with "
            "[MATERIAL] surfaces and refined aerodynamic lines. Use a minimal studio background, clean horizon line, "
            "softbox reflections, octane-style lighting, crisp edges, shallow shadows, and a premium catalog finish."
        ),
        negative_prompt="text, watermark, logo artifacts, cluttered background, blurry edges, distorted proportions, low quality, cartoon look",
        variables=[
            _source_field("PRODUCT_TYPE", "Product type", "electric concept vehicle"),
            _source_field("COLOR", "Main color", "pine green"),
            _source_field("MATERIAL", "Material", "matte ceramic and brushed metal"),
        ],
        tags=["product", "industrial design", "minimal"],
        guidance_scale=8,
        inference_steps=30,
        seed=3750982133,
    ),
    _source_template(
        id="source-elegant-device-render",
        title="Elegant Minimal Device Render",
        category="product",
        aspect_ratio="4:3",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/41a78495-bed6-4c75-b8c0-76398fa485cc/original=true/690280.jpeg",
        source_url="https://civitai.com/images/690280",
        source_model="Elegant minimalism eddiemauro LORA",
        source_category="E-Commerce & Ads",
        uses_count=13633,
        uses_last_7d=1259,
        description="Clean industrial-design presentation for a premium product concept or tech launch.",
        prompt=(
            "Generate an elegant minimal product concept for [PRODUCT_NAME], shaped like a futuristic [PRODUCT_TYPE]. "
            "Use [COLOR] accents, smooth matte surfaces, precise bevels, subtle studio reflections, centered composition, "
            "and a clean presentation-board feeling suitable for a premium launch."
        ),
        negative_prompt="multiple products, noisy scene, bad perspective, text, watermark, scratched surface, plastic toy look, low detail",
        variables=[
            _source_field("PRODUCT_NAME", "Product name", "Aero One"),
            _source_field("PRODUCT_TYPE", "Product type", "smart mobility device"),
            _source_field("COLOR", "Accent color", "graphite blue"),
        ],
        tags=["product", "launch", "tech"],
        guidance_scale=7,
        inference_steps=30,
        seed=3653215289,
    ),
    _source_template(
        id="source-appliance-concept-render",
        title="Appliance Concept Render",
        category="product",
        aspect_ratio="3:4",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/46b843cd-c793-428a-9b09-dbec139c9ad7/original=true/1065874.jpeg",
        source_url="https://civitai.com/images/1065874",
        source_model="Product Design minimalism eddiemauro LORA",
        source_category="E-Commerce & Ads",
        uses_count=7747,
        uses_last_7d=828,
        description="Vertical product concept template for appliances, accessories, and compact electronics.",
        prompt=(
            "Design a futuristic [PRODUCT_TYPE] product render for [BRAND_NAME]. Show a single hero object with "
            "[COLOR] accents, finely detailed vents, buttons, seams, and premium material transitions. Use soft gray studio lighting, "
            "clean shadows, and a vertical ecommerce composition with empty space for copy."
        ),
        negative_prompt="extra products, messy labels, unreadable text, warped buttons, bad reflections, blurry product, low resolution",
        variables=[
            _source_field("PRODUCT_TYPE", "Product type", "hair dryer"),
            _source_field("BRAND_NAME", "Brand name", "LumaCare"),
            _source_field("COLOR", "Accent color", "warm copper"),
        ],
        tags=["appliance", "ecommerce", "concept"],
        guidance_scale=9,
        inference_steps=30,
        seed=2213332203,
    ),
    _source_template(
        id="source-high-rise-real-estate",
        title="High-Rise Real Estate Launch",
        category="ad",
        aspect_ratio="16:9",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/558337ec-fb8b-4a1e-b9a3-1747972cbe27/original=true/9287585.jpeg",
        source_url="https://civitai.com/images/9287585",
        source_model="ArchitectureRealMix v1.1",
        source_category="Architecture",
        uses_count=64004,
        uses_last_7d=3482,
        description="Real-estate launch visual for towers, offices, mixed-use buildings, and property ads.",
        prompt=(
            "Create a photorealistic architectural campaign image for [PROPERTY_NAME], a [BUILDING_TYPE] in [LOCATION]. "
            "Show a refined exterior facade, landscaped street, natural sky, realistic vehicles, premium glass reflections, "
            "and a clean commercial real-estate composition."
        ),
        negative_prompt="warped windows, fake address text, cluttered traffic, distorted building, oversaturated sky, watermark, low quality",
        variables=[
            _source_field("PROPERTY_NAME", "Property name", "Green View Towers"),
            _source_field("BUILDING_TYPE", "Building type", "high-rise office building"),
            _source_field("LOCATION", "Location", "Quetta"),
        ],
        tags=["real estate", "architecture", "ad"],
        guidance_scale=7,
        inference_steps=20,
        seed=1360508132,
    ),
    _source_template(
        id="source-modern-architecture-exterior",
        title="Modern Architecture Exterior",
        category="ad",
        aspect_ratio="3:4",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/ceb881d2-fc45-4876-b84a-b718470dbe00/original=true/98306.jpeg",
        source_url="https://civitai.com/images/98306",
        source_model="dvArch exterior",
        source_category="Architecture",
        uses_count=41509,
        uses_last_7d=3707,
        description="Premium exterior architecture visual with dramatic light and a polished listing look.",
        prompt=(
            "Render a modern [PROPERTY_TYPE] exterior for [PROJECT_NAME] with [ARCHITECTURAL_STYLE] design language. "
            "Use an 85mm architectural photography look, sunset highlights, realistic shadows, high dynamic range, "
            "clean facade geometry, and a premium property-brochure composition."
        ),
        negative_prompt="logo, fake text, oversharpened edges, bad perspective, blurry facade, messy wires, low resolution",
        variables=[
            _source_field("PROPERTY_TYPE", "Property type", "villa"),
            _source_field("PROJECT_NAME", "Project name", "Hill Crest Residence"),
            _source_field("ARCHITECTURAL_STYLE", "Architecture style", "warm modern minimal"),
        ],
        tags=["architecture", "property", "exterior"],
        guidance_scale=7.5,
        inference_steps=25,
        seed=1065154782,
    ),
    _source_template(
        id="source-white-interior-design",
        title="Bright Interior Design Scene",
        category="product",
        aspect_ratio="4:3",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/fbf8b33b-e1df-4dd4-9c3d-96ce2b815000/original=true/545559.jpeg",
        source_url="https://civitai.com/images/545559",
        source_model="XSarchitectural InteriorDesign",
        source_category="Architecture",
        uses_count=35745,
        uses_last_7d=2597,
        description="Interior design template for furniture stores, renovation posts, and decor service ads.",
        prompt=(
            "Create a photorealistic [ROOM_TYPE] interior for [BRAND_NAME]. Use [COLOR_PALETTE] styling, premium furniture, "
            "clean natural daylight, realistic material textures, balanced decor, and a wide editorial composition suitable for "
            "an interior design portfolio."
        ),
        negative_prompt="messy room, warped furniture, low quality, fake text, bad shadows, distorted windows, cluttered decor",
        variables=[
            _source_field("ROOM_TYPE", "Room type", "living room"),
            _source_field("BRAND_NAME", "Brand name", "Casa Studio"),
            _source_field("COLOR_PALETTE", "Color palette", "white and warm oak"),
        ],
        tags=["interior", "decor", "portfolio"],
        guidance_scale=7,
        inference_steps=20,
        seed=2114630674,
    ),
    _source_template(
        id="source-royal-gown-editorial",
        title="Royal Gown Fashion Editorial",
        category="product",
        aspect_ratio="3:4",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/294fc68d-e939-4cc5-99d7-de0cf046040c/original=true/6300719.jpeg",
        source_url="https://civitai.com/images/6300719",
        source_model="Royal Gowns EDG collection",
        source_category="Fashion",
        uses_count=57231,
        uses_last_7d=2197,
        description="Luxury fashion editorial for gown drops, boutique campaigns, and styled model shoots.",
        prompt=(
            "Create a luxury fashion editorial for [BRAND_NAME] featuring a model wearing a [CLOTHING_ITEM] made from "
            "[FABRIC_DETAIL]. Use graceful standing pose, polished runway lighting, soft smile, premium styling, detailed fabric texture, "
            "and a vertical campaign composition."
        ),
        negative_prompt="bad anatomy, deformed hands, cheap fabric, blurry face, watermark, text, overexposed highlights, low quality",
        variables=[
            _source_field("BRAND_NAME", "Brand name", "Noor Atelier"),
            _source_field("CLOTHING_ITEM", "Clothing item", "sea-inspired ball gown"),
            _source_field("FABRIC_DETAIL", "Fabric detail", "shell embroidery and flowing silk"),
        ],
        tags=["fashion", "editorial", "boutique"],
        guidance_scale=5.5,
        inference_steps=20,
        seed=3068554313,
    ),
    _source_template(
        id="source-pink-streetwear-lookbook",
        title="Pink Streetwear Lookbook",
        category="story",
        aspect_ratio="3:4",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/19c35b36-34f7-4c44-6d82-66a366e0d200/original=true/324212.jpeg",
        source_url="https://civitai.com/images/324212",
        source_model="Landmine fashion LORA",
        source_category="Fashion",
        uses_count=42411,
        uses_last_7d=3928,
        description="Streetwear lookbook image for shirts, fashion drops, reels covers, and personal styling.",
        prompt=(
            "Generate a stylish lookbook portrait for [BRAND_NAME]. Show a confident model wearing [OUTFIT_DESCRIPTION] "
            "with [COLOR_THEME] styling, cinematic soft bloom, clean full-body framing, polished social-media fashion lighting, "
            "and realistic fabric texture."
        ),
        negative_prompt="changed face, distorted limbs, unreadable clothing text, watermark, bad fabric, blurry outfit, low quality",
        variables=[
            _source_field("BRAND_NAME", "Brand name", "Urban Thread"),
            _source_field("OUTFIT_DESCRIPTION", "Outfit description", "a pink blouse with black streetwear details"),
            _source_field("COLOR_THEME", "Color theme", "pink and charcoal"),
        ],
        tags=["fashion", "streetwear", "story"],
        guidance_scale=8,
        inference_steps=24,
        seed=3949398464,
    ),
    _source_template(
        id="source-office-fashion-campaign",
        title="Office Fashion Campaign",
        category="product",
        aspect_ratio="3:4",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/e76a5d85-8340-40cb-a21a-a0f633adac6f/original=true/6057624.jpeg",
        source_url="https://civitai.com/images/6057624",
        source_model="Haute Couture Pencil Dresses",
        source_category="Fashion",
        uses_count=30085,
        uses_last_7d=2922,
        description="Professional fashion campaign for formalwear, uniforms, boutique posts, and LinkedIn-safe ads.",
        prompt=(
            "Create a photorealistic office fashion campaign for [BRAND_NAME]. Feature a model wearing [CLOTHING_ITEM] in "
            "[COLOR], with a refined office background, confident posture, clean commercial lighting, realistic textile detail, "
            "and a premium vertical ad layout."
        ),
        negative_prompt="bad anatomy, distorted hands, cheap material, watermark, fake text, blurry face, overprocessed skin",
        variables=[
            _source_field("BRAND_NAME", "Brand name", "Executive Fit"),
            _source_field("CLOTHING_ITEM", "Clothing item", "a tailored pencil dress"),
            _source_field("COLOR", "Color", "deep navy"),
        ],
        tags=["fashion", "formalwear", "ad"],
        guidance_scale=5.5,
        inference_steps=20,
        seed=566228506,
    ),
    _source_template(
        id="source-abstract-brand-key-visual",
        title="Abstract Brand Key Visual",
        category="ad",
        aspect_ratio="3:4",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/34e0e2c4-65b6-4228-ac70-3c09c70b6dfc/original=true/8063881.jpeg",
        source_url="https://civitai.com/images/8063881",
        source_model="YamerMIX SDXL",
        source_category="Editorial & Blog",
        uses_count=152256,
        uses_last_7d=8850,
        description="Colorful abstract hero image for campaigns, blog covers, creator posts, and brand concepts.",
        prompt=(
            "Create an abstract brand key visual for [BRAND_NAME] around the theme [THEME]. Use [COLOR_PALETTE], "
            "layered smoke-like forms, contemporary impressionist texture, luminous highlights, high-detail shapes, "
            "and a polished editorial composition with no readable text."
        ),
        negative_prompt="bad anatomy, low resolution, watermark, text, noisy artifacts, muddy colors, weak composition, blurry details",
        variables=[
            _source_field("BRAND_NAME", "Brand name", "Admart Studio"),
            _source_field("THEME", "Theme", "creative momentum"),
            _source_field("COLOR_PALETTE", "Color palette", "emerald, violet, and soft white"),
        ],
        tags=["abstract", "brand", "editorial"],
        guidance_scale=9,
        inference_steps=50,
        seed=3880643347,
    ),
    _source_template(
        id="source-neon-tech-portrait",
        title="Neon Tech Portrait Campaign",
        category="ad",
        aspect_ratio="3:4",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/03e43115-dbfe-4105-8e24-c7ee6c23504d/original=true/16907802.jpeg",
        source_url="https://civitai.com/images/16907802",
        source_model="Colossus Project XL",
        source_category="SaaS & Tech",
        uses_count=85619,
        uses_last_7d=3849,
        description="Tech-forward portrait visual for AI tools, cybersecurity, SaaS launches, and agency campaigns.",
        prompt=(
            "Create a cinematic tech campaign portrait for [CAMPAIGN_NAME]. Show [PERSON_DESCRIPTION] surrounded by subtle "
            "[TECH_THEME] cues, neon rim light, shallow depth of field, premium camera realism, confident expression, "
            "and a clean dark background suitable for a SaaS launch visual."
        ),
        negative_prompt="drawing, illustration, deformed face, unreadable text, cheap neon, blurry eyes, watermark, low quality",
        variables=[
            _source_field("CAMPAIGN_NAME", "Campaign name", "AI Growth Agent"),
            _source_field("PERSON_DESCRIPTION", "Person description", "a young founder"),
            _source_field("TECH_THEME", "Tech theme", "automation dashboard"),
        ],
        tags=["tech", "portrait", "campaign"],
        guidance_scale=3,
        inference_steps=15,
        seed=4021919502,
    ),
    _source_template(
        id="source-cinematic-profile-portrait",
        title="Cinematic Profile Portrait",
        category="story",
        aspect_ratio="3:4",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/4e35ff58-5e91-4f1e-91e6-f76fb89def1f/original=true/16068005.jpeg",
        source_url="https://civitai.com/images/16068005",
        source_model="NightVisionXL",
        source_category="Social Stories",
        uses_count=81363,
        uses_last_7d=6471,
        description="Profile and personal-brand portrait setup with editable angle, outfit, and photography style.",
        prompt=(
            "Create a cinematic profile portrait of [PERSON_DESCRIPTION] wearing [OUTFIT]. Use [CAMERA_ANGLE], "
            "[PHOTOGRAPHY_STYLE], soft natural highlights, realistic skin texture, clean background separation, "
            "and a polished personal-brand composition."
        ),
        negative_prompt="ugly, deformed, noisy, blurry, low contrast, cartoon, anime, drawing, low budget, cheap, bad quality",
        variables=[
            _source_field("PERSON_DESCRIPTION", "Person description", "a confident entrepreneur"),
            _source_field("OUTFIT", "Outfit", "a modern black blazer"),
            _source_field("CAMERA_ANGLE", "Camera angle", "eye-level close portrait"),
            _source_field("PHOTOGRAPHY_STYLE", "Photography style", "editorial portrait photography"),
        ],
        tags=["portrait", "profile", "personal brand"],
        guidance_scale=6,
        inference_steps=28,
    ),
    _source_template(
        id="source-impressionist-blog-cover",
        title="Impressionist Blog Cover",
        category="announce",
        aspect_ratio="3:4",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/f2c9284e-c66a-4f42-ae83-5716f0829236/original=true/f2c9284e-c66a-4f42-ae83-5716f0829236.jpeg",
        source_url="https://civitai.com/images/97014615",
        source_model="NoobAI impressionist style",
        source_category="Editorial & Blog",
        uses_count=8596,
        uses_last_7d=884,
        description="Painterly editorial cover for blogs, calm brand stories, wellness posts, and announcements.",
        prompt=(
            "Create an impressionist editorial cover for [BLOG_TOPIC]. Show [SCENE_DESCRIPTION] with soft brushstrokes, "
            "gentle water or sky reflections when appropriate, warm pastel atmosphere, subtle paper texture, and a calm "
            "minimal composition with no readable text."
        ),
        negative_prompt="harsh outlines, unreadable text, watermark, muddy colors, distorted perspective, low quality, noisy artifacts",
        variables=[
            _source_field("BLOG_TOPIC", "Blog topic", "slow growth marketing"),
            _source_field("SCENE_DESCRIPTION", "Scene description", "two people in a small boat on a peaceful lake"),
        ],
        tags=["blog", "editorial", "calm"],
        guidance_scale=4,
        inference_steps=30,
        seed=749935418,
    ),
    _source_template(
        id="source-regal-event-poster",
        title="Regal Event Poster",
        category="announce",
        aspect_ratio="3:4",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/855b3847-628b-42b8-a3ce-3ed3838a726b/original=true/855b3847-628b-42b8-a3ce-3ed3838a726b.jpeg",
        source_url="https://civitai.com/images/139330330",
        source_model="Krea 2 Turbo",
        source_category="Event Posters",
        uses_count=1280,
        uses_last_7d=220,
        description="Dramatic vertical poster look for launches, cultural events, awards, and premium announcements.",
        prompt=(
            "Create a regal event poster image for [EVENT_NAME]. Show [MAIN_SUBJECT] in opulent ceremonial styling, "
            "dramatic warm light, detailed embroidered fabric, grand architectural background, strong vertical composition, "
            "and clear empty areas where event text can be added later."
        ),
        negative_prompt="watermark, unreadable text, distorted face, low detail fabric, bad hands, cluttered background, low quality",
        variables=[
            _source_field("EVENT_NAME", "Event name", "Founder Awards Night"),
            _source_field("MAIN_SUBJECT", "Main subject", "a confident host"),
        ],
        tags=["event", "poster", "premium"],
        guidance_scale=4,
        inference_steps=16,
        seed=1192046119,
    ),
    _source_template(
        id="source-ink-story-poster",
        title="Ink Story Poster",
        category="announce",
        aspect_ratio="9:16",
        preview_url="https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/402ed7f8-ba25-421d-a68a-b11ae31af91f/original=true/402ed7f8-ba25-421d-a68a-b11ae31af91f.jpeg",
        source_url="https://civitai.com/images/10703900",
        source_model="mrXOTOXNASSEWNDE ink illustration",
        source_category="Event Posters",
        uses_count=17870,
        uses_last_7d=1663,
        description="Atmospheric ink-poster style for book launches, theatre promos, music nights, and story campaigns.",
        prompt=(
            "Create an atmospheric ink illustration poster for [CAMPAIGN_NAME]. Show [SCENE_DESCRIPTION] with aged paper texture, "
            "brown and red ink tones, moonlit contrast, fine line detail, dramatic depth, and a vertical composition ready for a story post."
        ),
        negative_prompt="open mouth, low quality, cartoonish flatness, watermark, text, blurry ink lines, poor composition",
        variables=[
            _source_field("CAMPAIGN_NAME", "Campaign name", "Midnight Stories"),
            _source_field("SCENE_DESCRIPTION", "Scene description", "a lone figure on a small boat in misty wetlands"),
        ],
        tags=["poster", "ink", "story"],
        guidance_scale=4,
        inference_steps=38,
        seed=282176597,
    ),
]

TEMPLATE_SEEDS.extend(SOURCE_BACKED_TEMPLATE_SEEDS)
