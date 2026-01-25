/**
 * Research Chatbot API Endpoint
 * This serverless function handles chat requests using OpenAI's API
 * with RAG (Retrieval-Augmented Generation) for accurate, cited responses
 */

// Rate limiting store (in-memory, resets on function cold start)
const rateLimitStore = new Map();
const RATE_LIMIT = 20; // requests per hour per IP
const RATE_WINDOW = 60 * 60 * 1000; // 1 hour in milliseconds

export default async function handler(req, res) {
  // CORS headers
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS,PATCH,DELETE,POST,PUT');
  res.setHeader('Access-Control-Allow-Headers', 'X-CSRF-Token, X-Requested-With, Accept, Accept-Version, Content-Length, Content-MD5, Content-Type, Date, X-Api-Version');

  // Handle OPTIONS request
  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  // Only allow POST
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    // Rate limiting
    const clientIP = req.headers['x-forwarded-for'] || req.connection.remoteAddress;
    const now = Date.now();
    const clientRequests = rateLimitStore.get(clientIP) || [];

    // Remove old requests outside the window
    const recentRequests = clientRequests.filter(time => now - time < RATE_WINDOW);

    if (recentRequests.length >= RATE_LIMIT) {
      return res.status(429).json({
        error: 'Rate limit exceeded. Please try again later.',
        retryAfter: Math.ceil((recentRequests[0] + RATE_WINDOW - now) / 1000)
      });
    }

    // Add current request
    recentRequests.push(now);
    rateLimitStore.set(clientIP, recentRequests);

    // Validate API key
    const apiKey = process.env.OPENAI_API_KEY;
    if (!apiKey) {
      return res.status(500).json({
        error: 'Server configuration error: OpenAI API key not set',
        setup: 'Please add OPENAI_API_KEY to your Vercel environment variables'
      });
    }

    // Parse request
    const { message, papers, conversationId } = req.body;

    if (!message || typeof message !== 'string') {
      return res.status(400).json({ error: 'Invalid message' });
    }

    if (!papers || !Array.isArray(papers) || papers.length === 0) {
      return res.status(400).json({ error: 'No papers selected' });
    }

    // Sanitize input
    const sanitizedMessage = message.trim().substring(0, 1000);

    // Build context from papers
    const paperContext = papers.map(p => {
      return `
Paper ID: ${p.id}
Title: "${p.title}" (${p.year})
Authors: ${p.authors}
Abstract: ${p.abstract}
Topics: ${p.topics?.join(', ') || 'N/A'}
---`;
    }).join('\n');

    // Build system prompt with anti-hallucination measures
    const systemPrompt = `You are a research assistant for Professor Eugen Dimant's academic portfolio. Your role is to help visitors understand his research papers by providing accurate, cited answers.

CRITICAL RULES:
1. ONLY use information from the provided papers below
2. ALWAYS cite which paper(s) you're referencing
3. If information isn't in the papers, say "I don't have information about that in the selected papers"
4. Never make up or infer information not explicitly stated
5. Provide direct quotes when possible
6. Be concise but thorough
7. If asked to compare papers, explicitly reference each one

AVAILABLE PAPERS:
${paperContext}

When citing, use the format: [Paper Title, Year]
When quoting, use quotation marks and specify the paper.`;

    // Call OpenAI API
    const response = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        model: 'gpt-4o-mini', // Using gpt-4o-mini for cost-effectiveness
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: sanitizedMessage }
        ],
        temperature: 0.3, // Lower temperature for more factual responses
        max_tokens: 1500,
        presence_penalty: 0.1,
        frequency_penalty: 0.1
      })
    });

    if (!response.ok) {
      const error = await response.json();
      console.error('OpenAI API error:', error);
      return res.status(response.status).json({
        error: 'OpenAI API error',
        details: error.error?.message || 'Unknown error'
      });
    }

    const data = await response.json();
    const assistantMessage = data.choices[0]?.message?.content || 'No response generated';

    // Extract citations (simple pattern matching)
    const citationPattern = /\[([^\]]+),\s*(\d{4})\]/g;
    const citations = [];
    let match;

    while ((match = citationPattern.exec(assistantMessage)) !== null) {
      const [_, paperTitle, year] = match;
      const paper = papers.find(p =>
        p.title.includes(paperTitle) || paperTitle.includes(p.title.substring(0, 30))
      );

      if (paper) {
        citations.push({
          paper: `${paper.title} (${paper.year})`,
          quote: `Referenced in response`
        });
      }
    }

    // Generate conversation ID if not provided
    const newConversationId = conversationId || `conv-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    // Log usage (optional, for monitoring)
    console.log('Chat request:', {
      conversationId: newConversationId,
      papersCount: papers.length,
      messageLength: sanitizedMessage.length,
      tokensUsed: data.usage?.total_tokens || 0
    });

    // Return response
    return res.status(200).json({
      response: assistantMessage,
      citations: citations.length > 0 ? citations : null,
      conversationId: newConversationId,
      usage: {
        tokens: data.usage?.total_tokens || 0,
        papersAnalyzed: papers.length
      }
    });

  } catch (error) {
    console.error('Chat API error:', error);
    return res.status(500).json({
      error: 'Internal server error',
      message: error.message
    });
  }
}
