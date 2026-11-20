"""Tests for agent conversation routing and state management."""

from unittest.mock import AsyncMock
import pytest
from app.agent import (
    CompanyResearcherAgent,
    NO_COMPANY_REPLY,
    OFF_TOPIC_REPLY,
    is_clearly_off_topic,
)
from app.fetcher import FetchResult


@pytest.fixture
def mock_agent(monkeypatch):
    agent = CompanyResearcherAgent(api_key="mock_key", model_name="gemini-2.5-flash")
    return agent


@pytest.mark.asyncio
async def test_route_url_research_single(mock_agent, monkeypatch):
    # Mock crawl_site
    mock_crawl = AsyncMock(
        return_value=FetchResult(
            success=True,
            url="https://stripe.com",
            combined_text="Stripe is a financial infrastructure platform for businesses.",
            pages_crawled=2,
            is_js_sparse=False,
        )
    )
    monkeypatch.setattr(mock_agent.fetcher, "crawl_site", mock_crawl)

    # Mock _call_gemini
    sample_report = (
        "**Company:** Stripe (https://stripe.com)\n"
        "**What they sell (2 lines):**\n"
        "Line 1: Payment processing APIs\n"
        "Line 2: Global financial infrastructure\n"
        "**Who their customers are:**\n"
        "Internet businesses of all sizes, including Amazon and Shopify.\n"
        "**One task that could be automated with AI:**\n"
        "- Task: Dispute evidence compilation\n"
        "- Why it fits AI: Repetitive document synthesis\n"
        "- How AI would do it: Aggregate transaction logs\n"
        "**Confidence:** High - Stated on official website"
    )
    mock_gemini = AsyncMock(return_value=sample_report)
    monkeypatch.setattr(mock_agent, "_call_gemini", mock_gemini)

    reply, company = await mock_agent.process_message("sess_1", "Please research stripe.com")

    assert company == "Stripe"
    assert "**Company:** Stripe" in reply
    assert "Dispute evidence compilation" in reply

    # Verify session state was recorded
    session = mock_agent.sessions.get("sess_1")
    assert session is not None
    assert session.company_name == "Stripe"
    assert "Stripe is a financial infrastructure" in session.website_text


@pytest.mark.asyncio
async def test_route_url_research_multiple_warning(mock_agent, monkeypatch):
    mock_crawl = AsyncMock(
        return_value=FetchResult(
            success=True,
            url="https://stripe.com",
            combined_text="Stripe payments",
            pages_crawled=1,
        )
    )
    monkeypatch.setattr(mock_agent.fetcher, "crawl_site", mock_crawl)

    mock_gemini = AsyncMock(return_value="**Company:** Stripe (https://stripe.com)\n**Confidence:** High")
    monkeypatch.setattr(mock_agent, "_call_gemini", mock_gemini)

    reply, company = await mock_agent.process_message(
        "sess_2", "Can you check stripe.com and also daraz.pk?"
    )

    # Must research first and append warning note
    assert "Note: I researched only the first URL. Please send other URLs one at a time." in reply
    assert mock_crawl.call_args[0][0] == "https://stripe.com"


@pytest.mark.asyncio
async def test_route_no_url_no_company(mock_agent, monkeypatch):
    # Gemini should NOT be called
    mock_gemini = AsyncMock()
    monkeypatch.setattr(mock_agent, "_call_gemini", mock_gemini)

    reply, company = await mock_agent.process_message("sess_empty", "What is your opinion on fintech?")

    assert reply == NO_COMPANY_REPLY
    assert company is None
    assert mock_gemini.call_count == 0


@pytest.mark.asyncio
async def test_route_follow_up_on_researched_company(mock_agent, monkeypatch):
    session = mock_agent.get_or_create_session("sess_followup")
    session.company_name = "Stripe"
    session.company_url = "https://stripe.com"
    session.website_text = "Stripe offers payments, billing, and identity verification services."

    mock_gemini = AsyncMock(return_value="Stripe offers billing and identity verification services.")
    monkeypatch.setattr(mock_agent, "_call_gemini", mock_gemini)

    reply, company = await mock_agent.process_message(
        "sess_followup", "Do they support billing and subscriptions?"
    )

    assert company == "Stripe"
    assert "Stripe offers billing and identity verification" in reply
    assert mock_gemini.call_count == 1


@pytest.mark.asyncio
async def test_route_off_topic_message(mock_agent, monkeypatch):
    session = mock_agent.get_or_create_session("sess_offtopic")
    session.company_name = "Stripe"
    session.company_url = "https://stripe.com"
    session.website_text = "Stripe content"

    # Off-topic heuristic test
    assert is_clearly_off_topic("What is the weather in Tokyo?") is True
    assert is_clearly_off_topic("Write a python script to reverse a linked list") is True
    assert is_clearly_off_topic("Tell me a joke about dogs") is True

    # Message routing off-topic test
    reply, company = await mock_agent.process_message("sess_offtopic", "What is the weather in Tokyo today?")
    assert reply == OFF_TOPIC_REPLY
    assert company == "Stripe"
