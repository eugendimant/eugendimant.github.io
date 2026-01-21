# Website Editing Skill

## Description
Comprehensive instructions for managing and editing eugendimant.github.io website.

## Usage
When the user asks to modify the website (add papers, update citations, modify DNA visualization, etc.), automatically load and follow the instructions from `Website-Editing-Skill.md`.

## Instructions Source
All detailed instructions are in: `/home/user/eugendimant.github.io/Website-Editing-Skill.md`

## Quick Reference

**Critical Rules:**
1. ONLY modify what's requested - preserve everything else
2. ALWAYS backup before edits (keep last 3 in /backups)
3. VALIDATE after every change (JS syntax, required elements)

**Standard Workflow:**
1. Create backup
2. Make changes
3. Validate
4. Provide live preview (python3 -m http.server 8080)
5. Commit with clear message
6. Push to feature branch
7. Create PR for user
8. After merge → GitHub Pages auto-deploys (3-10 min)

**Live Site:** https://eugendimant.github.io
**Deployment Monitor:** https://github.com/eugendimant/eugendimant.github.io/actions

For complete details, schemas, examples, and troubleshooting, read the full `Website-Editing-Skill.md` file.
