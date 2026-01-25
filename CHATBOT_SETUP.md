# Research Chatbot Setup Guide

This guide will help you deploy the AI-powered research chatbot to your website using Vercel serverless functions.

## Overview

The chatbot allows visitors to:
- Select one or multiple papers from your portfolio
- Ask questions about methodology, findings, and implications
- Get accurate, cited answers powered by GPT-4
- Compare insights across multiple papers

**Security:** Your OpenAI API key is securely stored as an environment variable on Vercel's servers and never exposed to visitors.

## Prerequisites

1. **OpenAI API Key**
   - Go to https://platform.openai.com/api-keys
   - Create a new API key
   - Keep it safe - you'll need it in step 3

2. **Vercel Account** (Free)
   - Go to https://vercel.com
   - Sign up with your GitHub account
   - No credit card required for free tier

## Step-by-Step Deployment

### Step 1: Install Vercel CLI (Optional but Recommended)

```bash
npm install -g vercel
```

Or use the Vercel web dashboard (easier for first-time setup).

### Step 2: Connect Your GitHub Repository to Vercel

**Via Vercel Dashboard (Easiest):**

1. Go to https://vercel.com/new
2. Click "Import Git Repository"
3. Select your `eugendimant.github.io` repository
4. Click "Import"
5. Leave default settings (Framework Preset: Other)
6. **DO NOT deploy yet** - we need to add the API key first

### Step 3: Add OpenAI API Key as Environment Variable

**In Vercel Dashboard:**

1. Go to your project settings
2. Click "Environment Variables" in the sidebar
3. Add a new variable:
   - **Name:** `OPENAI_API_KEY`
   - **Value:** Your OpenAI API key (starts with `sk-...`)
   - **Environment:** Select all (Production, Preview, Development)
4. Click "Save"

**Via Vercel CLI:**

```bash
cd /path/to/eugendimant.github.io
vercel env add OPENAI_API_KEY
# Paste your API key when prompted
```

### Step 4: Deploy to Vercel

**Via Dashboard:**
- Click "Deploy" button

**Via CLI:**
```bash
vercel --prod
```

### Step 5: Update Your Site Configuration

Once deployed, Vercel will give you two URLs:
- **Production:** `https://eugendimant.vercel.app` (or your custom domain)
- **GitHub Pages:** `https://eugendimant.github.io` (your current site)

You have two options:

#### Option A: Keep Both Sites (Recommended for Testing)
1. Keep GitHub Pages as your main site
2. Use Vercel for the chatbot functionality
3. Update the API endpoint in `index.html`:

```javascript
// In the sendChatMessage function, change:
const response = await fetch('/api/chat', {
// To:
const response = await fetch('https://eugendimant.vercel.app/api/chat', {
```

#### Option B: Move Everything to Vercel
1. Point your domain to Vercel
2. Vercel will serve both the static site AND the chatbot backend
3. No changes needed - `/api/chat` will work automatically

### Step 6: Test the Chatbot

1. Go to your site → Research Chat tab
2. Select one or more papers
3. Try asking: "What are the main findings?"
4. You should get a response within 3-5 seconds

## Cost Estimation

**OpenAI API Costs (GPT-4o-mini):**
- Input: $0.150 per 1M tokens
- Output: $0.600 per 1M tokens
- Average query: ~2,000 tokens
- **Cost per query: ~$0.002** (less than half a cent)

**Realistic monthly costs for your site:**
- 100 queries/month: ~$0.20
- 500 queries/month: ~$1.00
- 1,000 queries/month: ~$2.00

**Vercel Costs:**
- Free tier: 100 GB bandwidth, 100 serverless invocations per day
- Your chatbot: **FREE** (well within limits)

## Features & Capabilities

### What the Chatbot CAN Do:
✅ Answer questions about selected papers
✅ Compare findings across multiple papers
✅ Explain methodology and results
✅ Provide direct quotes and citations
✅ Discuss policy implications
✅ Work with 1-47 papers simultaneously

### What It CANNOT Do:
❌ Access papers without PDFs (only uses papers with pdfUrl)
❌ Answer questions outside your research
❌ Generate new research ideas (only analyzes existing work)
❌ Read full PDFs (uses abstracts and metadata)

**Note:** Currently, the system uses paper metadata (title, abstract, authors) rather than full PDF text. To enable full PDF processing, see "Advanced: PDF Text Extraction" below.

## Anti-Hallucination Measures

The chatbot includes several safeguards:

1. **Strict System Prompt:** Instructs GPT to only use provided information
2. **Low Temperature:** 0.3 (more factual, less creative)
3. **Citation Requirements:** Must cite sources
4. **Error Handling:** Shows "I don't know" instead of guessing
5. **Rate Limiting:** 20 requests/hour per visitor (prevents abuse)

## Monitoring & Usage

### View Logs in Vercel:
1. Go to your Vercel project
2. Click "Logs" tab
3. See all chat requests, token usage, errors

### Monitor OpenAI Costs:
1. Go to https://platform.openai.com/usage
2. View detailed usage by day
3. Set monthly spending limits

### Rate Limiting:
- **Default:** 20 requests per hour per visitor
- **Adjust:** Edit `RATE_LIMIT` constant in `/api/chat.js`
- **Purpose:** Prevents API abuse and runaway costs

## Troubleshooting

### Error: "Backend not configured"
- **Cause:** Vercel not deployed or API endpoint unreachable
- **Fix:** Ensure Vercel deployment succeeded, check URL in fetch()

### Error: "OpenAI API key not set"
- **Cause:** Environment variable not configured
- **Fix:** Add OPENAI_API_KEY in Vercel dashboard → Settings → Environment Variables

### Error: "Rate limit exceeded"
- **Cause:** Too many requests from same visitor
- **Fix:** Wait 1 hour or adjust RATE_LIMIT in api/chat.js

### Chatbot gives generic answers:
- **Cause:** Not enough context in paper abstracts
- **Fix:** See "Advanced: PDF Text Extraction" below

### High API costs:
- **Check:** Vercel logs for unusual traffic
- **Solution:** Add stricter rate limiting or require authentication

## Advanced: PDF Text Extraction (Optional)

To enable full PDF text analysis:

1. **Install Dependencies:**
```bash
cd api
npm init -y
npm install pdf-parse node-fetch
```

2. **Create PDF Parser:**
Create `/api/parse-pdf.js`:
```javascript
import fetch from 'node-fetch';
import pdf from 'pdf-parse';

export default async function handler(req, res) {
  const { pdfUrl } = req.body;

  try {
    const response = await fetch(pdfUrl);
    const buffer = await response.buffer();
    const data = await pdf(buffer);

    return res.json({ text: data.text });
  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
}
```

3. **Update chat.js** to call parse-pdf endpoint first

**Cost implications:**
- Parsing PDFs adds ~20-30 seconds per paper
- Increases token usage 10-20x (full text vs abstracts)
- Consider caching parsed PDFs in a database

## Customization

### Change AI Model:
In `/api/chat.js`, line 98:
```javascript
model: 'gpt-4o-mini', // Change to 'gpt-4o' for better quality (10x cost)
```

### Adjust Response Length:
Line 105:
```javascript
max_tokens: 1500, // Increase for longer responses
```

### Modify System Prompt:
Lines 80-96: Customize how the AI behaves

### Add Authentication:
See Vercel's Edge Middleware docs for password protection

## Security Best Practices

✅ **DO:**
- Keep API keys in environment variables only
- Enable rate limiting (already implemented)
- Monitor usage regularly
- Set OpenAI spending limits
- Use HTTPS (automatic with Vercel)

❌ **DON'T:**
- Commit API keys to GitHub
- Share Vercel project access publicly
- Disable rate limiting without authentication
- Use gpt-4o model without cost monitoring

## Support

If you encounter issues:

1. **Check Vercel Logs:** Project → Logs tab
2. **Check OpenAI Status:** https://status.openai.com
3. **Check Browser Console:** F12 → Console tab (for frontend errors)
4. **GitHub Issues:** Create an issue in your repo with error messages

## Future Enhancements

Possible additions (require additional development):

- [ ] Full PDF text extraction and chunking
- [ ] Vector database (Pinecone/Weaviate) for semantic search
- [ ] Conversation memory across sessions
- [ ] Export chat transcripts
- [ ] Paper recommendation based on questions
- [ ] Multi-language support
- [ ] Voice input/output
- [ ] Integration with Google Scholar for latest citations

## Removing the Chatbot

If you want to remove the feature:

1. Delete the "Research Chat" nav link in `index.html` (line ~174)
2. Delete the `<section id="chat">` block (after line ~231)
3. Delete all chat CSS (lines ~171-240 in `<style>`)
4. Delete chat JavaScript functions (lines ~504-600)
5. Delete `/api` folder
6. Delete `vercel.json`
7. Delete this file (`CHATBOT_SETUP.md`)

Your site will work exactly as before.

---

**Questions?** Feel free to review the code or modify as needed. The system is designed to be self-contained and easy to remove if it doesn't meet your needs.
