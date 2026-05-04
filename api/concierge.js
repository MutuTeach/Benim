/**
 * /api/concierge — proxy to Anthropic Messages API.
 */

export const config = { runtime: "edge" };

const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION = "2023-06-01";
const MODEL = "claude-sonnet-4-5";
const MAX_TOKENS = 1024;
const UPSTREAM_TIMEOUT_MS = 30_000;
const MAX_MESSAGES = 50;
const MAX_MESSAGE_CHARS = 4_000;

const RATE_LIMIT_MAX = 20;
const RATE_LIMIT_WINDOW_MS = 60_000;
const ipBuckets = new Map();

const BASE_PROMPT = `You are the AI Concierge for Umut Şimşek's professional portfolio website.

ABOUT UMUT:
- Business Development Manager specialized in Forex/CFD partner networks (IBs)
- 6+ years experience, 100+ IBs managed
- Currently: BD Manager at Weltrade (2025)
- Previously: Team Lead Retention LATAM at TM Group (2022-2024); Retention Account Manager at Lavixo (2019-2022)
- Active regions: LATAM, MENA, Europe
- Languages: Spanish, English, Turkish, Portuguese — all fluent
- Specialties: IB prospecting & onboarding, FTD growth strategies, retention, low-risk activation campaigns (challenges, tournaments), AI marketing (creative, social content), KPI monitoring & inactive trader reactivation, regional strategy adaptation, webinars & events for partners
- Stack: MT4 / MT5, CRM systems
- Calendly (free 30-min call): https://calendly.com/simsekk-umut/30min

LANGUAGE BEHAVIOR:
- Default to Spanish (his primary site language)
- Detect from the user's message and match: Spanish, English, Portuguese, Turkish
- Tone: professional, warm but direct. No fluff. No corporate filler.
- Don't say "as an AI" or apologize for being an assistant.`;

const PROMPTS = {
  chat:
    BASE_PROMPT +
    `

CURRENT MODE: SITE CHATBOT
Your job: help visitors learn about Umut's services and convert interest into a Calendly booking.

GUIDELINES:
- Keep replies concise (2-4 sentences typically)
- When the visitor shows real interest or has a specific need, offer the Calendly: https://calendly.com/simsekk-umut/30min
- If they ask for rates, exact case studies, or sensitive specifics, say "mejor lo coordinamos en una llamada" and offer Calendly
- Out-of-scope questions (personal life, weather, etc.): gently redirect to professional matters
- Don't fabricate specific numbers, broker names, or testimonials beyond what's listed above
- Use bullet points only for actual service lists. Otherwise, conversational prose.`,

  qualifier:
    BASE_PROMPT +
    `

CURRENT MODE: IB QUALIFIER
Your job: evaluate whether the visitor is a good fit as an IB partner for Umut by asking questions ONE AT A TIME.

QUESTIONS TO COVER (one per turn, conversational):
1. Region — where is your audience based? (LATAM / MENA / Europe / Other)
2. Audience size & channel — how big is your community, and where? (Telegram, YouTube, Instagram, Discord, X, in-person, etc.)
3. Current broker partnership — are you working with a broker now? Which one?
4. Monthly FTDs — approximate new funded accounts per month (0 is OK, just ask)
5. Main goal — more clients? more FTDs? better retention? reactivation?
6. (If unclear) Are you a trader, an educator/marketer, or both?
7. (Last) Timeline — exploring or ready to start within 30 days?

RULES:
- Ask ONE question per response. Acknowledge their previous answer briefly first.
- Don't dump all questions at once. Don't number them visibly.
- After 5-7 answers, give the verdict in this exact format:
  **Veredicto:** Strong fit / Potential fit / Not yet ready
  **Por qué:** [2-3 sentence reasoning citing their actual answers]
  **Próximo paso:**
  - Strong fit → "Te recomiendo agendar una llamada con Umut: https://calendly.com/simsekk-umut/30min — propondría empezar con [package/service area]"
  - Potential fit → similar but suggest a specific gap to discuss in the call
  - Not yet ready → kindly explain what to build first (audience, regulatory clarity, etc.) — invite them to come back

STRONG-FIT CRITERIA:
- 1K+ engaged community in LATAM, MENA, or Europe
- Already monetizing OR clear path to monetize
- Realistic about timeline
- Willing to invest time in onboarding`,

  pulse:
    BASE_PROMPT +
    `

CURRENT MODE: MARKET PULSE
Your job: give traders & IBs quick, CURRENT intelligence on FX, CFDs, commodities, crypto using LIVE web search.

NON-NEGOTIABLE RULES:
- ALWAYS use web search for prices, trends, news, events — never quote from memory
- Search FIRST, then synthesize.
- Cite sources naturally in prose ("según Investing.com", "Reuters reporta")
- Keep responses scannable: brief summary line, then 2-4 bullets with key data points

OUTPUT STYLE:
- 1-line headline summary
- Bullets: price/level, recent move %, key driver, what to watch
- Timestamp when relevant
- For broad queries → search major movers: SPX, EUR/USD, BTC, gold

BOUNDARIES:
- NO financial advice. Just intel and context.
- If asked about Umut's services, say "para eso te paso al modo Chat" and stop.
- If asked something off-topic, redirect to markets.`,
};

const ALLOWED_MODES = new Set(Object.keys(PROMPTS));

export default async function handler(req) {
  if (req.method !== "POST") {
    return json({ error: "method_not_allowed" }, 405);
  }

  const ip =
    req.headers.get("x-real-ip") ||
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    "unknown";
  if (!checkRate(ip)) {
    return json({ error: "rate_limited" }, 429);
  }

  let body;
  try {
    body = await req.json();
  } catch {
    return json({ error: "invalid_json" }, 400);
  }

  const { mode, messages } = body || {};

  if (!ALLOWED_MODES.has(mode)) {
    return json({ error: "invalid_mode" }, 400);
  }
  if (!Array.isArray(messages) || messages.length === 0) {
    return json({ error: "messages_required" }, 400);
  }
  if (messages.length > MAX_MESSAGES) {
    return json({ error: "too_many_messages" }, 400);
  }
  for (const m of messages) {
    if (!m || (m.role !== "user" && m.role !== "assistant")) {
      return json({ error: "invalid_message_role" }, 400);
    }
    if (typeof m.content !== "string") {
      return json({ error: "invalid_message_content" }, 400);
    }
    if (m.content.length > MAX_MESSAGE_CHARS) {
      return json({ error: "message_too_long" }, 400);
    }
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    console.error("[concierge] ANTHROPIC_API_KEY missing");
    return json({ error: "server_misconfigured" }, 500);
  }

  const apiBody = {
    model: MODEL,
    max_tokens: MAX_TOKENS,
    system: PROMPTS[mode],
    messages: messages.map((m) => ({ role: m.role, content: m.content })),
  };
  if (mode === "pulse") {
    apiBody.tools = [{ type: "web_search_20250305", name: "web_search" }];
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);

  try {
    const upstream = await fetch(ANTHROPIC_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
        "anthropic-version": ANTHROPIC_VERSION,
      },
      body: JSON.stringify(apiBody),
      signal: controller.signal,
    });

    const text = await upstream.text();

    if (!upstream.ok) {
      console.error("[concierge] upstream error", upstream.status, text.slice(0, 500));
      return new Response(
        JSON.stringify({ error: "upstream_error", status: upstream.status }),
        {
          status: upstream.status >= 500 ? 502 : upstream.status,
          headers: { "Content-Type": "application/json" },
        }
      );
    }

    return new Response(text, {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch (err) {
    if (err?.name === "AbortError") {
      return json({ error: "upstream_timeout" }, 504);
    }
    console.error("[concierge] fetch failed", err);
    return json({ error: "upstream_unreachable" }, 502);
  } finally {
    clearTimeout(timeout);
  }
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    },
  });
}

function checkRate(ip) {
  const now = Date.now();
  const bucket = ipBuckets.get(ip);
  if (!bucket || now - bucket.windowStart > RATE_LIMIT_WINDOW_MS) {
    ipBuckets.set(ip, { count: 1, windowStart: now });
    return true;
  }
  if (bucket.count >= RATE_LIMIT_MAX) return false;
  bucket.count += 1;
  return true;
}
