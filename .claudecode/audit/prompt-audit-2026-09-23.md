# Prompt Audit: website-editing skills (2026-09-23)

## Assumptions

- **Scope.** The request named no files, so the scope is the repo's whole prompt surface. That turned out to be the three Claude Code instruction files in `.claudecode/skills/`:
  - `Website-Editing-Skill.md` (704 lines, the main instructions)
  - `website-editing-skill-for-claude.md` (192 lines, a condensed copy with a trigger description)
  - `website-editing.md` (32 lines, a pointer stub)

  Not in scope:
  - `index.html` only POSTs `{message, papers, conversationId}` to `/api/chat` and builds no prompt text.
  - The chatbot backend (`chatbot-archive/`) is gitignored and not in the repo, so its system prompt couldn't be audited.
  - `features/FEATURE_FLAG.md` is human documentation.
  - No non-Anthropic provider markers were found.
- **Target model.** Neither the request nor the repo names one. The files are read by Claude Code sessions, so the target is the model those sessions currently run: Claude Opus 5.5 (`claude-opus-5-5`). Most findings below don't depend on the model. They are factual claims that stopped matching the code.
- **Provenance.** All three files arrived in one commit (`10631a8`, "Add files via upload", 2026-04-30), so there's no per-line history to show what each rule was written to prevent. Their own footer says "Last updated: January 2026". Since then `index.html` has grown from about 1,270 lines to 2,019, and commit `7805fc3` changed the citation metrics to be computed automatically.

## Summary

| Group | Findings | High | Medium | Low / flag |
|---|---|---|---|---|
| 1a Pressure language | 2 | – | 2 | – |
| 1c Over-specification / padding | 1 | – | 1 | – |
| 2 Brittle skill files (stale facts, history, duplication) | 10 | 7 | 2 | 1 |
| 4 Structure / config | 2 | – | – | 2 |

**The three findings that matter most:**

1. **The required JS syntax check fails on a valid file, and the skill then says to "IMMEDIATELY restore from backup".** The check's regex grabs the text `<script>` inside the HTML comment near `<body>` (index.html:253). It then feeds that comment prose to `new Function` and gets `SyntaxError: Unexpected token ':'`. The real `<script>` block (lines 414–2017) parses cleanly. A session that follows the skill faithfully will undo correct edits. Fix: a check that matches only `<script>` at the start of a line. I tested it: it passes on the current file and catches an injected syntax error.
2. **The skill tells the model to hardcode the citation dashboard values** (`const totalCitations = XXXX; const hIndex = XX; ...`). Those values are now computed from the per-paper `citations` fields (index.html:796–802), and commit `7805fc3` deliberately went back to computing them. Following the instruction would undo that change.
3. **The backup and preview steps don't work in the environment where these skills run.** `backups/` is gitignored, so `git add backups/` fails with `fatal: pathspec 'backups/' did not match any files`, and the backups vanish with the container. The restore command `cp backups/index_$(ls -t backups/ | head -1)` builds a path `backups/index_index_…` that doesn't exist. The preview step sends the user a `localhost:8080` or `file:///home/user/...` link, which they can't open from outside a remote session. Git already provides the backup, and the PR is where the user reviews.

## Findings (ordered by confidence)

### High

| # | Location | Evidence | Pattern | Why it's obsolete | Action |
|---|---|---|---|---|---|
| H1 | `Website-Editing-Skill.md:40`, `:54`, `:577`; `website-editing-skill-for-claude.md:27` | `const m=h.match(/<script[^>]*>([\s\S]*?)<\/script>/g);const c=m[m.length-1]...` + "If any check fails, IMMEDIATELY restore from backup" | 2 – volatile specifics (the check no longer matches the file) | A 2026 HTML comment put the literal `<script>` into the page. The check now fails on a valid file, and the next rule says to roll back. | rewrite: use `[...h.matchAll(/^<script>([\s\S]*?)^<\/script>/gm)]`, and on failure look at `git diff` before restoring |
| H2 | `Website-Editing-Skill.md:245-254` | "Method A: Update dashboard metrics … `const totalCitations = XXXX; const hIndex = XX;`" | 2 – volatile specifics | These values are computed (index.html:797–800). There's no `const hIndex =` to edit, and hardcoding them would reverse `7805fc3`. | rewrite: "computed from per-paper counts; don't hardcode" |
| H3 | `Website-Editing-Skill.md:50-51`, `:397`, `:621-630`, `:694`; `website-editing-skill-for-claude.md:156` | "should be ~1270 lines", "±200 is suspicious", "~1383 ±100", file map with line ranges 1–1270 | 2 – volatile specifics | The file has 2,019 lines, so every line-count check reports a problem that isn't there. The two files also disagree with each other (1270 vs 1383). | rewrite: `git diff --stat` (the size of the change should match the size of the request); keep the file map without line numbers |
| H4 | `Website-Editing-Skill.md:106-117` | Section locator column "Line # (approx)": `~244`, `~351`, `~450` … | 2 – volatile specifics | Actual lines are 436, 703, 1168, and so on. The same table already says to `grep -n`, so the stale numbers are wrong and add nothing. | rewrite: drop the column |
| H5 | `Website-Editing-Skill.md:20-33`, `:389`, `:418-419`, `:580`, `:592-595`, `:682`; `website-editing-skill-for-claude.md:17-22`, `:153`, `:166`, `:184`; `website-editing.md:16,20` | `mkdir -p backups; cp index.html "backups/…"`, `git add backups/`, `cp backups/index_$(ls -t backups/ \| head -1) index.html` | 2 – wrong degrees of freedom / environment facts | `backups/` is in `.gitignore:5`, so `git add backups/` fails, and the backups don't survive a fresh clone or cloud session. The debugging restore command has a doubled `index_` prefix and never works. Git already does this job. | rewrite: "start from a clean working tree; git is the backup", with `git restore` / `git revert` |
| H6 | `Website-Editing-Skill.md:71-74`, `:334-381`; `website-editing-skill-for-claude.md:43`, `:116-128`; `website-editing.md:23` | "Give user URL: `http://localhost:8080` or `file:///home/user/…`", "Only after approval should you commit and push" | 2 – environment facts | The sessions that read these files run in a remote container. The user can't open its localhost or file paths, so the rule "wait for approval" asks for approval the user has no way to give. | rewrite: render and check the console yourself when a headless browser is available, say so when you can't, and treat the PR as the review. Wait for approval only when the user asks to approve first. |
| H7 | `Website-Editing-Skill.md:425`, `:704`; `website-editing.md:10,32`; `website-editing-skill-for-claude.md:58`, `:170`, `:192` | `git push -u origin claude/create-claude-md-rYTH5`; "`/home/user/eugendimant.github.io/Website-Editing-Skill.md`"; "in repository root" | 1d fossil / 2 history (pinned identifiers) | The branch is left over from one earlier session, and a model copying the command would push to it. The skill file isn't at the repo root; it's in `.claudecode/skills/`, so every pointer to it is broken. | rewrite: `<your-branch>`; correct the paths |

### Medium

| # | Location | Evidence | Pattern | Why it's obsolete | Action |
|---|---|---|---|---|---|
| M1 | `Website-Editing-Skill.md:3-18` | "⚠️ CRITICAL RULES", "PRESERVE EVERYTHING", "This is the most important rule", "❌ Previous mistakes to NEVER repeat: …" | 1a pressure + 2 history narrative | The rule itself is a real constraint and stays. The caps and the incident list are wording aimed at older models, and current models follow such wording too literally, which makes them cautious and rigid. The incident list describes what went wrong once instead of stating the rule. | rewrite: state it plainly with the reason ("one ~2,000-line file, so an edit aimed at one section can silently break another") and keep the four concrete practices |
| M2 | `Website-Editing-Skill.md:336`; `website-editing-skill-for-claude.md:9-24`, `:47`, `:118`; `website-editing.md:14-17` | "**IMPORTANT:** … ALWAYS provide a live preview", "ALWAYS BACKUP FIRST", "VALIDATE AFTER EVERY CHANGE", "ALWAYS provide direct PR link" | 1a pressure | When five rules are all marked critical, none of them stands out. Most of these rules are being rewritten anyway (H5, H6). | rewrite at normal volume (in the same hunks). "Include the direct PR link" stays as a plain instruction because it's a real preference. |
| M3 | `Website-Editing-Skill.md:661-672` | "1. Read before writing … 6. Document changes … 9. Ask questions … 10. Double-check" | 1c padding / repeated rules | Every item either repeats Core Rules 1–3 in other words or is something the model does by default. The closing line "When in doubt, preserve. It's better to ask than to accidentally delete." is a deliberate one-line recap, and it stays. | remove the list |
| M4 | All three files | Same rules, schema, and workflow in three places, and they disagree (1270 vs 1383 lines; only one validates `talks`; different preview instructions) | 2 – duplicated content that has drifted | Keep-list item 8 allows working duplication, but these copies now disagree, which is the case where consolidation is warranted. | The diff fixes the facts in each copy. Longer term, keep `Website-Editing-Skill.md` as the one source of truth and cut the other two down to trigger text plus a pointer (not in the diff; see F1 first). |

### Low / flag (no edit proposed)

| # | Location | Note |
|---|---|---|
| F1 | `.claudecode/skills/` | **Structural, outside the audit's scope, but likely the biggest issue.** Claude Code discovers project skills at `.claude/skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`). A `.claudecode/` directory with loose `.md` files isn't auto-loaded. So these files probably only reach the model when someone pastes them or when they're uploaded as the account-level skill (this session lists an `anthropic-skills:website-editing-skill`). Decide which copy is canonical. If it's the repo copy, move it to `.claude/skills/website-editing/SKILL.md` and turn `website-editing-skill-for-claude.md`'s Description/Trigger lines into frontmatter. |
| F2 | `Website-Editing-Skill.md:687-689` | `git reset --hard <commit-hash>` sits in the rollback section with no guard. It's a destructive, precise operation (keep-list item 3), so it should stay as an exact script, but consider adding "only on your own feature branch, never `main`". |
| F3 | `Website-Editing-Skill.md:534-567` | The "80% / 15% / 5%" brainstorming tiers look like strategy coaching. They're kept because they record how the author wants ideas presented, which only the author knows. |
| F4 | `features/FEATURE_FLAG.md` | Not model-facing, but its line references (~369, ~680, ~239) are stale in the same way as H3/H4 (the flag is now near line 253 and later). |
| F5 | chatbot backend | The chatbot's actual system prompt lives in the gitignored `chatbot-archive/` and couldn't be audited. Re-run this audit on it before `CHATBOT_ENABLED` goes to `true`. |

## Proposed diff

`prompt-audit-2026-09-23.patch` (24 hunks, 3 files, +85 / −207). **It hasn't been applied.** Check and apply it with:

```bash
git apply --check .claudecode/audit/prompt-audit-2026-09-23.patch
git apply .claudecode/audit/prompt-audit-2026-09-23.patch
```

Each hunk maps to one finding above, so you can take them separately (`git apply --include` or edit the patch). It contains H1–H7, M1–M3, and the fact fixes from M4. The F items aren't in it.

## Verification done

- New validator: prints `✓ JS syntax valid (1 block)` on the current `index.html`, and raises `SyntaxError` when a stray `{{{` is inserted at line 500.
- Old validator: `SyntaxError: Unexpected token ':'` at `- Currently: DISABLED` on the current, valid file. Reproduced.
- `git add -n backups/` → `fatal: pathspec 'backups/' did not match any files`. Reproduced.
- After applying the patch, no references to `backups/` copies, `1270`, `1383`, `localhost`/`file://` preview links, `rYTH5`, or the wrong root path remain (grep-checked).
- Behavioral check, not run: before and after the patch, have a session add a news item and see whether it (a) finishes without a false rollback and (b) leaves the citation dashboard computed.
