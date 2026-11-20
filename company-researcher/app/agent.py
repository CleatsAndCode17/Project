"""Agent module: conversation routing, session management, and Gemini SDK integration."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

from app.fetcher import SafeFetcher
from app.security import (
    extract_urls,
    format_untrusted_data_envelope,
    validate_url,
)

# Load environment variables
load_dotenv()

# System prompt path
SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "system_prompt.txt"


def load_system_prompt() -> str:
    """Load system prompt from file."""
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return (
        "You are a Company Researcher agent. You research a company ONLY from the website text provided to you."
    )


# Preload system prompt at startup
SYSTEM_PROMPT = load_system_prompt()

# Off-topic heuristic patterns
OFF_TOPIC_PATTERNS = [
    re.compile(r"\b(weather in|recipe for|bake a cake|write a poem|write a song|tell me a joke)\b", re.IGNORECASE),
    re.compile(r"\b(write (?:a )?python|write (?:a )?code|debug this code|write (?:a )?script)\b", re.IGNORECASE),
    re.compile(r"\b(capital of|who is the president of|who won the (?:world cup|super bowl))\b", re.IGNORECASE),
    re.compile(r"\b(translate (?:this|the following) to|solve \d+\s*[\+\-\*\/]|\d+\s*[\+\-\*\/]\s*\d+)\b", re.IGNORECASE),
]

OFF_TOPIC_REPLY = "I can only help with researching companies from their websites."
NO_COMPANY_REPLY = "Please send a company website URL (e.g. stripe.com) to start researching."
NO_API_KEY_REPLY = "GEMINI_API_KEY is not configured. Please add your GEMINI_API_KEY to the .env file and restart the server."


def is_clearly_off_topic(message: str) -> bool:
    """Detect common off-topic queries that are unrelated to company research."""
    for pattern in OFF_TOPIC_PATTERNS:
        if pattern.search(message):
            return True
    return False


@dataclass
class ChatTurn:
    role: str  # "user" or "model"
    text: str


@dataclass
class SessionState:
    session_id: str
    company_name: Optional[str] = None
    company_url: Optional[str] = None
    website_text: Optional[str] = None
    is_js_sparse: bool = False
    history: List[ChatTurn] = field(default_factory=list)

    def add_turn(self, role: str, text: str):
        self.history.append(ChatTurn(role=role, text=text))
        # Keep last 10 turns (5 user + 5 model turns or last 10 messages)
        if len(self.history) > 10:
            self.history = self.history[-10:]

    def clear(self):
        self.company_name = None
        self.company_url = None
        self.website_text = None
        self.is_js_sparse = False
        self.history.clear()


class CompanyResearcherAgent:
    """Coordinates session memory, URL fetching, message routing, and Gemini LLM calls."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        max_pages: Optional[int] = None,
        request_timeout: Optional[float] = None,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
        self.max_pages = max_pages or int(os.getenv("MAX_PAGES", "4"))
        self.request_timeout = request_timeout or float(os.getenv("REQUEST_TIMEOUT", "10"))
        
        self.fetcher = SafeFetcher(timeout=self.request_timeout)
        self.sessions: Dict[str, SessionState] = {}
        self.system_prompt = SYSTEM_PROMPT

    def get_or_create_session(self, session_id: str) -> SessionState:
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(session_id=session_id)
        return self.sessions[session_id]

    def reset_session(self, session_id: str):
        if session_id in self.sessions:
            self.sessions[session_id].clear()

    def _extract_company_name_from_reply(self, reply: str, fallback_url: str) -> str:
        """Extract company name from the **Company:** field in the report."""
        match = re.search(r"\*\*Company:\*\*\s*(.+?)(?:\s*\(|$|\n)", reply)
        if match:
            candidate = match.group(1).strip()
            # Clean square brackets if template brackets remain
            candidate = re.sub(r"[\[\]]", "", candidate).strip()
            if candidate and candidate.lower() != "name":
                return candidate

        # Fallback to domain name
        domain = re.sub(r"^https?://(?:www\.)?", "", fallback_url, flags=re.IGNORECASE)
        domain = domain.split("/")[0]
        return domain.capitalize() if domain else fallback_url

    async def _call_gemini(self, contents: list, custom_system_instruction: Optional[str] = None) -> str:
        """Call the Google GenAI SDK with graceful error handling."""
        if not self.api_key:
            return NO_API_KEY_REPLY

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            instruction = custom_system_instruction or self.system_prompt
            config = types.GenerateContentConfig(
                system_instruction=instruction,
                temperature=0.2,
            )

            # Convert contents into list of types.Content or pass directly
            genai_contents = []
            for item in contents:
                if isinstance(item, ChatTurn):
                    genai_contents.append(
                        types.Content(
                            role="user" if item.role == "user" else "model",
                            parts=[types.Part.from_text(text=item.text)],
                        )
                    )
                elif isinstance(item, str):
                    genai_contents.append(
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=item)],
                        )
                    )
                elif isinstance(item, types.Content):
                    genai_contents.append(item)

            response = client.models.generate_content(
                model=self.model_name,
                contents=genai_contents,
                config=config,
            )

            if response and response.text:
                return response.text.strip()
            return "No content received from Gemini model."

        except Exception as exc:
            err_str = str(exc)
            if "API_KEY_INVALID" in err_str or "api key not valid" in err_str.lower():
                return "Invalid Gemini API key. Please verify your GEMINI_API_KEY in the .env file."
            if "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                return "Gemini API rate limit or quota exceeded. Please try again shortly."
            # Do not return raw stack trace
            return f"An error occurred while contacting the Gemini model: {err_str.splitlines()[0]}"

    async def process_message(self, session_id: str, message: str) -> Tuple[str, Optional[str]]:
        """
        Main message router:
        1. URL detected -> fetch and research
        2. No URL, company exists -> follow-up or off-topic
        3. No URL, no company -> prompt for URL
        4. Off-topic check
        Returns: (reply_text, company_name_or_none)
        """
        session = self.get_or_create_session(session_id)
        cleaned_msg = message.strip()

        # Step 1: Detect URLs or bare domains in message
        first_url, has_multiple, all_urls = extract_urls(cleaned_msg)

        if first_url:
            # Validate URL for SSRF
            is_valid, err_or_host, norm_url = validate_url(first_url)
            if not is_valid:
                return f"I couldn't open this website. ({err_or_host})", session.company_name

            # Crawl website
            fetch_res = await self.fetcher.crawl_site(norm_url, max_pages=self.max_pages)
            if not fetch_res.success or not fetch_res.combined_text.strip():
                return "I couldn't open this website.", session.company_name

            # Prepare untrusted data envelope
            data_envelope = format_untrusted_data_envelope(
                url=norm_url,
                content=fetch_res.combined_text,
            )

            user_prompt = (
                f"Please research this company from the following website text and generate the structured research report according to your instructions:\n\n"
                f"{data_envelope}"
            )

            # Call Gemini
            reply = await self._call_gemini([user_prompt])

            # Append warning for multiple URLs
            if has_multiple:
                reply += "\n\nNote: I researched only the first URL. Please send other URLs one at a time."

            # Append notice if JavaScript-sparse
            if fetch_res.is_js_sparse:
                reply += "\n\nNote: The website appears to be JavaScript-rendered with minimal visible text, so this report was generated from limited content."

            # Update session state with new company
            company_name = self._extract_company_name_from_reply(reply, norm_url)
            session.clear()
            session.company_name = company_name
            session.company_url = norm_url
            session.website_text = fetch_res.combined_text
            session.is_js_sparse = fetch_res.is_js_sparse
            session.add_turn("user", cleaned_msg)
            session.add_turn("model", reply)

            return reply, company_name

        # Step 3: No URL and no researched company yet
        if not session.website_text:
            return NO_COMPANY_REPLY, None

        # Step 4: Off-topic check for follow-up message
        if is_clearly_off_topic(cleaned_msg):
            return OFF_TOPIC_REPLY, session.company_name

        # Step 2: Follow-up question on existing researched company
        # Build prompt strictly constraining answer to stored website data
        envelope = format_untrusted_data_envelope(
            url=session.company_url or "Stored Company Website",
            content=session.website_text,
        )

        follow_up_system_instruction = (
            f"{self.system_prompt}\n\n"
            "ADDITIONAL FOLLOW-UP RULES:\n"
            "You are answering a follow-up question about the company that was previously researched.\n"
            "1. DO NOT generate the initial 5-point research report again. Answer the specific follow-up question directly and concisely.\n"
            "2. Answer using ONLY the stored website content provided in the data envelope below.\n"
            "3. If the user's question is off-topic (not about the researched company, its business, products, operations, or research findings), "
            f"reply strictly: '{OFF_TOPIC_REPLY}'\n"
            "4. If the answer is not in the provided website content, say: 'Not clear from the website.'\n"
            "5. Keep your answer short, factual, and direct."
        )

        # Include recent conversation turns for context
        contents: List[ChatTurn] = []
        # Add the ground-truth website data context
        contents.append(ChatTurn(role="user", text=f"Here is the website content for context:\n\n{envelope}"))
        contents.append(ChatTurn(role="model", text=f"I have received the website data for {session.company_name or 'the company'}. What would you like to know?"))

        # Add recent turns (up to last 6 turns)
        for turn in session.history[-6:]:
            contents.append(turn)

        # Add current follow-up question
        contents.append(ChatTurn(role="user", text=cleaned_msg))

        reply = await self._call_gemini(contents, custom_system_instruction=follow_up_system_instruction)

        # Check if the model answered with off-topic indicator
        if "I can only help with researching companies" in reply:
            reply = OFF_TOPIC_REPLY

        # Update session history
        session.add_turn("user", cleaned_msg)
        session.add_turn("model", reply)

        return reply, session.company_name
