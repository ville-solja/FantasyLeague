# Users and Access

### Registration
**User story**
As a new user, I want to register an account by providing a unique email and username so that I can participate in the fantasy league.

**Acceptance criteria**
- User can register with required credentials
- Registration fails if the username or email is already in use
- After successful registration, the user account is created
- After successful registration, the user receives their initial tokens automatically
- The system records the date and time of registration

---

### Login
**User story**
As a registered user, I want to log in securely so that I can access my cards, team, and leaderboard.

**Acceptance criteria**
- User can log in with valid credentials (username AND password)
- Invalid credentials show an error
- Session persists according to configured authentication rules
- Logged-out users cannot access pages that require authentication

---

### Temporary Password
**User story**
As a user, I want to have the ability to receive a new password in case I've forgotten the current one.

**Acceptance criteria**
- User that does not remember their password has the option to send a temporary password to the email listed on their profile
- If the user does not have an email, an error is given informing them of the inability to reset

---

### Password Reset
**User story**
As a user, once logged in, I want to be able to reset my password.

**Acceptance criteria**
- Profile page has a flow for setting a new password
- Current password is required before a new one is accepted

---

### Logout
**User story**
As a logged-in user, I want to log out so that my account stays secure on shared devices.

**Acceptance criteria**
- User can log out from any page
- Session is invalidated on logout

---

### Admin-only Access
**User story**
As an admin, I want a protected admin area so that only authorized users can manage league configuration and season operations.

**Acceptance criteria**
- Only admin users can access the admin tab
- Non-admin cannot see the admin tab
- Admin status is verified server-side on every admin request — client-side state alone is not sufficient

---

### Profile Tab
**User story**
As a logged-in user, I want a profile page where I can update my account details.

**Acceptance criteria**
- User can change their display username; must remain unique
- User can change their password via a current password + new password form
- User can optionally link their account to an OpenDota player ID
- When a valid player ID is saved and the player exists in league data, the player's name and avatar are shown as a preview

---

### Profile Header Link
**User story**
As a logged-in user, I want to click my username in the header to open my Profile tab so that I can reach profile settings without hunting through the tab strip.

**Acceptance criteria**
- When logged in, the username in the top-right header is rendered as a button, not plain text
- Clicking the username button switches the active tab to Profile
- The button is visually distinct from surrounding text but cohesive with the header style
- When logged out the username button is hidden (no empty button visible)
- After a successful username change, the header button text updates immediately without a page reload
