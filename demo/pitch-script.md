# SnowTech: 5-minute pitch script

Keyed to the slides in the pitch deck. The time budget for each slide is in brackets.

## 1. Cover (10 s)

"Hi, we're [team]. This is SnowTech: the right crew to the riskiest ice first."

## 2. Problem (30 s)

"Every winter since 2018, half of Calgary's icy-sidewalk complaints took five to eleven days to close. One in ten took over two weeks. Even quiet weeks have a four-day median, so this isn't one bad storm. It's structural."

## 3. Stakes (25 s)

"Calgary's hospitals see about 1,360 emergency visits a year from falls on ice. In a storm, 400 tickets a day arrive against crews that close about half that. The City says it itself: limited resources mean several days before a first visit."

## 4. Solution (25 s)

"SnowTech does four things. Residents just talk to it. It ranks every spot by who's exposed, using eleven City data layers. It routes crews on Calgary's real roads with Google OR-Tools. And when crews call in sick, it re-plans in about four seconds."

## 5. Architecture (15 s)

"The key design choice: a language model listens, a solver decides. Plans are feasible, repeatable, and every ranking explains itself."

## 6. Results (25 s)

"We replayed Calgary's real November 2025 storm week, with the same crews for every policy. Oldest-first served 13% of high-risk tickets within two days. SnowTech served 43%, 3.2 times as many, while driving 2,848 km instead of 8,652."

## 7. Live demo (1 min 30 s)

Switch to the browser.

1. **Replay:** click FIFO, then SnowTech.
2. **Live ops:** click **Talk to SnowTech 311** and say: *"Hi, there's an icy sidewalk by the bus loop at the University of Calgary. A man in a wheelchair can't get through."* Say **"Yes"** to the read-back.
3. **Point at the map:** "It knows that's near a school, and the wheelchair moves it up. It's in a crew's route in two seconds."
4. Say **"No, thanks."** It hangs up by itself.
5. Click **3 crews out**: "Three officers sick. Every route re-planned in four seconds." Then click **Restore crews**.

## 8. Business (25 s)

"Base case: about $183,000 saved a season, more than the licence costs, plus 819 crew-hours and 40 tonnes of CO₂. There are 103 Canadian cities over 50,000 people."

## 9. Limits (15 s)

"We measured honestly. Triage means low-risk tickets wait longer when crews are short, and a supervisor always approves the plan."

## 10. Ask (15 s)

"Our ask: a pilot in one Calgary district this winter. A language model listens, a solver decides. Thank you."

## Right before you go up

1. Reset the board: from `~/code/hackathon/civicsignal-deploy`, run `railway restart --service api -y`, then Ctrl+C after about 10 s.
2. Have the deck in one tab and https://snowtech-phi.vercel.app/replay in another, with the mic allowed.
3. Have `snowtech-demo-narrated.mp4` ready as the offline backup.

**If the call fails:** "Here's the recorded version." Play the video from 0:26.
