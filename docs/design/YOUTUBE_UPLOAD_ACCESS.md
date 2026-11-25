# YouTube upload access for the Anchor Studio pipeline: exact steps

**Goal:** the pipeline on trijya-7 uploads each finished video (about 5 a day) to the Democracy News Live channel
(https://www.youtube.com/@democracynewslive8562) and adds it to a public "Video Bulletin" playlist. The site's Watch section
shows that playlist through YouTube's player.

**Who does what:**
- **Steps 1-6:** someone who is an **Owner or Manager of the DNL YouTube channel**, signed in with that Google account.
- **Step 7:** me, with the owner present for one sign-in.

I can't do the sign-ins or enter passwords myself. Nothing here costs money.

---

## Step 1: Create a Google Cloud project (2 min)
1. Open https://console.cloud.google.com/ while signed in with the channel owner's Google account (or a Google Workspace
   account of DNL's).
2. Top bar → project picker → **New project**. Name it `DNL Anchor Studio`, then **Create**, then select it.
3. Note the **Project number**: Home → Project info. The audit form in step 6 asks for it.

## Step 2: Enable the YouTube Data API (1 min)
1. Left menu → **APIs & Services → Library** (https://console.cloud.google.com/apis/library).
2. Search **YouTube Data API v3** → open it → **Enable**.

## Step 3: Set up the consent screen ("Google Auth Platform") (5 min)
1. Left menu → **APIs & Services → OAuth consent screen**. In the newer console this is called **Google Auth Platform**:
   https://console.cloud.google.com/auth/overview. Click **Get started**.
2. **App information:** App name `DNL Anchor Studio`; User support email: your email. Then **Next**.
3. **Audience:** choose **External**. Then **Next**.
4. **Contact information:** your email. Then **Next**, agree to the policy, then **Create**.
5. **Branding** (left menu), needed later for the audit:
   - App home page: `https://global.democracynewslive.com`
   - Privacy policy: the DNL privacy policy URL
   - Terms of service: the DNL terms URL

   Save.
6. **Data access** (left menu) → **Add or remove scopes** → tick these two (search "youtube") → **Update** → **Save**:
   - `https://www.googleapis.com/auth/youtube.upload` (upload videos)
   - `https://www.googleapis.com/auth/youtube` (add videos to the playlist)
7. **Audience** (left menu) → **Publishing status** → **Publish app**, then confirm.
   - **Why this matters:** while the app is in "Testing", Google expires the sign-in after **7 days**, and uploads
     would stop every week. "In production" keeps it working.
   - Google will show an "unverified app" warning at sign-in. That's expected and fine for our own single account
     (Google verification is only required for apps used by many people).

## Step 4: Create the OAuth client (2 min)
1. Left menu → **Clients** (or APIs & Services → Credentials) → **Create client**.
2. Application type: **Desktop app**. Name: `anchor-studio-trijya`. Then **Create**.
3. Click **Download JSON**. You get a file like `client_secret_XXXX.json`.
4. Put that file in your **Downloads** folder and tell me its name. It identifies the app; it is not your password.

## Step 4b: Create an API key for the website (2 min)
**Why:** the site reads the "Video Bulletin" playlist to know which videos to show. YouTube's public RSS feed for
playlists returns 404 for hours at a time (it was down on 12-13 Oct 2026), so the site uses the official API with a key
instead. This is free: each refresh costs 1 unit of the 10,000-unit daily quota.

1. Same project → **APIs & Services → Credentials** → **Create credentials → API key**.
2. Click the new key → **API restrictions → Restrict key → YouTube Data API v3** only → **Save**.
3. Copy the key and give it to the DNL site team, together with the playlist ID I send after step 7. They add two
   environment variables in Vercel (Project → Settings → Environment Variables, Production): `YOUTUBE_API_KEY` and
   `YT_BULLETIN_PLAYLIST_ID`.

## Step 5: Check the channel (1 min)
In YouTube Studio for the DNL channel (https://studio.youtube.com), make sure the person who will do the one-time sign-in
in step 7 is **Owner or Manager** of the channel: Settings → Permissions. If the channel sits under a Brand Account,
that person must be able to pick the DNL channel at sign-in.

(Phone verification at https://www.youtube.com/verify is only needed for custom thumbnails or videos over 15 minutes. Ours
are 60 s, so it's optional.)

## Step 6: Request the API audit: PROBABLY NOT NEEDED (re-checked 2026-10-13)
> The live videos.insert reference (https://developers.google.com/youtube/v3/docs/videos/insert, under
> `status.privacyStatus`) now says: "Videos uploaded from unverified API projects are **not restricted** to private
> viewing mode." The 2020 lock described below is gone from the official page, though older mirrors still show it.
> Do this step only if our private test upload (step 7) comes back locked.

### (Only if needed) Request the API audit (10-20 min to fill in; Google takes days to weeks)
**Why:** Google's rule is that videos uploaded through an API project created after 28 July 2020 that has **not** passed
this audit are **locked to private**. Private videos can't be shown on the site. Docs:
https://developers.google.com/youtube/v3/docs/videos/insert

1. Open the **YouTube API Services: Audit and Quota Extension Form**: https://support.google.com/youtube/contact/yt_api_form
2. Choose **"I would like to request an API audit"**. If asked about quota, the default is enough.
3. Fill in:
   - **Organisation:** Democracy News Live / RIG; website `https://global.democracynewslive.com`.
   - **Google Cloud project number:** from step 1.
   - **API client:** "Anchor Studio: an internal server-side tool, not a public app. It uploads our own newsroom's daily
     AI-presented news bulletins (~5 per day, 60 s each) to our own channel @democracynewslive8562, adds them to a
     playlist, and our website embeds that playlist with the standard YouTube player. No third-party users, no viewer
     data collected or stored."
   - **Scopes used:** youtube.upload, youtube (playlist insert).
   - **Disclosure:** every upload is flagged as altered or synthetic content (`containsSyntheticMedia`), because the
     presenters are AI-generated.
   - **Links:** the DNL privacy policy and terms (same as step 3.5). Google expects the privacy policy to mention the
     use of YouTube API Services and link to Google's privacy policy (https://policies.google.com/privacy). If it
     doesn't yet, the DNL team should add one paragraph.
   - **Screenshots or screencast**, if requested: I can produce these after step 7 (the upload log, the video on the
     channel, the site embed).
4. Submit. Google replies by email. Forward me anything they ask.

## Step 7: One-time sign-in to authorize uploads (5 min, together)
1. You tell me the JSON file's name from step 4. I run a small authorization script on this Mac. It opens a Google
   sign-in page in your browser.
2. **You** sign in as the channel Owner/Manager. If asked, **pick the DNL channel**. You'll see "Google hasn't verified
   this app": click **Advanced → Go to DNL Anchor Studio (unsafe)**. That's expected for our own app. Then tick both
   YouTube permissions → **Continue**.
3. The script saves a long-lived "refresh token". I copy it to trijya-7 (`~/.config/anchor-studio/youtube.env`, mode
   600). It never goes into git.
4. I upload one short **private** test video to confirm it lands on the right channel and the playlist works, then
   create the public **"Video Bulletin"** playlist and give you its link.

## Until the audit passes
- **Uploads will be private**, and possibly locked private even in Studio; the test in step 7 will show which.
- **Fallback:** the pipeline still writes each finished video plus a ready-to-paste title and description to
  `~/anchor-studio/output/daily/<date>/` on trijya-7. Someone can upload them by hand in YouTube Studio (about 2 min per
  video) and add them to the playlist; the site picks them up automatically either way.

## What you will NOT need any more
The video storage bucket, the Neon table and writer login, and (optionally) REVALIDATE_SECRET. The site reads the
playlist through the API key from step 4b, refreshing about every 10 minutes, with the RSS feed as a backup.
