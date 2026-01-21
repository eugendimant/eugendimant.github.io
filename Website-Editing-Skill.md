# Eugen Dimant Website - Claude Code Instructions

## ⚠️ CRITICAL RULES

### 1. PRESERVE EVERYTHING - ONLY MODIFY WHAT'S REQUESTED
**This is the most important rule: ONLY modify what is explicitly requested. Leave all other code exactly as-is.**

❌ **Previous mistakes to NEVER repeat:**
- Accidentally deleting news items while adding papers
- Removing navigation functions while updating talks
- Breaking JavaScript while editing CSS
- Deleting entire sections "by mistake"

✅ **Correct approach:**
- Read the ENTIRE section before editing
- Use precise Edit operations with sufficient context
- Verify the edit only touches the intended lines
- Validate immediately after each change

### 2. ALWAYS BACKUP FIRST
Before ANY edit, create a timestamped backup:
```bash
mkdir -p backups
cp index.html "backups/index_$(date +%Y-%m-%d_%H-%M-%S).html"
ls -t backups/index_*.html | tail -n +4 | xargs -r rm  # Keep last 3
```

**When to backup:**
- Before adding/editing papers
- Before updating citations
- Before modifying news or talks
- Before any structural changes
- Before experimenting with new features

### 3. VALIDATE AFTER EVERY CHANGE
Run these checks immediately after ANY edit:

```bash
# 1. Check JavaScript syntax
node -e "const h=require('fs').readFileSync('index.html','utf8');const m=h.match(/<script[^>]*>([\s\S]*?)<\/script>/g);const c=m[m.length-1].replace(/<script[^>]*>/,'').replace(/<\/script>/,'');new Function(c);console.log('✓ JS syntax valid')"

# 2. Verify required elements exist
grep -q "const papers=\[" index.html && echo "✓ Papers array" || echo "✗ MISSING: Papers array"
grep -q "const newsItems=\[" index.html && echo "✓ News items" || echo "✗ MISSING: News items"
grep -q "const talks=\[" index.html && echo "✓ Talks array" || echo "✗ MISSING: Talks array"
grep -q "function renderNews()" index.html && echo "✓ renderNews function" || echo "✗ MISSING: renderNews"
grep -q "function renderUpcomingTalks()" index.html && echo "✓ renderUpcomingTalks" || echo "✗ MISSING: renderUpcomingTalks"
grep -q "onclick=\"showSection('research')\"" index.html && echo "✓ Navigation" || echo "✗ MISSING: Navigation"

# 3. Check line count (should be ~1270 lines)
wc -l index.html
```

**If any check fails, IMMEDIATELY restore from backup and investigate.**

---

## 📍 Section Locators

Use `grep -n "PATTERN" index.html` to find exact line numbers:

| Section | Pattern | Line # (approx) |
|---------|---------|-----------------|
| Papers array | `const papers=\[` | ~244 |
| News items | `const newsItems=\[` | ~351 |
| Upcoming talks | `const talks=\[` | ~375 |
| Citation dashboard | `function updateCitationDashboard` | ~365 |
| Selected publications | `sortOrder:1` | Various |
| DNA visualization | `function initDNA` | ~450 |
| Navigation | `function showSection` | ~400 |
| Render functions | `function render` | Various |

**Pro tip:** Always use `grep -n` to get current line numbers before editing, as they shift with changes.

---

## 📋 Data Schemas

### Paper Object Schema
```javascript
{
  id: Number,              // Unique ID, increment from highest
  year: Number,            // Publication year
  status: String,          // "published" | "review" | "progress"
  sortOrder: Number,       // OPTIONAL: For "Selected Publications" (1=first, 2=second, etc.)
  title: String,           // Full paper title
  authors: String,         // "Last, First & Last, First & ..." format
  journal: String,         // Full journal name or "Under Review" or "Work in Progress"
  journalShort: String,    // Abbreviated journal name
  topics: Array<String>,   // ["norms", "nudging", "honesty", "polarization", "corruption", "terrorism"]
  method: String,          // "experimental" | "observational" | "methods"
  journalUrl: String,      // DOI or SSRN URL (can be empty "")
  pdfUrl: String,          // Direct PDF link (can be empty "")
  podcastUrl: String,      // OPTIONAL: Podcast/audio link
  citations: Number,       // Citation count (0 if unknown)
  pitch: String,           // 3-5 sentence description of the paper
  bibtex: String          // BibTeX citation entry
}
```

**Example:**
```javascript
{
  id: 9,
  year: 2025,
  status: "published",
  sortOrder: 1,  // This makes it appear in "Selected Publications"
  title: "A National Megastudy Shows That Email Nudges to Elementary School Teachers Boost Student Math Achievement",
  authors: "Duckworth, Angela; Ko, Ahra; Milkman, Katherine; Kay, Joseph; Dimant, Eugen et al.",
  journal: "Proceedings of the National Academy of Sciences (PNAS)",
  journalShort: "PNAS",
  topics: ["norms", "nudging"],
  method: "experimental",
  journalUrl: "https://doi.org/10.1073/pnas.2418616122",
  pdfUrl: "https://drive.google.com/file/d/1b5fPBMT2eOilEqVr1pFjf6_Ytp6NENCx/view",
  podcastUrl: "https://drive.google.com/file/d/12rKoz4vAaE74YL0GNXsLaiLw4AxqdUEO/view",
  citations: 4,
  pitch: "We conduct a megastudy testing 52 different email nudge interventions with over 19,000 U.S. elementary school teachers to improve student math outcomes. The low-cost behavioral interventions include growth mindset messaging, goal-setting prompts, and social norm information delivered via weekly emails. Several nudges significantly boost student math achievement, demonstrating that scalable teacher-focused interventions can improve educational outcomes.",
  bibtex: "@article{duckworth2025national,\n  title={A National Megastudy Shows That Email Nudges to Elementary School Teachers Boost Student Math Achievement},\n  author={Duckworth, Angela L. and Ko, Ahra S. and Milkman, Katherine L. and Kay, Joseph S. and Dimant, Eugen and others},\n  journal={PNAS},\n  volume={122},\n  number={10},\n  pages={e2418616122},\n  year={2025}\n}"
}
```

### News Item Schema
```javascript
{
  date: String,    // "Mon YYYY" format (e.g., "Sep 2025")
  year: Number,    // YYYY
  month: Number,   // 1-12
  type: String,    // "award" | "working" | "publication" | "announcement"
  text: String     // HTML string with <a> tags for links
}
```

**Example:**
```javascript
{
  date: "Sep 2025",
  year: 2025,
  month: 9,
  type: "award",
  text: 'Deeply honored to be included in <a href="https://www.capital.de/..." target="_blank">Capital Magazine\'s</a> German "Top 40 under 40" list.'
}
```

**Note:** News items are filtered to show only the last 12 months. Add new items at the TOP of the array (most recent first).

### Talk Object Schema
```javascript
{
  date: String,       // "Mon YYYY" format
  venue: String,      // Institution or event name
  expireYear: Number, // Year to expire
  expireMonth: Number // Month to expire (1-12)
}
```

**Example:**
```javascript
{
  date: "Jan 2026",
  venue: "ASSA, Philadelphia",
  expireYear: 2026,
  expireMonth: 1
}
```

**Note:** Talks are filtered to show only upcoming ones based on expireYear/expireMonth.

---

## 🛠️ Common Tasks

### Task 1: Add New Paper

**Steps:**
1. **Find highest ID:**
   ```bash
   grep -o "id:[0-9]*" index.html | sed 's/id://' | sort -n | tail -1
   ```

2. **Locate papers array:**
   ```bash
   grep -n "const papers=\[" index.html
   ```

3. **Read the papers section** to understand structure

4. **Add new paper** after `const papers=[` with ID = highest + 1

5. **Validate** using the validation checks above

**Important considerations:**
- Place papers in reverse chronological order (newest first)
- Include `sortOrder` field ONLY for "Selected Publications"
- Ensure commas are correct (trailing comma after last field, comma between objects)
- Escape quotes in strings with backslash: `\"`
- Use `target="_blank"` for all external links

### Task 2: Update Citation Counts

**Method A: Update dashboard metrics**
```bash
grep -n "function updateCitationDashboard" index.html
```
Then edit the function to update:
```javascript
const totalCitations = XXXX;
const hIndex = XX;
const i10Index = XX;
```

**Method B: Update individual paper citations**

⚠️ **Use context to avoid wrong matches!** Don't just search for `citations:OLD`, as this might match multiple papers.

**Safe approach:**
```bash
# Find the exact context around the paper
grep -B2 -A2 "citations:5" index.html
```

Then use Edit tool with sufficient context:
```javascript
old_string: 'title:"Specific Paper Title",authors:"...",journal:"...",journalShort:"...",topics:[...],method:"...",journalUrl:"...",pdfUrl:"...",citations:5,pitch:"'
new_string: 'title:"Specific Paper Title",authors:"...",journal:"...",journalShort:"...",topics:[...],method:"...",journalUrl:"...",pdfUrl:"...",citations:12,pitch:"'
```

### Task 3: Add News Item

**Steps:**
1. Locate news array:
   ```bash
   grep -n "const newsItems=\[" index.html
   ```

2. Add new item at TOP of array (right after `const newsItems=[`)

3. Format:
   ```javascript
   {date:"Mon YYYY",year:YYYY,month:MM,type:"TYPE",text:'HTML text with <a href="URL" target="_blank">links</a>'},
   ```

**News types:**
- `award` - Awards, honors, recognitions
- `working` - New working papers
- `publication` - Published papers
- `announcement` - Events, workshops, announcements

### Task 4: Add Upcoming Talk

**Steps:**
1. Locate talks array:
   ```bash
   grep -n "const talks=\[" index.html
   ```

2. Add new talk in chronological order

3. Format:
   ```javascript
   {date:"Mon YYYY",venue:"Institution Name",expireYear:YYYY,expireMonth:MM},
   ```

**Important:** Set expireYear/expireMonth to when the talk should disappear from the site (typically the month of the talk).

### Task 5: Mark Paper as "Selected Publication"

To feature a paper in the "Selected Publications" section:

1. Find the paper in the array
2. Add `sortOrder: N` field after `status: "published"`
   - `sortOrder: 1` = first selected paper
   - `sortOrder: 2` = second selected paper
   - etc.

**Example:**
```javascript
{
  id: 9,
  year: 2025,
  status: "published",
  sortOrder: 1,  // ← Add this line
  title: "Paper Title",
  // ... rest of fields
}
```

---

## ✅ Pre-Commit Checklist

Before committing ANY changes, verify:

- [ ] **Backup created** in `/backups` folder
- [ ] **JS syntax valid** (no console errors)
- [ ] **Papers array exists** (`const papers=[`)
- [ ] **News items exist** (`const newsItems=[`)
- [ ] **Talks array exists** (`const talks=[`)
- [ ] **renderNews function exists** (`function renderNews()`)
- [ ] **renderUpcomingTalks exists** (`function renderUpcomingTalks()`)
- [ ] **Navigation works** (`onclick="showSection('research')"`)
- [ ] **Line count reasonable** (~1270 lines, ±50 is OK, ±200 is suspicious)
- [ ] **Manual spot check** - Open index.html in browser and verify the changed section looks correct

**If unsure, test locally:**
```bash
# Open in default browser (Linux)
xdg-open index.html

# Or use Python server
python3 -m http.server 8000
# Then visit http://localhost:8000
```

---

## 🚀 Git Workflow

```bash
# Stage changes
git add index.html

# If backups folder has new files, add it too
git add backups/

# Commit with descriptive message
git commit -m "TYPE: Description"

# Push to branch (use -u first time)
git push -u origin claude/create-claude-md-rYTH5
```

**Commit message prefixes:**
- `Add paper:` - New paper(s) added
- `Update citations:` - Citation counts updated
- `Add news:` - New news item(s)
- `Update talks:` - Talks section modified
- `Feature:` - New functionality
- `Fix:` - Bug fix
- `Refactor:` - Code restructuring (rare, be careful!)

**Examples:**
```bash
git commit -m "Add paper: Pluralism Breeds Tolerance (Under Review)"
git commit -m "Update citations: From Google Scholar export"
git commit -m "Add news: Capital Magazine Top 40 Under 40"
git commit -m "Update talks: Add MIT and NYU seminars"
```

---

## 💡 Feature Improvements Framework

When brainstorming new features, present ideas in 3 tiers:

### Standard (80%) - Conventional improvements
Low-risk, proven approaches that are safe to implement:
- Add sorting/filtering options
- Improve mobile responsiveness
- Add loading states
- Enhance accessibility
- Fix browser compatibility issues

### Creative (15%) - Interesting enhancements
Medium-risk, innovative but reasonable:
- Interactive visualizations
- Animated transitions
- Smart search features
- Dynamic content loading
- Integration with external APIs

### Experimental (5%) - Outside-the-box ideas
High-risk/high-reward, bleeding-edge:
- AI-powered paper recommendations
- Real-time collaboration features
- Novel UI paradigms
- Experimental web technologies
- Unconventional layouts

**Process:**
1. Always backup first
2. Create prototype in separate branch if major
3. Validate thoroughly
4. Get user approval before committing
5. Document changes in commit message

---

## 🔍 Debugging Common Issues

### Issue: JavaScript errors after edit
**Solution:**
```bash
# Check syntax
node -e "const h=require('fs').readFileSync('index.html','utf8');const m=h.match(/<script[^>]*>([\s\S]*?)<\/script>/g);const c=m[m.length-1].replace(/<script[^>]*>/,'').replace(/<\/script>/,'');new Function(c);"

# If error, restore from backup
cp backups/index_$(ls -t backups/ | head -1) index.html
```

### Issue: Missing content after edit
**Solution:**
```bash
# Check if section exists
grep "const newsItems" index.html
grep "const talks" index.html
grep "const papers" index.html

# Compare with backup
diff index.html backups/index_$(ls -t backups/ | head -1)

# Restore if needed
cp backups/index_$(ls -t backups/ | head -1) index.html
```

### Issue: Citation count wrong
**Solution:**
```bash
# Find all citations for a specific paper title
grep -A5 -B5 "Paper Title" index.html | grep citations

# Update with context (see Task 2 above)
```

### Issue: New paper not showing
**Solution:**
- Check if `status` field matches filter criteria
- Verify object is inside `const papers=[...]` array
- Check for syntax errors (missing commas, quotes)
- Ensure `year` field is correct
- Run validation checks

---

## 📚 Quick Reference

### File Structure
```
index.html (~1270 lines)
├── Head section (1-50)
├── CSS styles (51-240)
├── Body/HTML structure (241-243)
├── Papers array (244-349)
├── renderNews + newsItems (350-363)
├── updateCitationDashboard (365-373)
├── talks array + renderUpcomingTalks (375-390)
├── Other functions (391-1269)
└── Closing tags (1270)
```

### Field Value Options

**Paper status:**
- `"published"` - Published in journal
- `"review"` - Under review
- `"progress"` - Work in progress

**Paper topics:**
- `"norms"` - Social norms
- `"nudging"` - Nudging interventions
- `"honesty"` - Honesty and dishonesty
- `"polarization"` - Political polarization
- `"corruption"` - Corruption research
- `"terrorism"` - Terrorism studies

**Paper method:**
- `"experimental"` - Lab/field experiments
- `"observational"` - Observational studies
- `"methods"` - Methodological papers

**News type:**
- `"award"` - Awards and honors
- `"working"` - Working papers
- `"publication"` - Publications
- `"announcement"` - General announcements

---

## 🎯 Best Practices

1. **Read before writing** - Always read the section you're editing first
2. **Use context** - Include enough context in Edit operations to ensure uniqueness
3. **Validate immediately** - Run validation checks after each change
4. **Commit frequently** - Small, focused commits are better than large ones
5. **Test locally** - When in doubt, open the file in a browser
6. **Document changes** - Write clear commit messages
7. **Keep backups** - Maintain the last 3 backups at all times
8. **Be conservative** - Only change what's requested
9. **Ask questions** - If unclear, ask before making assumptions
10. **Double-check** - Review your changes before committing

---

## 🆘 Emergency Rollback

If something goes badly wrong:

```bash
# Option 1: Restore from most recent backup
cp "backups/$(ls -t backups/ | head -1)" index.html

# Option 2: Git restore
git restore index.html

# Option 3: Git reset to previous commit
git log --oneline -5  # Find commit hash
git reset --hard <commit-hash>

# Then validate
grep -c "const papers" index.html  # Should be 1
grep -c "const newsItems" index.html  # Should be 1
wc -l index.html  # Should be ~1270
```

---

**Remember: When in doubt, preserve. It's better to ask than to accidentally delete.**

---

*Last updated: January 2026*
*File location: `/home/user/eugendimant.github.io/Website-Editing-Skill.md`*
