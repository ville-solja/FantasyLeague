# FantasyLeague

## Description
Target audience is players and watchers of Kanaliiga, but the design can be made general enough to function league agnostic.

## Key Features
- Simple login and account management
- Functionality to get "player cards"
- Ability to set player cards as your fantasy team
- Leaderboards and visibility

## Terminology
### League
League that the matches take place in. This is the single id that is combining all of the players, teams and matches. It is the initial value that is used to create the database required
### Match
A single played map as part of a tournament. Contains two teams, 10 players and a lot of additional data from the OpenDota API endpoint
### Team
Team that is taking part in the league and consists of players. Not immediately needed, but should be included to enable future team based metrics and leaderboards
### Player
Player that has participated in a match that is tied to the current tournament
### User
User of the fantasy league, this is not necessarily limited only to the players as ideally the fantasy league is for watchers as well
### Card
Player instance that is "owned"/"assigned" to a User that determines their "Roster" for the fantasyleague
### Deck
Bankend existing containing "cards" in a table. Deck is mostly a documentation reference and card table should be called cards for naming consistency
### Roster
Active "Cards" that "User" has set that will be determining how they are scoring on the fantasy league

## Architecture
### Phase 1 - MVP 
Version of the app should be easy to host and manage, and likely will be contained in single container

#### Ingestion
With just the tournament id the postgresql in populated with the matches, players, teams and the results

#### Steps
Ingestion of league data -> Storage in PostgreSQL -> Visualization of the leaderboard data in a website

### Phase 2 - Stability
Postgresql should be hosted outside of the container in order to enable permanence in the data. This should be done to make the user experience and long term traceablitiy doable.

### Phase 3 - Separation
Ingestion and other backend scripts should be separated entirely from the frontend