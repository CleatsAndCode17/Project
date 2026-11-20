/**
 * Company Researcher - Frontend Application Client
 * Clean Vanilla JavaScript, zero build step, zero dependencies
 */

(function () {
  'use strict';

  // DOM Elements
  const appRoot = document.getElementById('appRoot');
  const contentScroll = document.getElementById('contentScroll');
  const messagesFeed = document.getElementById('messagesFeed');
  const chatForm = document.getElementById('chatForm');
  const messageInput = document.getElementById('messageInput');
  const sendBtn = document.getElementById('sendBtn');
  const resetBtn = document.getElementById('resetBtn');
  const typingIndicator = document.getElementById('typingIndicator');
  const typingText = document.getElementById('typingText');
  const activeCompanyBadge = document.getElementById('activeCompanyBadge');
  const jumpToBottomBtn = document.getElementById('jumpToBottomBtn');
  const chipsRow = document.getElementById('chipsRow');

  // Session Storage Management
  const SESSION_KEY = 'company_researcher_session_id';
  let lastFailedMessage = null;

  function getSessionId() {
    let id = sessionStorage.getItem(SESSION_KEY);
    if (!id) {
      if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        id = crypto.randomUUID();
      } else {
        id = 'sess_' + Date.now() + '_' + Math.random().toString(36).substring(2, 11);
      }
      sessionStorage.setItem(SESSION_KEY, id);
    }
    return id;
  }

  const sessionId = getSessionId();

  // --------------------------------------------------------------------------
  // State & Placeholder Management
  // --------------------------------------------------------------------------
  function setAppState(state) {
    appRoot.dataset.state = state;
    if (state === 'empty') {
      messageInput.placeholder = 'Ask me anything...';
      if (chipsRow) chipsRow.style.display = 'flex';
      activeCompanyBadge.style.display = 'none';
      activeCompanyBadge.textContent = '';
    } else {
      messageInput.placeholder = 'Paste a company website, e.g. stripe.com';
      if (chipsRow) chipsRow.style.display = 'none';
    }
  }

  // --------------------------------------------------------------------------
  // Scroll Management & Jump to Latest
  // --------------------------------------------------------------------------
  function isUserScrolledUp() {
    const threshold = 80;
    return (
      contentScroll.scrollHeight - contentScroll.scrollTop - contentScroll.clientHeight > threshold
    );
  }

  function scrollToBottom(force = false) {
    if (force || !isUserScrolledUp()) {
      contentScroll.scrollTop = contentScroll.scrollHeight;
    }
  }

  contentScroll.addEventListener('scroll', () => {
    if (appRoot.dataset.state === 'chat' && isUserScrolledUp()) {
      jumpToBottomBtn.style.display = 'inline-flex';
    } else {
      jumpToBottomBtn.style.display = 'none';
    }
  });

  jumpToBottomBtn.addEventListener('click', () => {
    contentScroll.scrollTo({
      top: contentScroll.scrollHeight,
      behavior: 'smooth',
    });
    jumpToBottomBtn.style.display = 'none';
  });

  // --------------------------------------------------------------------------
  // Safe HTML Escaping & Fallback Markdown Parser
  // --------------------------------------------------------------------------
  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function renderSafeProse(rawText) {
    const escaped = escapeHtml(rawText);
    const withBold = escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    const lines = withBold.split('\n');
    const result = [];
    let inList = false;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const bulletMatch = line.match(/^\s*[-*]\s+(.+)$/);
      if (bulletMatch) {
        if (!inList) {
          result.push('<ul>');
          inList = true;
        }
        result.push(`<li>${bulletMatch[1]}</li>`);
      } else {
        if (inList) {
          result.push('</ul>');
          inList = false;
        }
        result.push(line);
      }
    }
    if (inList) result.push('</ul>');

    return result.join('\n').replace(/\n/g, '<br>');
  }

  // --------------------------------------------------------------------------
  // Structured Report Card Parser (DOM Built for complete XSS safety)
  // --------------------------------------------------------------------------
  function tryParseReport(rawText) {
    // Check if the reply satisfies core report sections
    if (!rawText.includes('**Company:**') || !rawText.includes('**What they sell')) {
      return null;
    }

    try {
      const data = {
        company: '',
        url: '',
        whatTheySell: '',
      customers: [],   // array of strings
        taskTitle: '',
        whyFits: '',
        howAi: '',
        confidenceLevel: '',
        confidenceReason: '',
        additionalNotes: '',
      };

      // 1. Company line
      const companyMatch = rawText.match(/\*\*Company:\*\*\s*(.+?)(?:\s*\((https?:\/\/[^\s)]+)\))?(?:\n|$)/i);
      if (companyMatch) {
        data.company = companyMatch[1].replace(/[\[\]]/g, '').trim();
        data.url = companyMatch[2] ? companyMatch[2].trim() : '';
      }

      // 2. What they sell — strip any residual "Line N:" prefixes the model may emit
      const sellMatch = rawText.match(/\*\*What they sell.*?\*\*:?\s*\n([\s\S]*?)(?=\n\*\*Who their customers are|\n\*\*One task|$)/i);
      if (sellMatch) {
        // Remove "Line 1:", "Line 2:", etc. and join into clean prose
        const cleanSell = sellMatch[1]
          .split('\n')
          .map(l => l.replace(/^Line\s*\d+:\s*/i, '').trim())
          .filter(Boolean)
          .join(' ');
        data.whatTheySell = cleanSell;
      }

      // 3. Customers — parse into bullet array
      const custMatch = rawText.match(/\*\*Who their customers are:\*\*\s*\n([\s\S]*?)(?=\n\*\*One task|$)/i);
      if (custMatch) {
        const raw = custMatch[1].trim();
        // Split on bullet lines (- or *) if present, else treat as single item
        const lines = raw.split('\n').map(l => l.replace(/^[\s\-\*]+/, '').trim()).filter(Boolean);
        data.customers = lines.length ? lines : [raw];
      }

      // 4. Automation task
      const taskMatch = rawText.match(/\*\*One task that could be automated with AI:\*\*\s*\n([\s\S]*?)(?=\n\*\*Confidence:|$)/i);
      if (taskMatch) {
        const taskBlock = taskMatch[1];
        const tMatch = taskBlock.match(/(?:[-*]\s*)?Task:\s*(.+?)(?=\n|$)/i);
        const wMatch = taskBlock.match(/(?:[-*]\s*)?Why it fits AI:\s*(.+?)(?=\n|$)/i);
        const hMatch = taskBlock.match(/(?:[-*]\s*)?How AI would do it:\s*(.+?)(?=\n|$)/i);

        data.taskTitle = tMatch ? tMatch[1].trim() : '';
        data.whyFits = wMatch ? wMatch[1].trim() : '';
        data.howAi = hMatch ? hMatch[1].trim() : '';
      }

      // 5. Confidence
      const confMatch = rawText.match(/\*\*Confidence:\*\*\s*(High|Medium|Low)\b(?:\s*[-–—:]\s*(.*))?/i);
      if (confMatch) {
        data.confidenceLevel = confMatch[1].trim();
        data.confidenceReason = confMatch[2] ? confMatch[2].trim() : '';
      }

      // 6. Trailing notes / extra text
      const notesMatch = rawText.match(/\*\*Confidence:\*\*.*?\n\n([\s\S]+)$/i);
      if (notesMatch) {
        data.additionalNotes = notesMatch[1].trim();
      }

      // Require company and at least one core section
      if (!data.company && !data.whatTheySell && !data.customers.length) {
        return null;
      }

      return data;
    } catch (_) {
      return null;
    }
  }

  function createReportCardElement(parsed) {
    const card = document.createElement('div');
    card.className = 'report-card-container';

    // Header: Company Name + External Link
    const header = document.createElement('div');
    header.className = 'report-header';

    const title = document.createElement('h2');
    title.className = 'report-company-title';
    title.textContent = parsed.company || 'Company Research';
    header.appendChild(title);

    if (parsed.url && /^https?:\/\//i.test(parsed.url)) {
      const link = document.createElement('a');
      link.className = 'report-company-link';
      link.href = parsed.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.innerHTML = `
        <span>Visit site</span>
        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
          <polyline points="15 3 21 3 21 9"></polyline>
          <line x1="10" y1="14" x2="21" y2="3"></line>
        </svg>
      `;
      header.appendChild(link);
    }
    card.appendChild(header);

    // Section 1: What they sell
    if (parsed.whatTheySell) {
      const sec = document.createElement('div');
      sec.className = 'report-section';
      const label = document.createElement('div');
      label.className = 'report-label';
      label.textContent = 'What They Sell';
      const body = document.createElement('div');
      body.className = 'report-body';
      body.textContent = parsed.whatTheySell;
      sec.appendChild(label);
      sec.appendChild(body);
      card.appendChild(sec);
    }

    // Section 2: Customers
    if (parsed.customers) {
      const sec = document.createElement('div');
      sec.className = 'report-section';
      const label = document.createElement('div');
      label.className = 'report-label';
      label.textContent = 'Target Customers';
      const body = document.createElement('div');
      body.className = 'report-body';
      body.textContent = parsed.customers;
      sec.appendChild(label);
      sec.appendChild(body);
      card.appendChild(sec);
    }

    // Section 3: AI Automation Subcard
    if (parsed.taskTitle || parsed.whyFits || parsed.howAi) {
      const sec = document.createElement('div');
      sec.className = 'report-section';
      const label = document.createElement('div');
      label.className = 'report-label';
      label.textContent = 'AI Automation Opportunity';

      const subcard = document.createElement('div');
      subcard.className = 'automation-subcard';

      if (parsed.taskTitle) {
        const row = document.createElement('div');
        row.className = 'automation-row';
        const rLabel = document.createElement('span');
        rLabel.className = 'automation-row-label';
        rLabel.textContent = 'Task';
        const rVal = document.createElement('span');
        rVal.className = 'automation-row-value';
        rVal.textContent = parsed.taskTitle;
        row.appendChild(rLabel);
        row.appendChild(rVal);
        subcard.appendChild(row);
      }

      if (parsed.whyFits) {
        const row = document.createElement('div');
        row.className = 'automation-row';
        const rLabel = document.createElement('span');
        rLabel.className = 'automation-row-label';
        rLabel.textContent = 'Why It Fits AI';
        const rVal = document.createElement('span');
        rVal.className = 'automation-row-value';
        rVal.textContent = parsed.whyFits;
        row.appendChild(rLabel);
        row.appendChild(rVal);
        subcard.appendChild(row);
      }

      if (parsed.howAi) {
        const row = document.createElement('div');
        row.className = 'automation-row';
        const rLabel = document.createElement('span');
        rLabel.className = 'automation-row-label';
        rLabel.textContent = 'How AI Would Do It';
        const rVal = document.createElement('span');
        rVal.className = 'automation-row-value';
        rVal.textContent = parsed.howAi;
        row.appendChild(rLabel);
        row.appendChild(rVal);
        subcard.appendChild(row);
      }

      sec.appendChild(label);
      sec.appendChild(subcard);
      card.appendChild(sec);
    }

    // Section 4: Confidence
    if (parsed.confidenceLevel) {
      const sec = document.createElement('div');
      sec.className = 'report-section';
      const label = document.createElement('div');
      label.className = 'report-label';
      label.textContent = 'Research Confidence';

      const row = document.createElement('div');
      row.className = 'confidence-row';

      const badge = document.createElement('span');
      const level = parsed.confidenceLevel.toLowerCase();
      badge.className = `badge-confidence badge-${level === 'high' ? 'high' : level === 'medium' ? 'medium' : 'low'}`;
      badge.textContent = parsed.confidenceLevel;
      row.appendChild(badge);

      if (parsed.confidenceReason) {
        const reason = document.createElement('span');
        reason.className = 'confidence-reason';
        reason.textContent = parsed.confidenceReason;
        row.appendChild(reason);
      }

      sec.appendChild(label);
      sec.appendChild(row);
      card.appendChild(sec);
    }

    // Additional Notes
    if (parsed.additionalNotes) {
      const sec = document.createElement('div');
      sec.className = 'report-section';
      const body = document.createElement('div');
      body.className = 'report-body';
      body.style.fontStyle = 'italic';
      body.style.color = '#94a3b8';
      body.textContent = parsed.additionalNotes;
      sec.appendChild(body);
      card.appendChild(sec);
    }

    return card;
  }

  // --------------------------------------------------------------------------
  // Message Insertion Functions
  // --------------------------------------------------------------------------
  function appendUserMessage(text) {
    setAppState('chat');

    const wrapper = document.createElement('div');
    wrapper.className = 'message-item user-item';

    const bubble = document.createElement('div');
    bubble.className = 'user-bubble';
    bubble.textContent = text; // Plain text only

    wrapper.appendChild(bubble);
    messagesFeed.appendChild(wrapper);
    scrollToBottom(true);
  }

  function appendAgentMessage(text, companyName) {
    setAppState('chat');

    const wrapper = document.createElement('div');
    wrapper.className = 'message-item agent-item';

    const card = document.createElement('div');
    card.className = 'agent-card';

    // Header with avatar and copy button
    const cardHeader = document.createElement('div');
    cardHeader.className = 'agent-card-header';

    const meta = document.createElement('div');
    meta.className = 'agent-avatar-meta';
    meta.innerHTML = `
      <div class="agent-avatar-icon" aria-hidden="true">
        <svg viewBox="0 0 20 20" width="14" height="14" fill="none">
          <circle cx="9" cy="9" r="6" stroke="#1d9bf0" stroke-width="2"></circle>
          <path d="M14 14l3.5 3.5" stroke="#38bdf8" stroke-width="2" stroke-linecap="round"></path>
        </svg>
      </div>
      <span class="agent-name-label">Researcher</span>
    `;

    // Copy Button with 1.5s "Copied" feedback
    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'btn-copy';
    copyBtn.setAttribute('aria-label', 'Copy response to clipboard');
    copyBtn.innerHTML = `
      <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
      </svg>
      <span>Copy</span>
    `;

    copyBtn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(text);
      } catch (_) {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }

      copyBtn.innerHTML = `
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        <span style="color: #34d399;">Copied</span>
      `;

      setTimeout(() => {
        copyBtn.innerHTML = `
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
          <span>Copy</span>
        `;
      }, 1500);
    });

    cardHeader.appendChild(meta);
    cardHeader.appendChild(copyBtn);
    card.appendChild(cardHeader);

    // Body: Try structured report card first, fallback to safe prose
    const parsedReport = tryParseReport(text);
    if (parsedReport) {
      card.appendChild(createReportCardElement(parsedReport));
    } else {
      const proseDiv = document.createElement('div');
      proseDiv.className = 'agent-prose';
      proseDiv.innerHTML = renderSafeProse(text);
      card.appendChild(proseDiv);
    }

    wrapper.appendChild(card);
    messagesFeed.appendChild(wrapper);

    if (companyName) {
      activeCompanyBadge.textContent = companyName;
      activeCompanyBadge.style.display = 'inline-block';
    }

    scrollToBottom();
  }

  function appendErrorMessage(errorText, isRetryable = false) {
    setAppState('chat');

    const wrapper = document.createElement('div');
    wrapper.className = 'message-item agent-item';

    const card = document.createElement('div');
    card.className = 'error-card';

    const msg = document.createElement('div');
    msg.className = 'error-message';
    msg.textContent = errorText;
    card.appendChild(msg);

    if (isRetryable && lastFailedMessage) {
      const retryBtn = document.createElement('button');
      retryBtn.type = 'button';
      retryBtn.className = 'btn-retry';
      retryBtn.textContent = 'Try again';
      retryBtn.addEventListener('click', () => {
        wrapper.remove();
        if (lastFailedMessage) {
          sendMessage(lastFailedMessage);
        }
      });
      card.appendChild(retryBtn);
    }

    wrapper.appendChild(card);
    messagesFeed.appendChild(wrapper);
    scrollToBottom(true);
  }

  // --------------------------------------------------------------------------
  // Loading & Submission Handlers
  // --------------------------------------------------------------------------
  function setLoading(isLoading, label = 'Reading the website...') {
    if (isLoading) {
      typingText.textContent = label;
      typingIndicator.style.display = 'flex';
      sendBtn.disabled = true;
      messageInput.disabled = true;
      scrollToBottom();
    } else {
      typingIndicator.style.display = 'none';
      sendBtn.disabled = false;
      messageInput.disabled = false;
      messageInput.focus();
    }
  }

  async function sendMessage(text) {
    const trimmed = text.trim();
    if (!trimmed) return;

    if (trimmed.length > 2000) {
      appendErrorMessage('Message exceeds the maximum limit of 2000 characters.');
      return;
    }

    lastFailedMessage = trimmed;

    // Display user message and clear field
    appendUserMessage(trimmed);
    messageInput.value = '';
    messageInput.style.height = 'auto';

    const isUrl = /(?:https?:\/\/|\.com|\.pk|\.org|\.net|\.io|\.ai)/i.test(trimmed);
    setLoading(true, isUrl ? 'Reading the website...' : 'Thinking...');

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message: trimmed,
        }),
      });

      if (!response.ok) {
        let errorDetail = 'An error occurred while contacting the server.';
        try {
          const errData = await response.json();
          if (errData && errData.detail) {
            errorDetail = errData.detail;
          }
        } catch (_) {}

        if (response.status === 429) {
          appendErrorMessage('Rate limit reached: Please wait a moment before sending more messages.', false);
        } else {
          appendErrorMessage(errorDetail, true);
        }
        return;
      }

      const data = await response.json();
      lastFailedMessage = null;
      appendAgentMessage(data.reply, data.company);
    } catch (_) {
      appendErrorMessage('Could not connect to the server. Please verify your internet connection and try again.', true);
    } finally {
      setLoading(false);
    }
  }

  // --------------------------------------------------------------------------
  // Event Listeners
  // --------------------------------------------------------------------------
  chatForm.addEventListener('submit', (e) => {
    e.preventDefault();
    sendMessage(messageInput.value);
  });

  // Enter sends, Shift+Enter adds new line
  messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(messageInput.value);
    }
  });

  // Auto-grow textarea up to 4 lines (~120px)
  messageInput.addEventListener('input', () => {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
  });

  // Example Chips Click Handler
  document.addEventListener('click', (e) => {
    const chip = e.target.closest('.chip-ghost');
    if (chip && chip.dataset.url) {
      sendMessage(chip.dataset.url);
    }
  });

  // Reset / New Chat Handler
  resetBtn.addEventListener('click', async () => {
    try {
      await fetch('/api/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      });
    } catch (err) {
      console.warn('Reset request failed:', err);
    }

    // Clear feed & return to empty state
    messagesFeed.innerHTML = '';
    setAppState('empty');
    messageInput.value = '';
    messageInput.style.height = 'auto';
    messageInput.focus();
  });

  // Test hooks for visual inspection and automation
  window.addEventListener('test-render-agent', (e) => {
    if (e.detail) appendAgentMessage(e.detail.text, e.detail.company);
  });
  window.addEventListener('test-render-error', (e) => {
    if (e.detail) appendErrorMessage(e.detail.text, e.detail.isRetryable);
  });

  // Initial focus
  messageInput.focus();
})();
