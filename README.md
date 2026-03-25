# FantasyLeague

## Description
Idea of a Fantasy league typically is that the participating **Users** are building their dream team (**Roster**) with some limitations and over the season they are tracking the progression of their team and the results between different users **Rosters** are made visible to other **Users** via **Leaderboards**.

Target audience is players and watchers of Kanaliiga, but the design can be made general enough to function league agnostic. 

## Key Features
- Simple login and account management
- Functionality for **User** to obtain **Card** from **Deck**
- Ability for **User** to set **Cards** as their **Roster**
- Leaderboard for both **Player** and **Roster** performances

### Next steps
#### MVP User
1. Create DB table for users
2. populate it with test users

#### MVP Card
1. Create DB table for cards
2. Create json to populate the table

#### FrontEnd proto
Frontend built on simple stack to enable having buttons for rest of the features

#### User creation
1. Field for username
2. Field for password
3. Button for saving the values to User -table

#### Obtaining Card
Button for randomizing from **Deck** and returning the **Card** information. **UserID** needs to be marked in the same transaction so the card is claimed.

## Terminology
#### League
League that the matches take place in. This is the single id that is combining all of the players, teams and matches. It is the initial value that is used to create the database required

Relevant endpoints:
https://docs.opendota.com/#tag/leagues/operation/get_leagues_by_league_id
https://docs.opendota.com/#tag/leagues/operation/get_leagues_by_league_id_select_matches

#### Match
A single played map as part of a tournament. Contains two teams, 10 players and a lot of additional data from the OpenDota API endpoint. Match endpoint also has extremely robust players performance metrics that can be used to determine the fantasy points

Relevant endpoint:
https://docs.opendota.com/#tag/matches/operation/get_matches_by_match_id

#### Weight
Predetermined factor that assigns a weight to each attribute from **Match** to **Player** in order to fairly determine how "valuable" performance metrics are in relation to each other.

#### Fantasy Points
Amount of points accumulated by a **Player** over a single **Match** according to predermined **Weights**

#### Player
Player that has participated in a match that is tied to the current tournament

Endpoint:
https://docs.opendota.com/#tag/players/operation/get_players_by_account_id

#### Team
Team that is taking part in the league and consists of players. Not immediately needed, but should be included to enable future team based metrics and leaderboards

#### User
User of the fantasy league, this is not necessarily limited only to the players as ideally the fantasy league is for watchers as well

#### Card
Player instance that is "owned"/"assigned" to a User that determines their "Roster" for the fantasyleague

#### Deck
Bankend existing containing "cards" in a table. Deck is mostly a documentation reference and card table should be called cards for naming consistency. In initial stages the deck is likely just populated from a json, but later should be automated at the start of season once the players and teams are enrolled to the league.

#### Roster
Active "Cards" that "User" has set that will be determining how they are scoring on the fantasy league. This part is the most UX intensive and hopefully someone more experienced can actually build this.

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