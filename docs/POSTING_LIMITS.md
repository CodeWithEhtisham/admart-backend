# Admart Posting Limits: What We Do and Why

As of 2026-10-30.

## Summary

Admart posts AI-made videos and images to users' own YouTube, Instagram and Facebook accounts, so we cap how often it posts. The caps do two jobs: keep every user's account from being flagged as spam, and keep Admart inside the platforms' API limits. Every real upload passes through one gate in the backend (`projects/publish_limits.py`), whether it comes from the publish page, an agent, or a Google Ads boost.

## What the platforms allow

The tightest official limit is YouTube's: 100 uploads per day for all of Admart combined, because every user uploads through our one Google Cloud project.

| Platform | Official limit | Counted per | Source |
| --- | --- | --- | --- |
| YouTube (API) | 100 uploads per day | Admart's whole Google project, shared by all users | [Quota cost calculator](https://developers.google.com/youtube/v3/determine_quota_cost) |
| YouTube (channel) | A daily cap YouTube does not publish | Each channel | [videos.insert reference](https://developers.google.com/youtube/v3/docs/videos/insert) |
| Instagram | 50 posts per rolling 24 hours (a carousel counts as 1) | Each Instagram account | [Content publishing limit](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit) |
| Facebook Reels | 30 reels per rolling 24 hours | Each Page | [Reels Publishing API](https://developers.facebook.com/docs/video-api/guides/reels-publishing) |
| Facebook videos | No published daily count | Each Page | — |

We may not split Admart across several Google projects to get more YouTube quota. YouTube's [developer policies](https://developers.google.com/youtube/terms/developer-policies) (III.D.1.c) require exactly one project per app, and breaking that can shut off YouTube for every user at once.

## Admart's limits

We stay well below the official maximums, because accounts that post near them tend to get flagged as spam.

| Rule | Limit | Why |
| --- | --- | --- |
| YouTube posts | 3 per account per 24 hours | Looks human, and stretches the shared 100-per-day allowance across more users |
| Instagram posts | 10 per account per 24 hours | A fifth of Instagram's 50 |
| Facebook posts | 10 per Page per 24 hours, at most 5 of them videos | Videos stay well under the 30-reel limit |
| Gap between posts | At least 1 hour on the same account | Bursts of posts are a spam signal |
| Duplicates | Same video to the same account blocked for 3 days | Reposting identical content is the classic spam pattern |
| Shared YouTube allowance | Admart stops at 100 uploads per day, all users combined | Uploads past it would fail anyway |

The limits count scheduled posts by when they go live, not when they were set up. A channel connected to several projects shares one set of limits, so extra projects don't multiply them. The numbers are constants at the top of `projects/publish_limits.py`.

## Keeping users' accounts safe

Beyond the caps, Admart does four things so platforms never treat a user's account as a spam bot.

1. **Stops when a platform pushes back.** A quota, rate-limit or spam error pauses posting to that account for 24 hours instead of retrying. Ordinary failures, like a network error, don't count against the user.
2. **Labels AI content.** YouTube requires creators to disclose realistic AI-made content. Admart-made videos are always marked as AI-generated on YouTube, and users can't turn it off.
3. **Spreads out scheduled posts.** Each scheduled post gets a random 0–5 minute delay, so posts never land at the exact same second.
4. **Uses official logins only.** Accounts connect through each platform's own sign-in (OAuth). Admart never asks for passwords or automates logins.

When Admart refuses a post, the user sees a plain reason for that platform, such as "Leave at least an hour between YouTube posts. Schedule this one later."

## Before launch

The most urgent item is YouTube quota: at 3 posts each, 100 uploads a day serves only about 33 active YouTube users.

- [ ] Apply for more YouTube quota through Google's "YouTube API Services – Audit and Quota Extension" form. The review can take weeks.
- [ ] Prepare what the audit asks for: a live privacy policy, terms of service, and a short demo video of Admart uploading to YouTube.
- [ ] Build the runner for scheduled Instagram posts. They are saved as "scheduled" today, but nothing posts them later.
- [ ] Decide whether the limits should be editable in the admin panel instead of in code.

Instagram and Facebook get no AI label from Admart: we found no setting for one in Meta's publishing API.
