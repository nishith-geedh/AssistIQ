// AssistIQ — App JS (navbar hide-on-scroll, chat persistence, clean UX)

// =========================
// Utility
// =========================
const $ = (q) => document.querySelector(q);

// Year in footer
const yearEl = $("#year");
if (yearEl) {
  yearEl.textContent = new Date().getFullYear();
}

// =========================
// Navbar: auto-hide on scroll
// =========================
(() => {
  const nav = document.querySelector(".nav");
  if (!nav) return;

  let lastY = window.scrollY;
  window.addEventListener(
    "scroll",
    () => {
      const y = window.scrollY;
      if (y > lastY && y > 40) {
        nav.classList.add("nav--hidden"); // scrolling down
      } else {
        nav.classList.remove("nav--hidden"); // scrolling up
      }
      lastY = y;
    },
    { passive: true }
  );
})();

// =========================
// Chat widget
// - Build once on demand
// - Persist messages in sessionStorage
// - Never close on outside click
// =========================

// API endpoint (replace for your deployment)
window.ASSISTIQ_API_ENDPOINT =
  window.ASSISTIQ_API_ENDPOINT ||
  "https://oz5ieiw1zb.execute-api.us-east-1.amazonaws.com/chat";

// Persistent sessionId stored in sessionStorage
let sessionId = sessionStorage.getItem("assistiq_sessionId");
if (!sessionId) {
  sessionId = crypto.randomUUID
    ? crypto.randomUUID()
    : "sess-" + Math.random().toString(36).substr(2, 9);
  sessionStorage.setItem("assistiq_sessionId", sessionId);
}

const fab = $("#chatFab");
const chatContainer = $("#chatContainer");

// Helpers for chat history
function getHistory() {
  try {
    return JSON.parse(sessionStorage.getItem("assistiq_chat_history") || "[]");
  } catch {
    return [];
  }
}
function saveHistory(arr) {
  try {
    sessionStorage.setItem("assistiq_chat_history", JSON.stringify(arr));
  } catch {}
}

// Build chat UI
function buildChat() {
  chatContainer.innerHTML = `
    <section id="chatWidget" class="chat-widget" role="dialog" aria-label="AssistIQ Chat" aria-modal="true" aria-hidden="true">
      <div class="chat-top">
        <div class="chat-title">AssistIQ Chat</div>
        <button id="minChat" class="icon-btn" aria-label="Minimize chat">—</button>
      </div>
      <div id="messages" class="messages" tabindex="0" aria-live="polite"></div>
      <div class="composer">
        <input id="input" placeholder="Type your IT question…" aria-label="Type your message"/>
        <button id="send" class="button primary">Send</button>
      </div>
      <div class="hint">Powered by Amazon Lex. Conversations may be logged to improve the service.</div>
    </section>
  `;

  const chat = $("#chatWidget");
  const minBtn = $("#minChat");
  const inputEl = $("#input");
  const sendBtn = $("#send");
  const messagesEl = $("#messages");

  // Restore previous session messages
  const history = getHistory();
  history.forEach((m) => appendMsg(m.text, m.who, false));

  // Open / Close chat
  function openChat() {
    chat.classList.add("open");
    chat.setAttribute("aria-hidden", "false");
    setTimeout(() => inputEl?.focus(), 180);
  }
  function closeChat() {
    chat.classList.remove("open");
    chat.setAttribute("aria-hidden", "true");
  }

  // Toggle via FAB
  fab.addEventListener("click", () => {
    if (chat.classList.contains("open")) {
      closeChat();
    } else {
      openChat();
    }
  });

  // Minimize button
  minBtn.addEventListener("click", closeChat);

  // Message loop
  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;

    appendMsg(text, "user");
    persist("user", text);
    inputEl.value = "";

    const endpoint = window.ASSISTIQ_API_ENDPOINT;
    if (!endpoint) {
      const msg = "API not configured. Set window.ASSISTIQ_API_ENDPOINT.";
      appendMsg(msg, "bot");
      persist("bot", msg);
      return;
    }

    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, sessionId }),
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => "");
        const msg = `Server error (${res.status}). ${
          errText || "Please try later."
        }`;
        appendMsg(msg, "bot");
        persist("bot", msg);
        return;
      }

      const data = await res.json().catch(() => ({}));
      const answer = data.answer || data.message || "…";
      appendMsg(answer, "bot");
      persist("bot", answer);
    } catch {
      const msg = "Network error. Please try again later.";
      appendMsg(msg, "bot");
      persist("bot", msg);
    }
  }

  // Append message
  function appendMsg(text, who, scroll = true) {
    const el = document.createElement("div");
    el.className = `msg ${who}`;
    el.textContent = text;
    messagesEl.appendChild(el);
    if (scroll) {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  }

  // Save chat history
  function persist(who, text) {
    const arr = getHistory();
    arr.push({ who, text });
    saveHistory(arr);
  }

  // Event bindings
  sendBtn.addEventListener("click", sendMessage);
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendMessage();
  });

  // Keyboard focus trap
  chat.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;

    const focusables = chat.querySelectorAll(
      'button,[href],input,textarea,[tabindex]:not([tabindex="-1"])'
    );
    if (!focusables.length) return;

    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });

  // Open immediately on first build
  openChat();
}

// Build once on first FAB click; afterwards just toggle
fab?.addEventListener("click", () => {
  if (!document.getElementById("chatWidget")) {
    buildChat();
  }
});
