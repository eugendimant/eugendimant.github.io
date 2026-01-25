# 🤖 Research Chatbot Feature

## What is this?

An AI-powered chatbot that lets visitors interact with your research papers. Visitors can select papers by topic, ask questions, and get accurate, cited answers powered by OpenAI's GPT-4.

## Key Features

✅ **Smart Paper Selection**
- Browse by topic (Social Norms, Corruption, Polarization, etc.)
- Select single or multiple papers
- Works with all papers that have PDF links

✅ **Intelligent Conversations**
- Ask about methodology, findings, implications
- Compare insights across multiple papers
- Get direct quotes with citations
- Conversation starters for easy engagement

✅ **Anti-Hallucination Design**
- Only answers from selected papers
- Always cites sources
- Says "I don't know" when uncertain
- Low temperature (0.3) for factual responses

✅ **Security & Cost Control**
- API key never exposed to visitors
- Rate limiting: 20 requests/hour per visitor
- ~$0.002 per query (less than 1 cent)
- Free Vercel hosting

## Architecture

```
Frontend (GitHub Pages)
  ├── Chat UI in index.html
  ├── Paper selection sidebar
  └── Message display with citations

Backend (Vercel Serverless)
  ├── /api/chat.js - Main endpoint
  ├── OpenAI GPT-4o-mini integration
  ├── Rate limiting
  └── Anti-hallucination prompt engineering

Security
  ├── API key in Vercel env vars
  ├── CORS headers
  └── Input sanitization
```

## Files Added

```
/api/chat.js              - Serverless function for chat
/vercel.json              - Vercel configuration
/package.json             - Dependencies
/.vercelignore            - Files to exclude from Vercel
/CHATBOT_SETUP.md         - Complete setup guide
/CHATBOT_README.md        - This file
```

## Files Modified

```
/index.html
  ├── Added "Research Chat" navigation link
  ├── Added chat section HTML
  ├── Added chat CSS styles
  └── Added chat JavaScript functions
```

## Quick Start

1. **Read the setup guide:** [CHATBOT_SETUP.md](./CHATBOT_SETUP.md)
2. **Get OpenAI API key:** https://platform.openai.com/api-keys
3. **Deploy to Vercel:** Connect GitHub repo
4. **Add API key:** In Vercel dashboard → Environment Variables
5. **Test:** Visit your site → Research Chat tab

## Cost Breakdown

**Monthly costs for typical academic website:**

| Traffic Level | Queries/Month | OpenAI Cost | Vercel Cost | Total |
|--------------|---------------|-------------|-------------|-------|
| Low          | 100           | $0.20       | Free        | $0.20 |
| Medium       | 500           | $1.00       | Free        | $1.00 |
| High         | 1,000         | $2.00       | Free        | $2.00 |
| Very High    | 5,000         | $10.00      | Free        | $10.00|

**Vercel free tier limits:**
- 100 GB bandwidth/month
- 100 serverless executions/day
- Unlimited static hosting

For academic sites, you'll stay within free limits.

## Example Interactions

**User:** "What are the main findings about corruption in these papers?"

**AI:** "Based on the selected papers, here are the key findings about corruption:

In 'Contagion of Rule-Breaking Behavior' [Dimant et al., 2020], the research found that exposure to others' corrupt behavior increases one's own likelihood of engaging in similar misconduct...

In 'The Nature of Corruption' [Dimant et al., 2018], the authors identify that corruption spreads through social networks and is influenced by normative beliefs..."

[Citations displayed with paper titles and years]

## Limitations

❌ **Does NOT:**
- Read full PDF text (uses abstracts/metadata only)*
- Access papers without PDF URLs
- Generate new research (only analyzes existing)
- Remember conversations across browser sessions
- Work offline

*Full PDF extraction can be added - see CHATBOT_SETUP.md "Advanced" section

## Privacy & Data

- No user data is stored permanently
- Conversations are not saved (session-only)
- OpenAI processes queries per their privacy policy
- Rate limiting uses IP addresses (not stored long-term)
- No tracking or analytics beyond standard Vercel logs

## Technical Details

**Frontend:**
- Pure JavaScript (no framework required)
- Matches existing site aesthetic
- Responsive design (mobile-friendly)
- Auto-resizing textarea
- Loading states and error handling

**Backend:**
- Node.js 18+ runtime
- OpenAI API v1
- GPT-4o-mini model (cost-effective)
- Serverless architecture (scales automatically)
- Edge function deployment

**Prompt Engineering:**
- System prompt enforces paper-only responses
- Temperature: 0.3 (factual over creative)
- Max tokens: 1,500 (medium-length responses)
- Presence penalty: 0.1 (reduces repetition)

## Customization Options

See `CHATBOT_SETUP.md` for details on:
- Changing AI model (gpt-4o for better quality)
- Adjusting response length
- Modifying system prompt
- Adding authentication
- Enabling full PDF text extraction
- Setting up vector database for better search

## Removal Instructions

Don't like it? Easy to remove:

1. Delete navigation link (1 line)
2. Delete chat section (50 lines)
3. Delete chat CSS (70 lines)
4. Delete chat JS (100 lines)
5. Delete `/api` folder
6. Delete config files (vercel.json, package.json)

Site works exactly as before.

## Future Enhancements

Possible additions (require dev work):

- [ ] Full PDF text extraction
- [ ] Vector database (semantic search)
- [ ] Conversation persistence
- [ ] Export chat transcripts
- [ ] Multi-language support
- [ ] Voice input/output
- [ ] Paper recommendations
- [ ] Integration with citation metrics

## Support & Issues

- **Setup problems?** See CHATBOT_SETUP.md troubleshooting section
- **Bugs?** Check browser console (F12) and Vercel logs
- **Feature requests?** Document in GitHub Issues

## License

Same as main website. For academic/personal use.

---

Built with ❤️ using OpenAI GPT-4, Vercel, and vanilla JavaScript.
