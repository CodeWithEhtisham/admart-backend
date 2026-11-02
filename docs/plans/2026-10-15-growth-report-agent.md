# Growth Report agent: plan

**Status:** approved 2026-10-15. Owner decisions are in section 8.

**The idea:** every week, every 15 days or every month, read the user's results, explain what happened in
plain words, and give a concrete plan for the next period. Deliver it to email (and later WhatsApp or
Telegram) and in the app, so the user can decide what to do next.

## 1. What competitors do (researched 2026-10-15)

| Product | Scheduled delivery | What the report says | Next-period plan | Gap |
|---|---|---|---|---|
| **Publer** | Weekly/monthly PDF by email, one mini-report per account | Numbers only | No | No insights; PDF only |
| **Metricool** | Branded PDF/PowerPoint reports on a schedule; AI reports from a prompt | Charts, competitors, best times | No | Built for agencies; charts, not decisions |
| **Hootsuite / Sprout Social** | Custom reports; AI assistant (OwlyGPT) for captions and ideas | Rich analytics | Partly (ideas, best times) | Expensive: per-seat pricing, Sprout reports from about $399/month |
| **vidIQ AI Coach** | **None: in-app chat only** | Channel audit, why a video stalled | Yes, content plan in chat | YouTube only; the user must ask |
| **DIY n8n templates** (YouTube + GPT + Gmail) | Weekly email | AI summary | Sometimes | Need days of setup, API keys and upkeep |

**The gap no one fills:** a report that arrives on its own, **explains** the results in plain words, gives a
**concrete next-period plan**, and lets the user **act on it in one click**. Today users get numbers
(Publer, Metricool) *or* advice they have to ask for (vidIQ), and never both together with the tools to
make the content.

## 2. How Admart's version is better

1. **Report → action.** The plan lists real posts (topic, hook, best day/time, platform). **Approve plan**
   adds the topics to the Shorts Autopilot queue and schedules the times. No competitor closes this loop.
2. **Plain-language verdict first.** For example: "Good week: views +38%. Your 2 how-to Shorts did 3× better
   than the facts ones. Post more how-tos, Tuesday evening." Charts come after.
3. **Goals with pace.** The user sets a goal (for example +500 subscribers this month); each report says
   whether they're on track and what pace is needed.
4. **Learns from the user's own data:** best format, best topics, best posting times, best platform, from
   their own posts rather than generic industry tables.
5. **Uses fresh trends:** the plan mixes what worked with this week's rising topics (Trend Finder).
6. **Honest:** it only states numbers we really have, and says "not enough data yet" instead of guessing.
7. **Delivered where the user is:** email first (works today), WhatsApp/Telegram next, and always in the app.
8. **Cheap:** about 0.01–0.02 credits per report (one or two text calls and an optional web search).

## 3. What the report contains

1. **Verdict:** 2–3 sentences, plus a traffic light (better / same / worse than last period).
2. **Key numbers vs the previous period:** posts, views, likes, comments, engagement rate, followers.
3. **Top 3 and bottom 3 posts,** with why (format, topic, hook, time, length).
4. **What worked / what didn't:** patterns by format, topic, platform, day and time.
5. **Goal progress** and the pace needed (if the user set a goal).
6. **Next-period plan:** N posts (N = the user's chosen cadence), each with topic, hook, format, platform,
   and suggested day and time.
7. **3 growth actions:** for example "reply to comments in the first hour", "re-post your best Short to
   Instagram", "your titles over 60 characters underperform".
8. **Buttons:** Approve plan (add to Autopilot), Open full report.

## 4. Data: what's possible without new permissions

| Data | Source | Phase |
|---|---|---|
| Posts published through Admart, with views, likes and comments | existing (`PublishJob` + live stats) | 1 |
| YouTube subscribers, total views, video count | `channels.list?part=statistics` (existing `youtube.force-ssl` scope) | 1 |
| Instagram followers, media count | existing `instagram_basic` | 1 |
| Facebook Page followers | existing `pages_read_engagement` | 1 |
| YouTube watch time, average view %, traffic sources, audience, **all** videos (not only Admart's) | YouTube Analytics API, **new scope** `yt-analytics.readonly` | 2 |
| YouTube **revenue** | **new scope** `yt-analytics-monetary.readonly` (monetized channels only) | 2 |

**YouTube policy note:** API statistics may only be kept for **30 days**. Follower snapshots are kept 35 days
at most (enough for a month-over-month comparison) and then deleted. The Privacy Policy line "statistics
are not stored" changes to "kept up to 30 days to calculate growth".

**Phase 2's new scopes** mean users must reconnect YouTube, and the scopes go into the Google review. Decide
**before** submitting the Google review, so it covers them in one go.

## 5. Delivery

| Channel | Phase | Notes |
|---|---|---|
| In-app (agent page, Notifications, bell) | 1 | Existing inbox |
| **Email** (HTML, plus a link to the full report) | 1 | The app already sends email (SMTP settings); free |
| **Telegram** | 2 | Free bot; the user taps a link once to connect; instant |
| **WhatsApp** | 2–3 | Needs a WhatsApp Business account, Meta business verification, an approved message template, and a small cost per message |
| Slack | later | Incoming webhook URL |

## 6. Schedule

- Every **week**, every **15 days** or every **month**, at a day/time in the user's time zone.
- Covers the last 7 / 15 / 30 days, compared with the period before.
- Reuses Autopilot: `schedule` gains `"every": 7 | 15 | 30` (days), and `next_slot` adds that many days.
  The existing worker loop runs it, and "Run now" also works.

## 7. Build (Phase 1)

- **Agent** `growth-report` (single task; steps `collect → analyze → deliver`).
  - `collect`: the posts in this period and the one before, with live stats, plus follower snapshots
    (new `AccountSnapshot` model: account, date, followers, views, videos; rows older than 35 days deleted).
  - `analyze`: one OpenRouter call (and Trend Finder's search when the plan needs fresh topics) → verdict,
    wins/losses, plan, actions, all as JSON. The numbers are computed in code; the AI only interprets them.
  - `deliver`: in-app notification plus HTML email to the project owner (and up to 5 extra addresses the
    user adds).
- **Settings:** frequency, day/time, goal (metric, target, by date), posts per week in the plan, email
  recipients.
- **UI:** report view (verdict, numbers with arrows, top/bottom posts, plan cards with **Approve plan** and
  per-item **Make a Short**); schedule card; past reports list.
- **Tests:** period maths and comparison, low-data report, snapshot clean-up after 35 days, email content,
  schedule every 15 days, Approve plan filling the Autopilot queue.

## 8. Owner decisions (2026-10-15)

1. **Data:** include the YouTube Analytics API now (`yt-analytics.readonly` and `yt-analytics-monetary.readonly`):
   watch time, average view %, subscribers gained/lost, all videos and revenue (monetized channels).
   Users who connected before this must reconnect YouTube; the report says so and links Social Accounts.
   Storage follows YouTube policy III.E.4.b: Analytics data may be kept while the user stays authorized.
   Each report re-checks access, and disconnecting YouTube removes the YouTube numbers from saved reports.
   Instagram/Facebook follower counts are read live (no snapshots needed).
2. **Delivery:** email and in-app now. WhatsApp, Telegram and Slack show as "Coming soon".
3. **Price:** the real cost in credits (one text call with web search, ~0.01-0.02), refunded on failure.
