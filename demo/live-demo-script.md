# SnowTech live demo script (2 minutes of the 5-minute pitch)

## Before your slot (2 min)

1. Reset the board: from `~/code/hackathon/civicsignal-deploy`, run `railway restart --service api -y`, then Ctrl+C after ~10 s.
2. Open https://snowtech-phi.vercel.app/replay in Chrome, full screen. Allow the microphone.
3. Turn the laptop volume up. Have the narrated video open offline as a backup.

## Beat 1: the result (25 s)

**Screen:** Storm-week replay.

**Do:** Click **FIFO (oldest first)**, then **SnowTech**.

**Say:** "This is Calgary's real storm week, November 2025, with the same crews for both. Oldest-first reaches 13 percent of high-risk sidewalks within two days. SnowTech reaches 43 percent, and drives 2,848 kilometres instead of 8,652."

## Beat 2: a resident calls (45 s)

**Do:** Click **Live ops**, then **Talk to SnowTech 311**.

**Agent:** "Hi, this is SnowTech… where is it? An intersection or a landmark works."

**You:** "Hi, there's an icy sidewalk by the bus loop at the University of Calgary. A man in a wheelchair can't get through."

**Agent** reads it back.

**You:** "Yes."

**Agent:** "Your report is in… among the higher-priority locations because…", then reads the ticket number.

**Point at the map:** the new ticket pulses near U of C. "It knows the university is near a school, and the wheelchair moves it up. It's in a crew's route within two seconds."

**Agent:** "Anything else?"

**You:** "No, thanks."

**Agent:** says goodbye and hangs up by itself.

## Beat 3: something breaks (25 s)

**Do:** Click **3 crews out**.

**Say:** "Three officers call in sick. SnowTech re-plans every route in about four seconds, moves only the jobs it has to, and keeps the riskiest ice covered."

**Do:** Click **Restore crews**.

## Beat 4: close (10 s)

**Say:** "A language model listens, a solver decides, and every decision comes with its reasons."

## If something goes wrong

| Problem | What to do |
|---|---|
| Agent asks sidewalk, road or pathway | Say "Sidewalk." |
| Agent can't find the location | Say "17 Avenue and 37 Street South-West." |
| Agent asks "Did you mean A or B?" | Pick the one you meant. |
| You need a moment | Say "Give me a second." It waits silently. |
| Mic or call fails | Say "The live line is on our demo video," then play `snowtech-demo-narrated.mp4` from 0:26. |
| Wi-Fi is down | Play the narrated video from the start. It works offline. |
| Map shows old test tickets | Ignore them, or reset the board between teams if you have time. |

## Lines that land with judges

- "Every winter since 2018, half of icy-sidewalk complaints took five to eleven days to close."
- "Same crews: 3.2 times more high-risk sidewalks served in two days, two-thirds fewer kilometres."
- "Base case: about 183 thousand dollars a season, more than the licence costs."
- "Remove the voice and the solver still makes the plan. Voice is just the way in."
