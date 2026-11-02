# Cross-poster agent

## Goal
One Library video → a post written for each connected platform (YouTube, Instagram, Facebook) from what is
actually said in the video → you check all of them on one screen → the agent posts them, now or at a time
you pick.

## User decisions (2026-10-14)
- Source: any ready Library video (uploaded or agent-made).
- Approval: AI writes the posts, you edit/approve once, then the agent posts by itself.
- Timing: post now, or one chosen date/time for all platforms.
- Platforms: YouTube, Instagram, Facebook (whichever are connected; untick any at the review).
  TikTok waits for its Content Posting API approval.

## Steps
| Step | What it does | Cost |
|---|---|---|
| `fetch` | Probe the video (no length limit), take the first 3 min of sound | free |
| `listen` | Transcript via fal Whisper (reuses the Video Editor's transcribe); silent videos skip it | ≤ $0.018 |
| `write_post` | One OpenRouter call writes: YouTube title/description/tags, Instagram caption + hashtags, Facebook caption. Title check on the YouTube title. Thumbnail with text (agent-made videos keep theirs) | free models |
| `review_post` (gate `post`) | You edit every post, untick platforms, YouTube privacy, now or a date/time | — |
| `wait` | If a time was picked, the run sleeps until then (status queued, `locked_until` = that time); cancel = discard, refunded | — |
| `post` | One `PublishJob` (Calendar/Analytics) and the existing publishers, one platform at a time | — |

- Vertical and ≤ 3 min → YouTube Short (`#Shorts` in the description); Instagram posts it as a Reel.
- Scheduling is done by the agent itself (same for every platform), not by each platform's scheduler.
  Needs the plan's `can_schedule_publishing`, like the Publish page.
- Scheduled runs don't count toward the 3-open-runs-per-agent limit.

## Safety
- Each platform's result is saved before and after its upload. A retry skips platforms that succeeded;
  an upload interrupted mid-way is marked "check before posting again" and never re-uploaded automatically.
- If every platform fails the run fails and is refunded; if some succeed the run succeeds and lists the
  failures (post those again from the Publish page).
- "Contains synthetic media" is set on YouTube only for AI-made videos, not uploads.

## Frontend
- Start: `AgentVideoPicker` (3-minute limit and per-minute price only for the Video Editor), "Post this video".
- `AgentPostReview` (new): a card per platform with its text, YouTube title check + thumbnail, privacy,
  now / date-time.
- Workflow summaries; finished run shows each platform's result; scheduled run shows the time and "Cancel".

## Tests
- Dry run: fetch → listen → write_post → gate → post (publishers mocked), PublishJob created.
- Retry after partial success re-posts only the failed platform; interrupted upload is not repeated.
- Schedule: past time / locked plan rejected; future time makes the run wait; discard refunds.
- Start refused with no connected platform, and for another project's asset.
