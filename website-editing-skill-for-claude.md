# website-editing

**Description:** Comprehensive instructions for managing and editing eugendimant.github.io website. Use when user requests website modifications, paper additions, citation updates, or DNA visualization changes.

**Trigger:** When user asks to modify website, add papers, update citations, edit news/talks, or enhance features.

---

## Critical Rules

**PRESERVE EVERYTHING - ONLY MODIFY WHAT'S REQUESTED**
- Read entire section before editing
- Use precise Edit operations with sufficient context
- Never delete unrelated code
- Validate immediately after changes

**ALWAYS BACKUP FIRST**
```bash
mkdir -p backups
cp index.html "backups/index_$(date +%Y-%m-%d_%H-%M-%S).html"
ls -t backups/index_*.html | tail -n +4 | xargs -r rm
```

**VALIDATE AFTER EVERY CHANGE**
```bash
# JS syntax check
node -e "const h=require('fs').readFileSync('index.html','utf8');const m=h.match(/<script[^>]*>([\s\S]*?)<\/script>/g);const c=m[m.length-1].replace(/<script[^>]*>/,'').replace(/<\/script>/,'');new Function(c);console.log('✓ JS valid')"

# Verify required elements
grep -q "const papers=\[" index.html && echo "✓ Papers" || echo "✗ MISSING"
grep -q "const newsItems=\[" index.html && echo "✓ News" || echo "✗ MISSING"
grep -q "function renderNews()" index.html && echo "✓ Functions" || echo "✗ MISSING"
```

---

## Standard Workflow

1. **Create backup** before any edit
2. **Read section** to understand structure
3. **Make changes** with precise edits
4. **Validate** JS syntax and elements
5. **Provide preview** - Start server: `python3 -m http.server 8080 &`
6. **Commit** with clear message
7. **Push** to feature branch (format: `claude/feature-name-XXXXX`)
8. **Create PR** for user review
9. **After merge** → GitHub Pages auto-deploys (3-10 min)

---

## File Locations

- **Website:** https://eugendimant.github.io
- **Repository:** /home/user/eugendimant.github.io/index.html
- **Full docs:** /home/user/eugendimant.github.io/Website-Editing-Skill.md
- **Deployments:** https://github.com/eugendimant/eugendimant.github.io/actions

---

## Paper Schema

```javascript
{
  id: Number,              // Unique, increment from highest
  year: Number,            // Publication year
  status: "published"|"review"|"progress",
  sortOrder: Number,       // OPTIONAL: For "Selected Publications"
  title: String,
  authors: String,         // "Last, First & Last, First"
  journal: String,
  journalShort: String,
  topics: ["norms","nudging","honesty","polarization","corruption","terrorism"],
  method: "experimental"|"observational"|"methods",
  journalUrl: String,
  pdfUrl: String,
  podcastUrl: String,      // OPTIONAL
  citations: Number,
  pitch: String,           // 3-5 sentence description
  bibtex: String
}
```

---

## Common Tasks

### Add Paper
1. Find highest ID: `grep -o "id:[0-9]*" index.html | sed 's/id://' | sort -n | tail -1`
2. Locate papers array: `grep -n "const papers=\[" index.html`
3. Read papers section to understand structure
4. Add new paper with ID = highest + 1
5. Validate and commit

### Update Citations
1. Locate paper with context to avoid wrong matches
2. Use Edit with sufficient surrounding context
3. Update citation count
4. Validate

### Add News Item
Add at TOP of newsItems array (most recent first):
```javascript
{date:"Mon YYYY",year:YYYY,month:MM,type:"award"|"working"|"publication"|"announcement",text:'HTML with <a> tags'}
```

### Add Talk
```javascript
{date:"Mon YYYY",venue:"Institution",expireYear:YYYY,expireMonth:MM}
```

---

## Preview Workflow

**ALWAYS provide preview before committing:**
```bash
python3 -m http.server 8080 &
```
User can access at: `file:///home/user/eugendimant.github.io/index.html`

**Tell user to test:**
- Navigation works
- New features function properly
- No console errors
- Existing features still work

---

## Deployment Process

After user merges PR:
- GitHub Pages auto-detects merge to `main`
- Builds and deploys automatically (3-10 minutes)
- No manual steps needed

**Tell user:**
```
✅ Changes merged!
Monitor: https://github.com/eugendimant/eugendimant.github.io/actions
Timeline: 3-10 minutes
Live site: https://eugendimant.github.io
Hard refresh: Ctrl+F5 (Windows) or Cmd+Shift+R (Mac)
```

---

## Validation Checklist

Before commit:
- [ ] Backup created in /backups
- [ ] JS syntax valid
- [ ] All required elements exist
- [ ] Line count reasonable (~1383 ±100)
- [ ] Preview tested
- [ ] Clear commit message

---

## Git Commands

```bash
# Commit
git add index.html backups/
git commit -m "TYPE: Description"

# Push
git push -u origin claude/feature-name-XXXXX

# Create PR
https://github.com/eugendimant/eugendimant.github.io/pull/new/BRANCH
```

**Commit prefixes:** `Add paper:`, `Update citations:`, `Add news:`, `Update talks:`, `Feature:`, `Fix:`

---

## Emergency Rollback

```bash
# Restore from backup
cp "backups/$(ls -t backups/ | head -1)" index.html

# Or git restore
git restore index.html
```

---

**Full documentation:** Read `Website-Editing-Skill.md` in repository root for complete schemas, examples, debugging, and advanced workflows.
