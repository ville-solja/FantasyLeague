# Technical Writer

The `/technical-writer` slash command rewrites a piece of project documentation so it states its core message clearly and concisely for the people who read it. Maintainers run it on a file, a section, or a documentation area.

---

## How it works

1. **Resolve** the target: a path, `path#heading`, or a short description. With no argument, or a target that matches no file, it asks.
2. **Name the audience** from the file's location and content, what they need first, and the document's core message. If that is unclear or there are several audiences, it asks with options to choose from.
3. **Draft** a rewrite that leads with the core message and keeps every name, value, path and command exact.
4. **Propose** the draft with word counts and a list of any facts removed or moved. Nothing is written until the maintainer chooses: apply, apply with exclusions, or discard. Structural changes, such as deleting a section or moving content to another file, are offered as separate choices.
5. **Apply** only the approved changes, and keep `markdown/features/README.md` and `markdown/stories/_index.md` in sync.

It improves how docs read. Whether docs match the code is checked by `/documentation-steward`.

## Usage

```
/technical-writer markdown/features/reference/security-audit-3.md
/technical-writer README.md#Deployment
/technical-writer hoster deploy notes
```

## Default audiences

| Location | Audience |
|---|---|
| `README.md` (top) | New contributors |
| `README.md` Deployment, `.env.example` | Hoster / operator |
| `markdown/features/core/` | Developers, product owner |
| `markdown/features/reference/` | Developers, operators |
| `markdown/stories/` | Product owner, developers |
| `markdown/ui_description/` | Developers, UI designers |
| `markdown/plans/` | Developer implementing the plan |
| `.claude/commands/` | The agent itself |

The agent definition is `.claude/commands/technical-writer.md`. It reads `markdown/lessons-learned.md` before each run and appends an entry for any novel documentation pitfall.
