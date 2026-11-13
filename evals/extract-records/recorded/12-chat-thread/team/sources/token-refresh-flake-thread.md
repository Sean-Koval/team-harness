---
id: token-refresh-flake-thread
type: source
scope: team
status: processed
date: '2026-11-11'
owner: eli-example
sources:
- resource: https://chat.example.invalid/rooms/agent-platform/threads/token-refresh-flake
  hash: sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674
links: []
description: 'token-refresh flake in sandbox jobs'
schema_version: 1
revision: '1'
provider: chat
title: 'token-refresh flake in sandbox jobs'
observed_at: '2026-11-11T10:15:00+00:00'
obligations: []
---
Room: agent-platform
Exported: 2026-11-11, thread "token-refresh flake in sandbox jobs"
Members: Ana Reyes (ana-example), Ben Tanaka (ben-example), Chidi Obi (chidi-example), Dana Kowal (dana-example), Eli Marsh (eli-example), ci-bot

[09:02] ci-bot: Job 4411 (repo: billing-adapter, ticket PLAT-433) failed: integration/test_token_refresh.py::test_refresh_before_expiry
[09:03] Eli Marsh: and there it is again. that's 10 in two weeks
[09:03] Eli Marsh: always the same test, always in sandbox jobs
[09:05] Ben Tanaka: passes for me locally every time fwiw
[09:05] Dana Kowal: same. I talked about this in the sync on Monday, I think it's the clock
[09:06] Eli Marsh: as usual I reran it once and it passed, so per the rule it's reported, not rerun again
[09:06] Eli Marsh: [attachment: job-4411-log.txt]
[09:08] Chidi Obi: looking at the log. "token expired 41s before refresh window" ... yeah that smells like time
[09:09] Dana Kowal: @Ana Reyes quick q, do you know if the sandbox clock is synced from the host or via NTP? I couldn't find it in the image docs
[09:10] Ben Tanaka: :eyes:
[09:14] Ana Reyes: From the host, at boot, and that's it. Nothing re-syncs it during the job. The image has no NTP client, on purpose, since egress is closed
[09:14] Ana Reyes: and a restored snapshot keeps whatever time it had when the snapshot was taken, until the next boot
[09:15] Dana Kowal: > Ana Reyes 09:14: Nothing re-syncs it during the job
[09:15] Dana Kowal: that's it then. snapshots restore without a reboot. the clock can be minutes behind
[09:15] Eli Marsh: [reaction: :dart: x2]
[09:16] Chidi Obi: wait, how far behind can it get
[09:17] Dana Kowal: depends how old the snapshot is. we refresh them every few hours, so... up to a few hours in theory? the test only tolerates 60s
[09:18] Ben Tanaka: oof
[09:18] Eli Marsh: let me check 4411
[09:21] Eli Marsh: ran `date -u` in a fresh restore of the same snapshot vs the host: sandbox is 3m12s behind
[09:21] Eli Marsh: so yes
[09:22] Ana Reyes: nice find. so the test was right the whole time
[09:22] Dana Kowal: the test was right the whole time :sob:
[09:23] Chidi Obi: ok so, proposal while we're here. from now on every flaky test gets quarantined with a @flaky marker within an hour of the second failure, no exceptions. we lose too much time to reruns
[09:24] Ben Tanaka: hmm
[09:25] Ana Reyes: I don't love that. this one would have been quarantined two weeks ago and we'd never have found the clock
[09:25] Dana Kowal: yeah, I said the same on Monday. quarantine hides exactly this kind of thing
[09:26] Chidi Obi: but the reruns are real cost. eli has rerun this thing like ten times
[09:26] Eli Marsh: once per failure, per the rule. it's annoying but it's not ten reruns per failure
[09:27] Chidi Obi: fair
[09:27] Ben Tanaka: also, a quarantined test in an agent job means the agent's PR goes green when it shouldn't. reviewers trust green
[09:28] Chidi Obi: ok that's the better argument. what if quarantine needs a ticket?
[09:29] Ana Reyes: still no from me. we'd end up with a quarantine list nobody reads. we already have rerun-once-then-report and it worked here, it's how we got to the clock
[09:30] Dana Kowal: -1 from me too, sorry chidi
[09:30] Chidi Obi: no worries. withdrawn, we keep rerun once then report
[09:30] Ana Reyes: thanks. not adopting the quarantine rule then
[09:31] Ben Tanaka: [reaction: :+1: x3]
[09:33] Eli Marsh: unrelated but is anyone going to the lunch thing today? the new place on the corner
[09:33] Ben Tanaka: the dumpling one? yes
[09:34] Chidi Obi: I went last week. get the pan-fried ones, skip the soup
[09:34] Dana Kowal: I'm in if it's after 12:30, I have a call
[09:35] Eli Marsh: 12:45 then
[09:35] Ben Tanaka: :dumpling:
[09:37] Dana Kowal: ok back to the clock. fix is simple: resync the clock from the host as the first step after a snapshot restore. I'll add that to the restore script, PR by Friday
[09:38] Ana Reyes: great, thanks. please tag me on it
[09:38] Dana Kowal: will do
[09:39] Chidi Obi: should the test itself be more tolerant? 60s is tight
[09:40] Dana Kowal: no, the 60s is the real refresh window in prod. if the sandbox clock is wrong the sandbox is wrong
[09:40] Chidi Obi: ok, makes sense
[09:41] Eli Marsh: writing this down before we forget it. Lesson: when a time-based test flakes only in sandbox jobs, compare the sandbox clock with the host (`date -u` in both) before rerunning anything. We lost about two weeks rerunning this one.
[09:41] Eli Marsh: (edited) We lost about two weeks rerunning and staring at the mock server.
[09:42] Ana Reyes: +1, good one
[09:42] Ben Tanaka: +1
[09:43] Dana Kowal: should I put the date check in the job template too?
[09:44] Ana Reyes: not yet, let's see if the resync fixes it first
[09:44] Dana Kowal: ok
[09:45] ci-bot: Job 4415 (repo: billing-adapter, ticket PLAT-433) passed
[09:46] Ben Tanaka: lol it passed now, of course
[09:46] Eli Marsh: fresh snapshot probably
[09:47] Chidi Obi: btw who's telling the support desk about the handoff time? that was left open on monday
[09:48] Ana Reyes: not this thread please :) take it to the delivery room
[09:48] Chidi Obi: right, sorry
[09:50] Ben Tanaka: is the snapshot refresh interval written down anywhere? "every few hours" is a bit vague
[09:52] Dana Kowal: every 4 hours, it's in the restore script header. I'll mention it in the PR
[09:52] Ben Tanaka: thanks
[09:54] Eli Marsh: closing the loop on 4411: root cause is clock skew after snapshot restore, fix incoming from dana, no quarantine
[09:55] Ana Reyes: [reaction: :white_check_mark: x4]
[10:12] Dana Kowal: PR is up as a draft: resync clock on restore. https://git.example.invalid/platform/sandbox-image/pull/88
[10:13] Ana Reyes: on it
