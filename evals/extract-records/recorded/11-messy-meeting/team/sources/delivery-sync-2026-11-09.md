---
id: delivery-sync-2026-11-09
type: source
scope: team
status: processed
date: '2026-11-09'
owner: ana-example
sources:
- resource: https://meet.example.invalid/recordings/delivery-sync-2026-11-09
  hash: sha256:e08b689e6628394e64251bedb445a33c5aa51277f694c97098b240604d395a2a
links: []
description: 'Weekly delivery sync, 2026-11-09'
schema_version: 1
revision: '1'
provider: meeting
title: 'Weekly delivery sync, 2026-11-09'
observed_at: '2026-11-09T15:10:00+00:00'
obligations: []
---
Weekly delivery sync, 2026-11-09
Recording transcript (auto-generated, unedited)
Attendees: Ana Reyes (ana-example), Ben Tanaka (ben-example), Chidi Obi (chidi-example), Dana Kowal (dana-example), Eli Marsh (eli-example, joined late)

00:00:04 Ana Reyes: Okay, I think we're recording. Can people hear me?
00:00:07 Ben Tanaka: Yep.
00:00:08 Chidi Obi: Yes. You're a bit quiet but yes.
00:00:11 Ana Reyes: Is that better? I moved the mic.
00:00:13 Chidi Obi: Much better.
00:00:15 Ana Reyes: Great. Eli said he'd be five minutes late, he's coming off the customer call. Let's just start, we have three things and I want to actually finish on time today for once.
00:00:24 Dana Kowal: Famous last words.
00:00:26 Ana Reyes: [laughs] I know. Before we start, did everyone see the agenda doc? I put the three items at the top.
00:00:31 Ben Tanaka: I saw it this morning. Is the flaky test one still on there or did that get fixed?
00:00:35 Dana Kowal: Still on there. Not fixed. I'll explain when we get to it.
00:00:38 Chidi Obi: My camera's going to stay off, by the way, my connection's doing that thing again.
00:00:42 Ana Reyes: That's fine. Okay. First one is the on-call handoff. Right now handoff is Monday at nine thirty, and it keeps colliding with standup, so the outgoing person is half in standup, half writing the note, and the incoming person gets a note that says "see the channel", basically.
00:00:44 Ben Tanaka: That was me last week. Sorry.
00:00:46 Ana Reyes: No, it's not a you problem, it's the slot. So the proposal on the board was to move the handoff to Friday at four. End of week, everyone's wrapping up anyway, you write the note while it's fresh.
00:00:58 Dana Kowal: I like Friday. I'd rather hand off with the week in my head than reconstruct it on Monday morning.
00:01:04 Chidi Obi: Same. Friday four is fine for me.
00:01:07 Ben Tanaka: Does anyone—
00:01:07 Dana Kowal: And it means—
00:01:08 Ben Tanaka: Sorry, go ahead.
00:01:09 Dana Kowal: No, you go.
00:01:10 Ben Tanaka: I was just going to ask, does the pager rotation flip automatically or does someone flip it?
00:01:15 Ana Reyes: Someone flips it. It's a manual edit in the schedule. We can deal with that after.
00:01:20 Ben Tanaka: Okay.
00:01:21 Ana Reyes: Alright, sounds like nobody objects. So, decided: on-call handoff moves to Friday at four, starting this week. And as before, the outgoing person writes the handoff note. That doesn't change.
00:01:33 Chidi Obi: Sounds good.
00:01:35 Ana Reyes: Okay. Second thing, the changelog. Chidi, this is yours.
00:01:39 Chidi Obi: Yeah. So, the change lock — the changelog — the hand-written CHANGELOG file. Nobody updates it until release day and then I spend an hour going through merged PRs trying to remember what each one did. Last release I missed two entries entirely and the support desk found out from a customer.
00:01:57 Dana Kowal: Ouch.
00:01:58 Chidi Obi: Yeah. So my proposal is we stop hand-writing it. We generate the release notes from the PR titles, grouped by the conventional commit prefix. feat, fix, and so on. The tool's already in the repo template, we just never turned it on.
00:02:12 Ben Tanaka: Do PR titles hold up for that, though? Some of mine are like "fix the thing".
00:02:17 Chidi Obi: Some of them are bad, sure. But they already have to carry the ticket key, so people already look at them. And honestly a bad title in the notes is a better nudge than a missing entry.
00:02:28 Dana Kowal: Should we lint the titles then? Like a check that fails if the title doesn't read as a sentence or whatever?
00:02:33 Chidi Obi: Maybe later. I don't want to add a gate on day one. Let's see how bad it is first.
00:02:38 Ana Reyes: Yeah, let's not add a check yet.
00:02:40 Ben Tanaka: What about reverts? If I revert something, does it show up as a feature and then a… a negative feature?
00:02:46 Chidi Obi: It skips reverts and the PR it reverted, if both are in the same release. I tested that last week.
00:02:51 Ben Tanaka: Oh nice. Okay.
00:02:53 Ana Reyes: Chidi, it's your call, you own releases.
00:02:56 Chidi Obi: Then yes. Decided: from the next release on, release notes are generated from PR titles, and we delete the hand-written CHANGELOG.
00:03:04 Ana Reyes: Great.
00:03:05 Dana Kowal: Do we keep the old file around for history or—
00:03:08 Chidi Obi: Git has the history. I'll delete it in the same PR that turns the generator on.
00:03:13 Ana Reyes: Okay.
00:03:15 [Eli Marsh joined]
00:03:16 Eli Marsh: Hey, sorry, sorry. Customer call ran over. What did I miss?
00:03:20 Ana Reyes: Hey Eli. Not much. Changelog is now generated from PR titles, that's done. And we moved on-call handoff to Friday at four.
00:03:28 Eli Marsh: Oh. Hm.
00:03:30 Ana Reyes: Hm?
00:03:31 Eli Marsh: Can I push back on the Friday thing? Sorry to reopen it the second I walk in.
00:03:35 Ana Reyes: No, go ahead.
00:03:36 Eli Marsh: Friday at four is the worst time for it. If the handoff note is thin, or something's half-broken, the incoming person has the whole weekend with no one to ask, because the outgoing person has logged off. With Monday you at least have everyone around if the note is missing something.
00:03:52 Dana Kowal: That's… fair, actually. I was thinking about my own week, not about the person picking it up.
00:03:57 Eli Marsh: And the support desk is off Friday afternoons. So if something comes in at five on Friday, they can't even tell the new person who's on.
00:04:04 Ben Tanaka: Oh, I didn't know that about the support desk.
00:04:06 Eli Marsh: Yeah, since October. They do a half day.
00:04:09 Chidi Obi: Then Friday's out, I think.
00:04:11 Ana Reyes: Yeah. Okay. I'm reversing that one. Let's not move it to Friday. The actual problem was the collision with standup, right? So what if we keep Monday but move it after standup.
00:04:21 Ben Tanaka: Ten?
00:04:22 Ana Reyes: Ten. Standup ends at ten to ten on a good day.
00:04:25 Dana Kowal: On a good day. [laughs]
00:04:27 Ana Reyes: Fine, ten. Anyone hate Monday at ten?
00:04:30 Eli Marsh: Monday at ten is great.
00:04:31 Chidi Obi: Works.
00:04:32 Ana Reyes: Okay, so, to be clear, because I said the other thing a minute ago: decided, on-call handoff is Monday at ten, after standup, starting next Monday the 16th. Friday is off the table. Note-writing stays with the outgoing person like always.
00:04:46 Ben Tanaka: Got it.
00:04:47 Ana Reyes: Ben, you're on call this week, right? Can you change the rotation in the pager schedule?
00:04:51 Ben Tanaka: Yeah, I'll change the rotation in the pager schedule today so the shift flips Monday at ten.
00:04:56 Ana Reyes: Thank you. And someone also needs to tell the support desk the handoff time changed, because they page whoever the schedule says.
00:05:03 Eli Marsh: Yeah, someone should—
00:05:03 Dana Kowal: Is that—
00:05:04 Chidi Obi: [crosstalk] —the desk lead, or—
00:05:06 Ana Reyes: Sorry, one at a time.
00:05:08 Dana Kowal: I was just asking whether it goes to the desk lead or the shared inbox.
00:05:11 Eli Marsh: Shared inbox, I think. They rotate the lead.
00:05:14 Ana Reyes: Okay. Anyway, it needs doing before Monday. Let's — we'll figure out who. Let's move on, I want to get to the third thing.
00:05:21 Ben Tanaka: Before we do, can I just say, Dana, did you actually do the ride on Saturday?
00:05:25 Dana Kowal: [laughs] I did. A hundred and ten kilometres. I couldn't feel my hands for the last twenty.
00:05:30 Ben Tanaka: In this weather?
00:05:31 Dana Kowal: It was four degrees at the start. I had two pairs of gloves on and it did not matter. There's a café at the halfway point that does this enormous cinnamon thing and honestly that's the only reason I finished.
00:05:42 Chidi Obi: Is that the one by the reservoir?
00:05:44 Dana Kowal: The one past the reservoir, by the old mill. The reservoir one closed.
00:05:48 Chidi Obi: Oh no. That was a good one.
00:05:50 Eli Marsh: Are you doing the spring one too? The two hundred?
00:05:53 Dana Kowal: If my hands grow back. [laughs] Ben, you said you'd come.
00:05:57 Ben Tanaka: I said I'd think about it. My bike has been a coat rack since August.
00:06:01 Ana Reyes: Okay, okay, I'm cutting this off. [laughs] We can do bikes after. Third thing. Dana, the flaky integration test.
00:06:08 Dana Kowal: Right. Sorry. So the token-refresh test in the sandbox suite has failed nine times in the last two weeks, always in agent jobs, never locally. I haven't found it yet. I've ruled out the mock server, it's the same version everywhere.
00:06:22 Eli Marsh: Is it time-based? Token stuff usually is.
00:06:25 Dana Kowal: Probably. It checks that a token minted with a five-minute expiry is refreshed at four minutes. If the clock's off, that falls apart.
00:06:33 Eli Marsh: The sandboxes are restored from a snapshot, right? So the clock could be whatever it was when the snapshot was taken, until something resyncs it.
00:06:41 Dana Kowal: That's my best guess too. I want to prove it before I touch anything.
00:06:45 Ana Reyes: Do we want to quarantine the test in the meantime?
00:06:48 Dana Kowal: I'd rather not. If it's the clock, the test is right and the sandbox is wrong. Quarantining it would hide exactly the thing we're looking for.
00:06:56 Ben Tanaka: Agreed. Leave it in.
00:06:58 Ana Reyes: Okay. Leave it in. Dana, keep digging, and bring it to the thread when you know more. I'm not going to make that an action, you're already on it.
00:07:05 Dana Kowal: Yep.
00:07:06 Chidi Obi: Oh, one thing on the release side, quickly. We already agreed this last month, but just so it's on the recording: every PR still needs one approval before merge, generated notes or not. The generator doesn't change that.
00:07:17 Ana Reyes: Right, nothing changes there.
00:07:19 Eli Marsh: Can I ask one more thing about the generator? Does it pick up the ticket key from the title, or does it strip it?
00:07:24 Chidi Obi: It keeps it and links it. So the notes link back to the ticket.
00:07:28 Eli Marsh: Nice. The desk will like that.
00:07:30 Ana Reyes: Okay. Anything else?
00:07:32 Ben Tanaka: Should we write up the Friday thing somewhere? Like, a lesson, "don't move handoff to the end of the week"?
00:07:37 Ana Reyes: I don't think it's a lesson, we just caught it before it happened. The decision itself says Monday. That's enough.
00:07:43 Ben Tanaka: Fair.
00:07:44 Dana Kowal: Are we doing the retro on Thursday or is that moved?
00:07:47 Ana Reyes: Thursday, same time. Okay, I think that's it. Recap, quickly. One: on-call handoff is Monday at ten, starting the 16th. Not Friday. Ben updates the pager schedule today. Somebody tells the support desk, and we still need a name for that. Two: release notes come from PR titles from the next release, Chidi turns the generator on and deletes the old file. Three: Dana keeps on the flaky test, no quarantine.
00:08:12 Chidi Obi: Sounds right.
00:08:13 Eli Marsh: Who's telling the desk, then?
00:08:15 Ana Reyes: Ugh, I — let's sort it in the thread. I have to jump to another call.
00:08:19 Dana Kowal: Bye all.
00:08:20 Ben Tanaka: Bye.
00:08:21 Eli Marsh: See you.
00:08:22 [Recording stopped]
