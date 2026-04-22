# Kanaliiga Stream Overlay — UI Kit

Recreation of the season-14 matchup broadcast layout in HTML, using the same composition as `assets/stream/Dota2 ottelupari striimi layout_s14.png`:

- 1920×1080 fixed canvas, scaled to fit viewport
- Dota 2 dusk-map background + vertical protection gradient
- Top corners: division (left) · format (right)
- Top center: Kanaliiga logo + DOTA 2 badge + SEASON N
- Bottom: signature orange/black hex VS banner with team names and scores
- Bottom-left: caster credit

Use this as a reference for any new overlay scene (idle, BRB, interstitial, standings crawl). Only the **center logo cluster** and **bottom banner** should stay across scenes; corners and caster credit are scene-specific.
