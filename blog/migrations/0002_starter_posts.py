"""Three starter posts as drafts: edit and publish them from the admin dashboard (Blog)."""

from django.db import migrations

POSTS = [
    {
        "slug": "how-to-make-youtube-shorts-with-ai",
        "title": "How to make YouTube Shorts with AI, step by step",
        "summary": "From a one-line topic to a finished vertical Short: research, a hook, a script, "
        "voice, pictures, captions and your approval before anything is posted.",
        "body": """Short videos reward consistency, but writing, recording and editing every day is hard. AI can do most of the work while you stay in charge of what goes out. This is how the YouTube Shorts Creator in Admart works.

## 1. Start with a topic

Type one line, such as "3 surprising facts about coffee". If you set your channel niche, you can even leave it blank and the agent picks a fresh topic for you.

## 2. Research and three ideas

The agent looks the topic up on the web, then proposes three different ideas. Each one comes with a hook (the first line people hear) and a score that shows how strong that hook is. You pick the one you like, and you can rewrite the hook.

## 3. A script you can edit

The script is written scene by scene, with the words to speak and a description of the picture for each scene. Change anything before moving on.

## 4. Voice, pictures and captions

- The narration is recorded in the voice, pace and tone you chose.
- Each scene gets a picture or a matching stock clip.
- Captions are timed to every spoken word.

## 5. You approve, then publish

You watch the finished Short with its title and thumbnail. Nothing is posted until you approve it. Then you publish it to YouTube right away or at a time you choose.

## Tips for better Shorts

- **Lead with the payoff.** The first two seconds decide whether people keep watching.
- **One idea per Short.** Three facts is plenty for 30 to 45 seconds.
- **Check the facts.** AI can be wrong, so read the script before you approve it.

Want the agent to keep going on its own? Turn on **Autopilot** and choose the days and time: it makes a new Short on that schedule and waits for your approval.""",
    },
    {
        "slug": "post-one-video-to-youtube-instagram-and-facebook",
        "title": "Post one video to YouTube, Instagram and Facebook without rewriting it three times",
        "summary": "Each platform wants a different title, caption and hashtags. Here is how to cross-post one "
        "video properly, and how the Cross-poster agent does it for you.",
        "body": """Posting the same video everywhere is the easiest way to grow on more than one platform. Copying the same caption everywhere is not: each platform reads text differently.

## What each platform wants

- **YouTube** is a search engine. It needs a clear title with the subject near the start, a description that explains the video, and tags people actually search for.
- **Instagram** shows only the first line of a caption before "more", so that line has to hook people. Hashtags help people discover the Reel.
- **Facebook** works best with a short, friendly caption that starts a conversation, and few hashtags.

## Vertical or not?

A vertical video up to 3 minutes goes up as a **Short** on YouTube and a **Reel** on Instagram. Wider or longer videos go up as normal videos.

## How the Cross-poster agent helps

1. Pick any video from your Library, uploaded or made with Admart.
2. The agent listens to the video and writes a post for each platform you connected, using only what is actually said in it.
3. You check every post on one screen, change anything, and untick platforms you want to skip.
4. Post now, or pick a date and time. Scheduled posts can be cancelled any time before they go out.

Every post then shows up in your Calendar and Analytics, so you can see which platform works best for each video.

## A quick checklist before you post

- Is the first line (or title) clear on its own?
- Are the facts and names right?
- Did you follow each platform's rules for AI-generated or altered content?""",
    },
    {
        "slug": "remove-pauses-and-ums-from-video-automatically",
        "title": "Remove pauses and \"ums\" from your videos automatically",
        "summary": "Talking-head videos feel twice as fast without long pauses, filler words and restarts. "
        "Here is how automatic editing works and how to keep control of every cut.",
        "body": """Most talking videos have the same problems: long pauses, "um" and "uh", and sentences you started twice. Cutting them by hand takes longer than recording. Automatic editing does it in minutes, and you still decide what goes.

## What gets cut

- **Long pauses.** You choose how tight it feels: Gentle, Normal or Tight.
- **Filler words** such as "um" and "uh".
- **Restarts**, where you began a sentence and then said it again properly.
- **Black or frozen frames**, but only where nothing is being said.

## You review every cut

The Video Editor shows your full transcript with the planned cuts struck through, in a different colour for each reason. Click any cut to keep it, click any word to cut it, and fix the spelling of words in the captions. You also hear your original and cleaned-up sound side by side.

## Cleaner sound

Choose how much audio cleanup you want, from a free basic filter to studio-level voice isolation. Background noise goes down and your voice levels out.

## The finished video

- In the format you need: vertical 9:16, square 1:1, portrait 4:5 or the original shape.
- Captions in your brand colour, burned in.
- A title, description and thumbnail written from what you actually said.

## Tips for recording

- Pause instead of saying "um": a silent pause is easier to cut cleanly.
- If you stumble, stop and say the whole sentence again. The restart gets removed.
- Record in a quiet room. Cleanup helps, but a good recording still sounds best.""",
    },
]


def seed(apps, schema_editor):
    BlogPost = apps.get_model("blog", "BlogPost")
    for post in POSTS:
        BlogPost.objects.get_or_create(slug=post["slug"], defaults={**post, "author": "Admart team", "status": "draft"})


def unseed(apps, schema_editor):
    apps.get_model("blog", "BlogPost").objects.filter(slug__in=[p["slug"] for p in POSTS], status="draft").delete()


class Migration(migrations.Migration):
    dependencies = [("blog", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
