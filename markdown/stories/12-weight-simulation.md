# 12. Weight Simulation

### 12.1 Weight Calculation
**User Story**
As admin I want to provide a weight for statistics experts to simulate the values and set the values for the season.

**Acceptance criteria**
- Separate endpoint is created outside of the league navigation
- Endpoint is given the matchID
- Endpoint can receive each scoring stat and value that differs from the default
- Returning value is a simple table containing the players and their fantasy point values from the given match, with the provided scoring modifiers

---

### 12.2 Weight Statistics
**User Story**
As statistician, I want to have documentation about the weight simulation endpoint, so I can build my own tooling to systematically gather data.

**Acceptance criteria**
- Documentation about the endpoint functionality is available to users
