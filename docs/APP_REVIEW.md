# App review guide: Google / YouTube, Meta, TikTok

Copy-ready answers for each platform's review form, matched to what the code really does
(`projects/oauth.py`, `projects/publish.py`, `projects/insights.py`). Replace `https://YOUR-DOMAIN`
with the production frontend address. Keep this file in step with the code when permissions change.

## Before submitting anywhere

- [ ] Production site on https with its own domain (not an IP or a staging subdomain you'll change).
- [ ] `VITE_COMPANY_NAME`, `VITE_COMPANY_ADDRESS`, `VITE_SUPPORT_EMAIL` set; no highlighted blanks on
      `/privacy` or `/terms`.
- [ ] Homepage explains what the app does and links Privacy and Terms (it does, in the footer).
- [ ] A test account for reviewers: email and password, a project, a few Library videos and some credits.
- [ ] The app name and logo on the consent screens match the website.

Links every form asks for:

| | URL |
|---|---|
| Homepage | `https://YOUR-DOMAIN/` |
| Privacy policy | `https://YOUR-DOMAIN/privacy` |
| Terms of service | `https://YOUR-DOMAIN/terms` |
| Data deletion instructions (Meta) | `https://YOUR-DOMAIN/privacy#data-deletion` |
| OAuth redirect (social) | `https://API-DOMAIN/api/social/callback/<platform>` |

**One-line app description** (reuse everywhere):
> Admart is a social media tool for small businesses and creators. It helps them make short videos and images with AI, edit their own videos, and publish or schedule them on the YouTube, Facebook and Instagram accounts they connect, always after the user reviews and approves each post.

---

## 1. Google: OAuth app verification

Google Cloud Console → **Google Auth Platform** → Branding / Data access → Verification.

**Scopes requested**

| Scope | Sensitivity | Used for |
|---|---|---|
| `openid`, `email`, `profile` | basic | Sign in with Google |
| `https://www.googleapis.com/auth/youtube.upload` | sensitive | Upload videos the user approved |
| `https://www.googleapis.com/auth/youtube.force-ssl` | sensitive | Read the connected channel's name; set a video's thumbnail; add a video to a playlist the user picks; list the user's playlists; read view, like and comment counts of videos published through Admart |
| `https://www.googleapis.com/auth/yt-analytics.readonly` | sensitive | Growth Report: the channel's views, watch time, average view %, subscribers gained/lost and top videos for the period the user chose |
| `https://www.googleapis.com/auth/yt-analytics-monetary.readonly` | sensitive | Growth Report: estimated revenue for monetized channels, shown only to the channel owner in their report |
| `https://www.googleapis.com/auth/adwords` | sensitive | Only when the user connects Google Ads in Ads Manager, to create and read their own campaigns |

**Justification text**, one per scope:

- *youtube.upload:* "Admart uploads a video to the user's own YouTube channel only after the user reviews it, writes or approves the title, description, tags and privacy, and presses Publish or schedules it. We call videos.insert with exactly what the user approved."
- *youtube.force-ssl:* "After an upload we call thumbnails.set with the thumbnail the user chose and playlistItems.insert for the playlist the user picked. We call channels.list (mine) to show which channel is connected, playlists.list so the user can pick a playlist, and videos.list (statistics) to show view, like and comment counts for videos the user published through Admart. We do not store those counts."
- *yt-analytics.readonly:* "Our Growth Report agent, which the user schedules (weekly, every 15 days or monthly), reads the user's own channel totals for the period and the one before (views, estimated minutes watched, average view percentage, subscribers gained and lost, likes, comments, shares) and the top 10 videos, and explains them with a plan for the next period. The report is shown in the app and emailed to the user."
- *yt-analytics-monetary.readonly:* "In the same report, the channel owner sees their estimated revenue for the period compared with the previous one. Only for monetized channels; never shared with anyone else."
- *adwords:* "Only for users who connect Google Ads in our Ads Manager page, to create the ad campaigns they configure and show their results."

**Demo video** (unlisted YouTube link; 2–4 minutes; no cuts during the consent flow):
1. Show the homepage with the address bar (domain visible), then Privacy and Terms.
2. Sign in, open **Social Accounts**, click **Connect YouTube**.
3. On Google's consent screen, **show the address bar with the `client_id`** and the scopes listed, then allow.
4. Back in the app, show the connected channel name (channels.list).
5. Open a video in the **Library** → **Publish**: set title, description, tags, privacy (choose *Unlisted*), pick a thumbnail and a playlist → Publish.
6. Show the video on YouTube Studio with that title, thumbnail and playlist (videos.insert, thumbnails.set, playlistItems.insert).
7. Open **Analytics** and show the view count for that video (videos.list).
7b. Open **Agents → Growth Report** → **Make the report**: show the views, watch time, subscribers and revenue
    (YouTube Analytics API), the top videos, and the emailed copy.
8. Open **Social Accounts** → Disconnect YouTube, and say that this deletes the stored tokens.

---

## 2. YouTube API Services: audit and quota extension

Form: *YouTube API Services – Audit and Quota Extension Form*. The default 10,000 units/day is about
6 uploads (each upload costs 1,600 units), so request more before launch.

- **API client purpose:** "A publishing tool: users connect their own channel and upload or schedule the videos they made or edited in Admart, after reviewing title, description, tags, privacy and thumbnail."
- **API services used:** videos.insert, thumbnails.set, playlistItems.insert, playlists.list, channels.list (mine), videos.list (statistics and snippet), and the YouTube Analytics API reports.query (channel==MINE) for Growth Reports.
- **Data stored:** the channel ID, name and avatar, and encrypted OAuth tokens while connected; the YouTube video ID of each upload. Statistics on the Analytics page are fetched live and not stored. Growth Reports keep the YouTube Analytics numbers they show (policy III.E.4.b), every report run re-checks authorization, and disconnecting YouTube deletes the tokens and removes YouTube numbers from saved reports. Deleting the account deletes everything.
- **Data shared:** none with third parties. YouTube data is never sent to AI providers.
- **Users can revoke access:** Social Accounts → Disconnect, or Google's security settings (linked in the Privacy Policy).
- **Quota estimate:** (expected uploads per day × 1,600) + (thumbnail and playlist calls × 50) + small reads. For example 100 uploads/day ≈ 170,000 units.
- **Compliance with the YouTube Terms and Developer Policies:** the Terms link YouTube's Terms of Service; the Privacy Policy links the Google Privacy Policy, explains the API data use, and gives the revoke link.

Screenshots/screencast: reuse the Google demo video.

---

## 3. Meta (Facebook + Instagram): App Review

developers.facebook.com → your app → **App Review → Permissions and features**. Business verification
is required for advanced access. Set the **Data deletion instructions URL** in App settings → Basic.

| Permission | How Admart uses it (paste into "How will your app use this permission") |
|---|---|
| `public_profile` | Shows the name of the connected Facebook account on the Social Accounts page. |
| `pages_show_list` | Lists the user's Facebook Pages so they can choose which Page to publish to. |
| `pages_read_engagement` | Reads views and likes for posts the user published to their Page through Admart, shown on the Analytics page. |
| `pages_manage_posts` | Publishes the video or image the user approved, with their caption, to the Page they chose, now or at the scheduled time they set. |
| `business_management` | Finds the Pages and Instagram business accounts the user manages through Business Manager, so they can connect them. |
| `instagram_basic` | Shows the connected Instagram business account's username and picture. |
| `instagram_content_publish` | Publishes the Reel or image the user approved, with their caption, to their Instagram business account. |
| `instagram_manage_insights` | Reads views and likes for posts published through Admart, shown on the Analytics page. |
| `ads_management`, `ads_read` | Only if you submit Ads Manager: create the ads the user configures and show their results. Leave these out if you don't need ads yet. |

**Screencast per permission:** one recording can cover several. Show:
1. Login → **Social Accounts** → **Connect Meta**: Facebook's dialog with the permissions, then choose the Page and Instagram account.
2. Library video → **Publish** → tick Facebook and Instagram, write the captions → Publish. Then show the post live on the Page and the Instagram profile.
3. **Analytics** with the engagement numbers.
4. Disconnect Meta (it deletes the tokens).

Notes for the reviewer (paste into "Additional notes"):
> Test account: [email] / [password]. Log in, open Social Accounts and connect a Facebook Page with a linked Instagram business account. Publishing only happens after the user reviews a post and presses Publish or schedules it. Data deletion instructions: https://YOUR-DOMAIN/privacy#data-deletion

After approval, set `FACEBOOK_PUBLISH_ENABLED=True` and `INSTAGRAM_PUBLISH_ENABLED=True` on the server.

---

## 4. TikTok: Login Kit and Content Posting API

developers.tiktok.com → your app → Products: **Login Kit** (`user.info.basic`) and **Content Posting API**
(`video.upload`, `video.publish`).

- **Product description:** reuse the one-line app description. Say that users post their own videos after approving them.
- **Scope explanations:**
  - `user.info.basic`: show the connected TikTok account's name and avatar.
  - `video.upload` and `video.publish`: post the video the user approved to their TikTok account.

⚠️ **Work needed before the TikTok audit.** TikTok requires a specific posting screen for *direct post*. Admart's TikTok publisher posts as **private (SELF_ONLY)** with no options. Before applying, add:
- the creator's nickname and avatar (from `creator_info`) on the posting screen;
- a privacy choice from the options TikTok returns, with no default selected;
- toggles for comments, duet and stitch, respecting what `creator_info` disables;
- a commercial content disclosure, plus "Your brand" and "Branded content" options;
- a notice that processing can take a few minutes.

Until then, keep `TIKTOK_PUBLISH_ENABLED=False`. Unaudited apps can only post privately anyway.
