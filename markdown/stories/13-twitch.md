# 13. Twitch Integration

### 13.1 Twitch Integration — MVP Selection and Token Drop
**User story**
As a streamer I want to select the MVP of a match, which also rewards viewers watching the stream.

**Acceptance criteria**
- After a match has ended the streamer presses the quick action button on Twitch to open MVP selection
- The most recent matches (ongoing and ended) in the system are listed with start time and teams. Streamer makes the selection out of these matches.
- Streamer is shown the list of 10 players who participated in the match
- Streamer selects one of the players who participated in the match and confirms
- Confirming the MVP saves the selection and automatically drops tokens to viewers in the presence pool (once per match — re-confirming a different MVP does not re-drop)
- The number of viewers rewarded is capped server-side by `TWITCH_DROP_MAX`
- The broadcaster sees a confirmation showing the MVP name and which viewers received tokens

---

### 13.2 Twitch Integration — Viewer Token Eligibility
**User story**
As a viewer I want to be eligible for token drops while watching the Kanaliiga stream.

**Acceptance criteria**
- Viewers who have linked their Fantasy account and have the Twitch extension panel open are in the drop pool
- Presence in the pool is maintained automatically while the panel is open (heartbeat every ~55 seconds)
- Viewers not in the pool at the time of the MVP confirmation do not receive a token for that match

---

### 13.3 Twitch Integration — Account Linking
**User story**
As a user of fantasy league I want to link my twitch profile in fantasy league so I am eligible for drops while watching stream.

**Acceptance criteria**
- User can navigate to their profile and start process for linking their Twitch account
- Account linking is done in Twitch recommended fashion that is safe and does not create attack surface against twitch accounts from the fantasy league
- Safety of linking accounts is documented

---

### 13.4 Twitch Integration — Extension
**User story**
As a streamer I want to take FantasyLeague twitch extension into use so I can use extension features that interact with app. I additionally want the buttons and flow to be on quick actions, so they are not conflicting with any other elements.

**Acceptance criteria**
- Streamer is able to take the extension into use with instructions documented in fantasy league app
- Extension buttons are visible in the quick actions
