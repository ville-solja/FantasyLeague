## Documentation

The `markdown/` folder is the single source of truth for product intent. Always consult and keep these three locations up to date:

### markdown/user_stories.md
Canonical list of user stories for the whole project. Before implementing a feature, check whether it is already covered. After implementing, mark it complete and add any new stories that emerged.

### markdown/ui_description/
Short specifications for each UI tab and major component (one file per tab). Describes visible elements, table columns, button behaviours, and conditional states. When a tab changes — new element added, interaction changed, column removed — update the corresponding file. When adding a new tab or major section, create a new file here.

### markdown/feature_description/
In-depth documentation for non-trivial features and mechanics (e.g. card rarity system, weekly roster locking, scoring weights). When implementing a feature with enough complexity to warrant explanation, create or update a file here. The README should link to these rather than duplicate their content.

When a suitably large or complex subject is identified during implementation, ask the user whether a feature description document should be created.

## Readme
The README should stay reasonably sized with links to the markdown documentation. Do not duplicate content that belongs in `markdown/feature_description/`.