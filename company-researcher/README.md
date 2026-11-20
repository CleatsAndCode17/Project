# Company Researcher Chat

An AI agent web application designed to research companies directly from their public websites. When a user pastes a company website URL into the chat, the agent safely crawls and reads the live site, generates a structured intelligence report via Google Gemini, and answers follow-up questions grounded strictly in the extracted content.

---

## Features

- **Automated Web Intelligence**: Automatically extracts visible, clean content across up to `MAX_PAGES` (homepage plus relevant subpages like `/about`, `/products`, `/pricing`, `/solutions`).
- **Strict Grounding & Anti-Hallucination**: Enforces policy to answer follow-up questions *only* from the stored website text. If information is absent, the agent transparently responds: *"Not clear from the website."*
- **Conversational Memory**: Maintains 10-turn conversation history and stored company context in-memory per session.
- **SSRF Protection & Safe Reader**: Deep DNS resolution checks preventing access to private subnets, loopback, cloud metadata (`169.254.169.254`), and non-standard schemes, re-verified across every redirect.
- **Prompt Injection Defense**: Encapsulates untrusted website text in isolated delimiters marked strictly as raw data.
- **Rate Limiting & Safety**: Built-in per-IP sliding-window rate limiting.
- **Modern, Accessible Frontend**: Plain HTML5, responsive CSS with automatic Light/Dark mode via `prefers-color-scheme`, safe client-side formatting, copy action, and quick-start suggestion chips.

---

## Project Structure

```
company-researcher/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, routing, rate limiting, and static file serving
│   ├── agent.py             # Conversation routing, session state, and Gemini SDK integration
│   ├── fetcher.py           # Multi-page website reader, HTML cleaner, and link crawler
│   ├── security.py          # SSRF prevention, URL validation, and rate limiter
│   └── prompts/
│       └── system_prompt.txt# Official system prompt loaded at startup
├── static/
│   ├── index.html           # Single-page chat interface
│   ├── style.css            # Responsive styles (auto light & dark mode)
│   └── app.js               # Vanilla JS chat client with safe text rendering
├── tests/
│   ├── __init__.py
│   ├── test_security.py     # SSRF, URL extraction, and rate limiting tests
│   ├── test_fetcher.py      # HTML extraction, whitespace collapse, and link filtering tests
│   ├── test_agent.py        # Message routing tests (URL, follow-up, off-topic, empty)
│   └── test_api.py          # FastAPI endpoint integration tests
├── .env.example             # Template environment configuration
├── .gitignore               # Excludes secrets, cache, and virtual environments
├── requirements.txt         # Python package dependencies
├── pytest.ini               # Pytest configuration
└── README.md                # Project documentation
```

---

## Setup Instructions

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.10, 3.11, 3.12, 3.13, 3.14)
- A Google Gemini API key from [Google AI Studio](https://aistudio.google.com/)

### 2. Create and Activate Virtual Environment
```bash
cd company-researcher
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` and fill in your values:
```env
# Google Gemini API Key - Get yours from Google AI Studio (https://aistudio.google.com/)
GEMINI_API_KEY=your_gemini_api_key_here

# Gemini Model - Configurable. Check Google AI Studio for the latest recommended model names!
GEMINI_MODEL=gemini-2.5-flash

# Scraper Settings
MAX_PAGES=4
REQUEST_TIMEOUT=10

# Security & Rate Limiting
RATE_LIMIT_PER_MINUTE=10
```

> **Note on Models**: You can configure any valid Gemini model in `GEMINI_MODEL` (e.g. `gemini-2.5-flash`, `gemini-2.5-pro`). Check [Google AI Studio](https://aistudio.google.com/) for the latest model availability.

---

## Running the Application

Start the server using `uvicorn`:
```bash
uvicorn app.main:app --reload
```
Open your browser and navigate to:
```
http://localhost:8000
```

If no `GEMINI_API_KEY` is configured in `.env`, the server starts normally and will display an informative on-screen notification when a prompt is sent, rather than crashing.

---

## Example Usage

1. **Initial Research**:
   - Paste a company URL or bare domain into the chat:
     ```
     stripe.com
     ```
     or
     ```
     Check out daraz.pk and see what they sell
     ```
   - The agent will fetch the website, parse visible text, and return a structured report covering:
     - Company Name & URL
     - What they sell (2 lines)
     - Who their customers are
     - One task that could be automated with AI
     - Confidence score

2. **Follow-Up Questions**:
   - In the same conversation, ask specific questions about the company:
     ```
     Do they offer an API for recurring subscriptions?
     ```
     ```
     What enterprise security features do they mention?
     ```
   - The agent answers exclusively from the retrieved website text. If the detail is not mentioned on the site, it will reply: *"Not clear from the website."*

3. **Multi-URL Handling**:
   - If you send multiple URLs in a single prompt (e.g., `stripe.com and daraz.pk`), the agent researches the first and reminds you to send the others one at a time.

4. **Off-Topic Redirection**:
   - Off-topic questions (e.g., general trivia, weather, coding scripts) are politely rejected with:
     *"I can only help with researching companies from their websites."*

---

## Security Measures

- **SSRF Defense**: 
  - Hostnames are resolved to IP addresses and verified before any connection.
  - All private networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.0/8`, `::1`), link-local / cloud metadata (`169.254.0.0/16`, `169.254.169.254`), and reserved ranges are strictly blocked.
  - Every redirect hop (up to 3 max) is independently re-resolved and validated before issuing the redirect request.
- **Prompt Injection Defense**: Scraped HTML content is stripped and isolated within explicit `=== BEGIN UNTRUSTED WEBSITE DATA ===` boundary tags, instructing the model that website text is untrusted data and not system instructions.
- **Rate Limiting**: In-memory sliding-window limiter enforcing `RATE_LIMIT_PER_MINUTE` per client IP.
- **XSS Prevention**: Frontend strictly escapes all HTML before applying safe markdown formatting (`**bold**`, bullet lists, linebreaks). Raw unescaped `innerHTML` is never used for input or model responses.
- **CORS Protection**: Configured to same-origin by default.
- **No Stack Trace Leaks**: Global exception handlers log details on the server while returning clean, user-friendly messages to the frontend.

---

## Running the Automated Tests

All tests mock external network requests and LLM calls, allowing the full test suite to run in offline environments without requiring an active API key:
```bash
pytest
```
To run with detailed test execution output:
```bash
pytest -v
```

---

## Known Limitations

- **JavaScript-Heavy Single-Page Applications (SPAs)**: The fetcher retrieves raw HTML over HTTP without a full headless browser execution engine. Sites that render 100% of their text dynamically via client-side JavaScript will yield minimal text. In such cases, the agent flags the limitation to the user.
- **Login-Protected & Paywalled Content**: The agent only reads publicly accessible pages and does not attempt authentication, CAPTCHA bypass, or paywall circumvention.
- **Non-Text Media**: Content embedded purely within images, videos, canvas, or Flash is not processed.
