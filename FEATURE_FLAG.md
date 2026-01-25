# Research Chatbot - Feature Flag System

## 🎛️ How It Works

The Research Chatbot is **fully embedded** in your website but controlled by a feature flag. This allows you to:

✅ Test it privately before public launch
✅ Show it to specific people via URL
✅ Enable it for everyone with one line change
✅ No separate deployment needed

## 🔐 Current Status

**Status:** 🔴 DISABLED (Hidden from public)
**Access:** 🔑 Private URL only
**Backend:** ⚠️ Not deployed (requires Vercel setup)

## 🌐 How to Access (Private)

### **Option 1: URL Parameter `research-chat`**
```
https://eugendimant.github.io/?research-chat=true
```

### **Option 2: URL Parameter `chat`** (shorter)
```
https://eugendimant.github.io/?chat=true
```

When you visit with these URLs:
- ✅ Research Chat tab appears in navigation
- ✅ You can select papers and use the chatbot
- ✅ Other visitors don't see it (unless they know the URL)

**Note:** The chatbot UI will work, but without Vercel backend, you'll see an error when sending messages. The error message will guide you to deploy the backend.

## 🚀 How to Enable for Everyone

### **Step 1: Edit index.html**

Find this line (around line 369):
```javascript
const CHATBOT_ENABLED = false;
```

Change to:
```javascript
const CHATBOT_ENABLED = true;
```

### **Step 2: Commit and push**
```bash
git add index.html
git commit -m "Enable Research Chat for all visitors"
git push
```

### **Step 3: Deploy backend** (if not already done)
See `chatbot-archive/CHATBOT_SETUP.md` for Vercel deployment

**That's it!** The Research Chat tab will now appear for everyone.

## 🔄 How to Disable Again

Change back to:
```javascript
const CHATBOT_ENABLED = false;
```

The tab disappears for everyone (except those using the URL parameter).

## 📊 Testing Checklist

Before enabling publicly, test these scenarios:

### **With feature flag DISABLED (current state):**
- [ ] Navigate to site normally → No Research Chat tab
- [ ] Add `?research-chat=true` → Research Chat tab appears
- [ ] Click Research Chat tab → Chat interface loads
- [ ] Select papers → Paper list populates
- [ ] Try sending message → Shows backend error (expected)

### **With feature flag ENABLED (after deploy):**
- [ ] Navigate to site normally → Research Chat tab visible
- [ ] Click Research Chat tab → Chat interface loads
- [ ] Select papers and ask question → Gets AI response
- [ ] Check citations → Papers are referenced
- [ ] Try 21st request in hour → Rate limit message

## 🛠️ Technical Details

### **Feature Flag Implementation**

The system uses a simple JavaScript constant with three-layer control:

**Layer 1: Global Flag**
```javascript
const CHATBOT_ENABLED = false;  // Master switch
```

**Layer 2: URL Parameter Override**
```javascript
const chatbotPrivateAccess =
  urlParams.get('research-chat') === 'true' ||
  urlParams.get('chat') === 'true';
```

**Layer 3: Combined Permission**
```javascript
const SHOW_CHATBOT = CHATBOT_ENABLED || chatbotPrivateAccess;
```

### **Access Control Points**

**Navigation Visibility** (line 375-382):
- Hides nav link on page load if not enabled
- Shows link if URL parameter present

**Section Access** (line 680):
- Blocks direct navigation to chat section
- Returns early if permission denied
- Logs message to console for debugging

**Example Flow:**

```
User visits: https://yoursite.com
  ↓
CHATBOT_ENABLED = false
  ↓
chatbotPrivateAccess = false
  ↓
SHOW_CHATBOT = false
  ↓
Nav link hidden
  ↓
showSection('chat') → Denied
```

```
User visits: https://yoursite.com/?chat=true
  ↓
CHATBOT_ENABLED = false
  ↓
chatbotPrivateAccess = true
  ↓
SHOW_CHATBOT = true
  ↓
Nav link visible
  ↓
showSection('chat') → Allowed
```

## 🎯 Use Cases

### **Scenario 1: Silent Testing**
You want to test the chatbot yourself without showing it to visitors.

**Solution:**
1. Keep `CHATBOT_ENABLED = false`
2. Visit `?research-chat=true`
3. Test functionality
4. No impact on public site

### **Scenario 2: Beta Testers**
You want specific colleagues to test and provide feedback.

**Solution:**
1. Keep `CHATBOT_ENABLED = false`
2. Share URL: `https://yoursite.com/?chat=true`
3. They see the chatbot, others don't
4. Collect feedback privately

### **Scenario 3: Soft Launch**
You want to gradually roll out to a subset of users.

**Solution:**
1. Keep `CHATBOT_ENABLED = false`
2. Share private URL in newsletter to subset
3. Monitor usage and costs
4. Enable globally when confident

### **Scenario 4: Public Launch**
You're ready for everyone to see it.

**Solution:**
1. Change `CHATBOT_ENABLED = true`
2. Commit and push
3. Tab appears for all visitors
4. URL parameter still works (harmless)

### **Scenario 5: Quick Disable**
You discover a bug or cost issue.

**Solution:**
1. Change `CHATBOT_ENABLED = false`
2. Push immediately
3. Chatbot hidden in ~1 minute (CDN cache)
4. Fix issue at your own pace

## 🔒 Security Considerations

**Is the private URL a security risk?**

No, because:
- ✅ Chatbot has rate limiting (20 req/hour)
- ✅ Only works with your papers (no sensitive data)
- ✅ Backend requires Vercel deployment (not live yet)
- ✅ API key never exposed (server-side only)
- ✅ Worst case: Someone uses free research assistant

**If someone finds the URL parameter:**
- They get access to a tool for your public research
- No private data exposed
- Rate limiting prevents abuse
- You can always disable it

**Best practices:**
- Don't advertise the private URL publicly
- Use it for testing and beta access only
- Enable globally when ready for prime time

## 📝 Code Locations

**Feature Flag Definition:**
- File: `index.html`
- Line: ~369
- Section: Top of `<script>` tag

**Navigation Link:**
- File: `index.html`
- Line: ~239
- Section: `<nav>` inside `<header>`

**Access Control:**
- File: `index.html`
- Line: ~680
- Function: `showSection()`

**Chat Section HTML:**
- File: `index.html`
- Line: ~298-352
- Section: `<section id="chat">`

**Chat JavaScript:**
- File: `index.html`
- Line: ~504-623
- Section: Research Chat Functions

## 🚨 Backend Status

**Current:** Backend NOT deployed
**Location:** Code in `chatbot-archive/api/`
**Deploy to:** Vercel (free tier)
**Setup time:** 10 minutes
**Guide:** `chatbot-archive/CHATBOT_SETUP.md`

When you try to send a message before deploying:
```
⚠️ Backend not configured. Please see setup instructions
in CHATBOT_SETUP.md
```

This is expected! Deploy backend when you're ready for actual testing.

## 🎓 Summary

**What you have now:**
- ✅ Fully functional chatbot UI embedded in website
- ✅ Hidden from public by default
- ✅ Accessible via secret URL for private testing
- ✅ One-line change to enable for everyone
- ⚠️ Backend not deployed (shows friendly error)

**What you need to do:**
1. **Test privately:** Visit `?research-chat=true`
2. **Deploy backend:** Follow `CHATBOT_SETUP.md` (when ready)
3. **Enable publicly:** Change flag to `true` (when ready)

**Benefits of this approach:**
- Zero risk of accidental public launch
- Full testing capability before launch
- No code duplication or maintenance
- Easy rollback if needed
- Beta testing without complexity

---

**Last updated:** 2026-01-25
**Feature flag location:** `index.html` line 369
**Private access:** `?research-chat=true` or `?chat=true`
