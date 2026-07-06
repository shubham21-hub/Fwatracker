---
name: cc.fwafarm.com has no positive "not banned" marker
description: Why ban-status parsing for cc.fwafarm.com member pages must treat "no ban keyword + valid parsed member data" as confident not-banned, not as an ambiguous/unparseable page.
---

cc.fwafarm.com's member page never renders an explicit "not banned" / "no ban" string for clean players — it simply omits any ban-related text entirely. Only banned players get a "🚨BANNED🚨" style marker.

**Why:** A parser that requires a *positive* not-banned signal before returning `found=True, banned=False` (to avoid the failure mode of silently reporting a clean result on a page it can't understand) will misfire on every legitimate clean player, since no such positive signal exists on this site.

**How to apply:** Only escalate to a hard "could not confidently determine ban status" error when the page could not even be parsed as a real member page (no player name extracted, no clan/rank/tracked-actions content). If a player name *was* successfully extracted and no ban keyword appears anywhere in the scoped main-content text, treat that as a confident "not banned" — don't require an explicit not-banned string match.
