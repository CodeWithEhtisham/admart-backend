# Future work

Later YouTube work. Not in the current publish flow.

## YouTube Suggest (video-aware)

Today Suggest only uses the working title, generation prompt, and brand kit. It does not open the MP4.

Later: send the clip (or sampled frames + audio) to Gemini so title, description, tags, category, and language come from what is on screen. Needs a fetchable media URL (`MEDIA_BASE_URL` or Gemini Files API). Keep prompt-enhance text-only.

Still do not suggest Studio-only fields (comments, remixing, premiere, end screens, cards).

## YouTube Shorts

Later: detect short/vertical videos, apply Shorts-safe metadata, and publish as a Short where the YouTube Data API allows.

End screens, cards, remixing, and other Studio-only Shorts controls stay out of that pass.
