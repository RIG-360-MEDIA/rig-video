# RIG-Video: planned changes (before going live / production)

## 1. Editable daily story list (planned, user 2026-11-19)
Once the daily runs start again, the day's DNL picks are a **queue**: one hour after the selection is published,
every story still on the list goes into video building automatically.

During that hour, a signed-in user can change the list:
- **Remove** any story, so no video is made from it.
- **Add** any story straight from DNL, so it gets a video too.

Today (for comparison): "Hide" only removes a card from that user's own view (saved in prefs/<user>.json hiddenPicks).
Nothing is built automatically; a story is made only when someone presses "Use this story".

To settle when we build it:
- One shared list per workspace, or one per user? (Automatic building suggests one shared list.)
- Does the hour start when the selection is published? Can a user end the hour early?
- How does a user find a DNL story to add: search DNL articles (read-only DB) or paste the article link?
- Does a story added after the hour ends join the next batch, or start building right away?
