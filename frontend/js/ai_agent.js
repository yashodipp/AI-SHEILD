(function bootstrapAIShieldAssistant() {
  const COMPONENT_PATH = "/components/assistant_popup.html";
  const HISTORY_KEY = "ai-shield-assistant-history";
  const SETTINGS_KEY = "ai-shield-assistant-settings";
  const SESSION_KEY = "ai-shield-assistant-session";
  const DEFAULT_LANGUAGE = "auto";
  const TYPING_DELAY_MS = 12;
  const DEFAULT_FOOTNOTE = "Type or speak in Hindi or English. AI Shield Assistant will reply in the same language.";
  const ENGLISH_WELCOME_TEXT =
    "Hello, I am AI Shield Assistant. Ask me about uploads, scores, reports, dashboard activity, or how to use the website. You can also speak in Hindi or English.";
  const HINDI_WELCOME_TEXT =
    "नमस्ते, मैं AI Shield Assistant हूँ। आप मुझसे uploads, scores, reports, dashboard activity, या website use करने के बारे में पूछ सकते हैं। आप Hindi या English में बोल भी सकते हैं।";

  const state = {
    history: [],
    isBusy: false,
    isGreeting: false,
    isListening: false,
    isMuted: false,
    language: DEFAULT_LANGUAGE,
    activeView: "chat",
    lastReply: "",
    lastReplyLanguage: "en",
    recognition: null,
    sessionId: "",
    pendingSpeech: null,
    pendingTTS: null,
  };

  const ui = {};

  const isPopupOpen = () => Boolean(ui.popup?.classList.contains("open"));

  const safeParse = (rawValue, fallback) => {
    try {
      return rawValue ? JSON.parse(rawValue) : fallback;
    } catch (error) {
      return fallback;
    }
  };

  const getStorage = () => window.sessionStorage;

  const ensureSessionId = () => {
    const storage = getStorage();
    const existingSessionId = storage.getItem(SESSION_KEY);
    if (existingSessionId) {
      return existingSessionId;
    }

    const generatedSessionId = window.crypto?.randomUUID
      ? window.crypto.randomUUID()
      : `assistant-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    storage.setItem(SESSION_KEY, generatedSessionId);
    return generatedSessionId;
  };

  const persistHistory = () => {
    getStorage().setItem(HISTORY_KEY, JSON.stringify(state.history));
  };

  const persistSettings = () => {
    getStorage().setItem(
      SETTINGS_KEY,
      JSON.stringify({
        isMuted: state.isMuted,
        language: state.language,
      }),
    );
  };

  const resolveAssistantLanguage = () => window.AIShieldVoice?.resolveOutputLanguage?.(state.language) || "en";

  const defaultWelcomeMessage = (language = resolveAssistantLanguage()) => ({
    role: "assistant",
    text: language === "hi" ? HINDI_WELCOME_TEXT : ENGLISH_WELCOME_TEXT,
  });

  const isWelcomeOnlyHistory = (history) =>
    Array.isArray(history) &&
    history.length === 1 &&
    history[0]?.role === "assistant" &&
    [ENGLISH_WELCOME_TEXT, HINDI_WELCOME_TEXT].includes(history[0]?.text);

  const loadState = () => {
    const storage = getStorage();
    const savedSettings = safeParse(storage.getItem(SETTINGS_KEY), {});
    state.history = safeParse(storage.getItem(HISTORY_KEY), []);
    state.isMuted = Boolean(savedSettings.isMuted);
    state.language = savedSettings.language || DEFAULT_LANGUAGE;
    state.sessionId = ensureSessionId();

    if (isWelcomeOnlyHistory(state.history)) {
      state.history = [];
      persistHistory();
    }
  };

  const createMessageElement = (entry) => {
    const bubble = document.createElement("article");
    bubble.className = `assistant-message ${entry.role}`;

    const meta = document.createElement("div");
    meta.className = "assistant-message-meta";
    meta.textContent = entry.role === "user" ? "You" : entry.role === "system" ? "Notice" : "AI Shield Assistant";

    const body = document.createElement("div");
    body.className = "assistant-message-text";
    body.textContent = entry.text;

    bubble.append(meta, body);
    return bubble;
  };

  const createPendingElement = () => {
    const bubble = document.createElement("article");
    bubble.className = "assistant-message assistant pending";

    const meta = document.createElement("div");
    meta.className = "assistant-message-meta";
    meta.textContent = "AI Shield Assistant";

    const loader = document.createElement("div");
    loader.className = "assistant-message-text assistant-bubble-loader";
    loader.innerHTML = "<span></span><span></span><span></span>";

    bubble.append(meta, loader);
    return bubble;
  };

  const scrollChatToLatest = (behavior) => {
    window.requestAnimationFrame(() => {
      ui.chatLog.scrollTo({
        top: ui.chatLog.scrollHeight,
        behavior: behavior || "smooth",
      });
    });
  };

  const renderHistory = () => {
    ui.chatLog.innerHTML = "";
    state.history.forEach((entry) => {
      ui.chatLog.appendChild(createMessageElement(entry));
    });
    renderMessageCenter();
    scrollChatToLatest("auto");
  };

  const appendHistoryEntry = (entry) => {
    state.history.push(entry);
    persistHistory();
    ui.chatLog.appendChild(createMessageElement(entry));
    renderMessageCenter();
    scrollChatToLatest();
  };

  const setFootnote = (message) => {
    ui.footnote.textContent = message;
  };

  const setStatus = (message) => {
    ui.statusPill.textContent = message;
  };

  const updateLanguageUI = () => {
    const labels = {
      auto: "Auto",
      en: "English",
      hi: "Hindi",
    };

    ui.languageLabel.textContent = labels[state.language] || "Auto";

    ui.languageButtons.forEach((button) => {
      const isActive = button.dataset.language === state.language;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });
  };

  const updateMuteUI = () => {
    ui.muteToggle.textContent = state.isMuted ? "Voice Off" : "Voice On";
    ui.muteToggle.setAttribute("aria-pressed", String(!state.isMuted));
  };

  const updateListeningUI = () => {
    ui.wave.classList.toggle("active", state.isListening);
    ui.micButton.classList.toggle("listening", state.isListening);
    ui.micButton.textContent = state.isListening ? "Stop" : "Mic";
  };

  const togglePopup = (forceState) => {
    const shouldOpen = typeof forceState === "boolean" ? forceState : !ui.popup.classList.contains("open");
    ui.popup.classList.toggle("open", shouldOpen);
    ui.launcher.classList.toggle("is-open", shouldOpen);
    ui.popup.setAttribute("aria-hidden", String(!shouldOpen));
    ui.launcher.setAttribute("aria-expanded", String(shouldOpen));
    document.body.classList.toggle("assistant-open", shouldOpen);

    if (shouldOpen) {
      ui.input.focus();
      scrollChatToLatest("auto");
      maybePlayWelcomeMessage();
    } else {
      window.AIShieldVoice?.cancel?.();
      clearPendingSpeech();
      if (state.isListening) {
        stopListening();
      }
      setStatus("Ready");
      setFootnote(DEFAULT_FOOTNOTE);
    }
  };

  const typeText = async (element, text) => {
    element.textContent = "";
    for (const character of text) {
      element.textContent += character;
      scrollChatToLatest();
      await new Promise((resolve) => window.setTimeout(resolve, TYPING_DELAY_MS));
    }
  };

  const getChatContext = () => ({
    current_page: window.location.pathname,
    latest_result: window.AIShieldState?.latestResult || null,
  });

  const createMessageCard = (entry) => {
    const card = document.createElement("article");
    card.className = "assistant-message-card";

    const title = document.createElement("strong");
    title.textContent = entry.role === "user" ? "Your message" : entry.role === "system" ? "System notice" : "Assistant reply";

    const body = document.createElement("p");
    body.textContent = entry.text;

    const type = document.createElement("small");
    type.textContent = entry.role === "user" ? "Chat input" : entry.role === "system" ? "Status update" : "AI Shield Assistant";

    card.append(title, body, type);
    return card;
  };

  const renderMessageCenter = () => {
    if (!ui.messageCenter) {
      return;
    }

    ui.messageCenter.innerHTML = "";
    const recentMessages = [...state.history].slice(-12).reverse();

    if (!recentMessages.length) {
      const empty = document.createElement("article");
      empty.className = "assistant-message-card";
      empty.innerHTML = "<p>No messages yet. Start chatting with AI Shield Assistant.</p>";
      ui.messageCenter.appendChild(empty);
      return;
    }

    recentMessages.forEach((entry) => {
      ui.messageCenter.appendChild(createMessageCard(entry));
    });
  };

  const clearPendingSpeech = () => {
    state.pendingSpeech = null;
    state.pendingTTS = null;
  };

  const queueSpeechRetry = (text, tts) => {
    state.pendingSpeech = text;
    state.pendingTTS = tts;
    setStatus("Voice ready");
    setFootnote("Tap anywhere or send a message once if browser voice playback did not start automatically.");
  };

  const flushPendingSpeech = async () => {
    if (state.isMuted || !state.pendingSpeech || !window.AIShieldVoice?.speak || !isPopupOpen()) {
      return;
    }

    const pendingText = state.pendingSpeech;
    const pendingTTS = state.pendingTTS;
    clearPendingSpeech();
    await speakReply(pendingText, pendingTTS);
  };

  const switchView = (view) => {
    state.activeView = view === "messages" ? "messages" : "chat";
    const isChatView = state.activeView === "chat";

    ui.chatPanel.classList.toggle("is-active", isChatView);
    ui.chatPanel.hidden = !isChatView;
    ui.messagePanel.classList.toggle("is-active", !isChatView);
    ui.messagePanel.hidden = isChatView;

    ui.viewButtons.forEach((button) => {
      const isActive = button.dataset.view === state.activeView;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });
  };

  const maybePlayWelcomeMessage = async () => {
    if (state.isGreeting || state.history.length || !ui.chatLog || !isPopupOpen()) {
      return;
    }

    state.isGreeting = true;
    switchView("chat");
    setStatus("Greeting");
    setFootnote("AI Shield Assistant is welcoming you.");

    const welcomeLanguage = resolveAssistantLanguage();
    const welcomeEntry = defaultWelcomeMessage(welcomeLanguage);
    const greetingElement = createMessageElement({ role: "assistant", text: "" });
    const greetingTextNode = greetingElement.querySelector(".assistant-message-text");
    ui.chatLog.appendChild(greetingElement);
    scrollChatToLatest("auto");

    try {
      const greetingSpeech = speakReply(
        welcomeEntry.text,
        window.AIShieldVoice?.getPreferredTTS?.(welcomeLanguage) || {
          lang: welcomeLanguage === "hi" ? "hi-IN" : "en-US",
          rate: 0.92,
          pitch: 1.02,
          gender: "female",
          voice_hints:
            welcomeLanguage === "hi"
              ? ["Google हिन्दी", "Google Hindi", "Microsoft Heera", "Veena", "Lekha"]
              : ["Samantha", "Google UK English Female", "Google US English", "Microsoft Aria", "Microsoft Jenny"],
          provider_hints: ["google", "microsoft", "apple"],
        },
      );
      await typeText(greetingTextNode, welcomeEntry.text);
      state.history.push(welcomeEntry);
      state.lastReply = welcomeEntry.text;
      state.lastReplyLanguage = welcomeLanguage;
      persistHistory();
      renderMessageCenter();
      setStatus("Ready");
      setFootnote(DEFAULT_FOOTNOTE);
      state.isGreeting = false;
      void greetingSpeech;
    } catch (error) {
      greetingTextNode.textContent = welcomeEntry.text;
      state.history.push(welcomeEntry);
      persistHistory();
      renderMessageCenter();
      setStatus("Ready");
      setFootnote(DEFAULT_FOOTNOTE);
      state.isGreeting = false;
    } finally {
      scrollChatToLatest();
    }
  };

  const speakReply = async (text, tts) => {
    if (state.isMuted || state.isListening || !window.AIShieldVoice?.speak || !isPopupOpen()) {
      return;
    }

    const spoken = await window.AIShieldVoice.speak(text, tts, {
      onstart() {
        if (!isPopupOpen()) {
          window.AIShieldVoice?.cancel?.();
          return;
        }
        clearPendingSpeech();
        setStatus("Speaking");
      },
      onend() {
        setStatus("Ready");
        setFootnote(DEFAULT_FOOTNOTE);
      },
      onerror() {
        setStatus("Ready");
      },
    });

    if (!spoken && text) {
      queueSpeechRetry(text, tts);
    }
  };

  const showSystemNotice = (message) => {
    appendHistoryEntry({ role: "system", text: message });
  };

  const sendMessage = async (message, source) => {
    const trimmedMessage = message.trim();
    if (!trimmedMessage || state.isBusy || state.isGreeting) {
      if (!trimmedMessage) {
        setStatus("Type or speak a message first");
      } else if (state.isGreeting) {
        setStatus("Greeting in progress");
      }
      return;
    }

    switchView("chat");
    state.isBusy = true;
    appendHistoryEntry({ role: "user", text: trimmedMessage });
    ui.input.value = "";
    ui.input.focus();
    setStatus(source === "voice" ? "Processing voice message" : "Thinking");
    setFootnote("AI Shield Assistant is preparing a reply.");

    const pendingElement = createPendingElement();
    ui.chatLog.appendChild(pendingElement);
    scrollChatToLatest();

    try {
      const response = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmedMessage,
          language: state.language,
          session_id: state.sessionId,
          context: getChatContext(),
        }),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "The assistant could not reply right now.");
      }

      pendingElement.classList.remove("pending");
      const textNode = pendingElement.querySelector(".assistant-message-text");
      const allowVoiceReply = isPopupOpen();
      const replySpeech = allowVoiceReply ? speakReply(payload.reply, payload.tts) : null;
      await typeText(textNode, payload.reply);

      state.lastReply = payload.reply;
      state.lastReplyLanguage = payload.language || "en";
      state.history.push({ role: "assistant", text: payload.reply });
      persistHistory();
      renderMessageCenter();
      state.isBusy = false;
      ui.input.focus();
      setStatus("Ready");
      setFootnote(DEFAULT_FOOTNOTE);
      void replySpeech;
    } catch (error) {
      pendingElement.remove();
      appendHistoryEntry({
        role: "system",
        text: error.message || "The assistant is temporarily unavailable.",
      });
      setStatus("Error");
      setFootnote("There was a problem reaching the assistant. Please try again.");
    } finally {
      if (state.isBusy) {
        state.isBusy = false;
      }
      scrollChatToLatest();
    }
  };

  const speechRecognitionError = (errorCode) => {
    const messages = {
      "audio-capture": "Microphone input was not detected.",
      "network": "Browser speech service connect nahi ho paya. Internet, mic permission, aur Chrome या Edge try karein. Aap typed chat bhi use kar sakte hain.",
      "not-allowed": "Microphone permission is blocked in this browser.",
      "service-not-allowed": "Speech recognition service is not available here.",
      "no-speech": "No speech was detected. Please try again.",
      "language-not-supported": "The selected language is not supported for voice input.",
    };

    return messages[errorCode] || "Speech recognition could not start.";
  };

  const recognitionLanguage = () => {
    if (state.language === "hi") {
      return "hi-IN";
    }
    if (state.language === "en") {
      return "en-US";
    }

    const browserLanguages = [navigator.language, ...(navigator.languages || [])]
      .filter(Boolean)
      .map((value) => String(value).toLowerCase());

    if (browserLanguages.some((value) => value.startsWith("hi"))) {
      return "hi-IN";
    }

    return "en-US";
  };

  const stopListening = () => {
    if (state.recognition) {
      state.recognition.stop();
    }
    state.isListening = false;
    updateListeningUI();
  };

  const startListening = () => {
    if (!window.AIShieldVoice?.isRecognitionSupported?.()) {
      showSystemNotice("Voice input is not supported in this browser. Please use Chrome, Edge, or another browser with Web Speech API support.");
      setStatus("Mic unsupported");
      return;
    }

    if (state.isListening) {
      stopListening();
      return;
    }

    window.AIShieldVoice?.cancel?.();
    clearPendingSpeech();

    const beginRecognition = async () => {
      const micAccess = await window.AIShieldVoice.requestMicrophoneAccess?.();
      if (micAccess && micAccess.ok === false) {
        const deniedMessage =
          micAccess.reason === "NotAllowedError"
            ? "Microphone permission allow karein, phir dobara try karein."
            : "Microphone access available nahi hai. Browser settings check karein.";
        showSystemNotice(deniedMessage);
        setStatus("Mic blocked");
        setFootnote(deniedMessage);
        return;
      }

      const recognition = window.AIShieldVoice.createRecognition();
      if (!recognition) {
        showSystemNotice("Voice input is not available right now.");
        setStatus("Mic unavailable");
        return;
      }

      let finalTranscript = "";
      let shouldSubmit = false;
      let recognitionErrorCode = "";

      state.recognition = recognition;
      recognition.lang = recognitionLanguage();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;

      recognition.onstart = () => {
        state.isListening = true;
        updateListeningUI();
        setStatus("Listening");
        setFootnote("Listening for Hindi or English speech.");
      };

      recognition.onresult = (event) => {
        const spokenParts = [];
        for (const result of event.results) {
          spokenParts.push(result[0].transcript);
        }

        finalTranscript = spokenParts.join(" ").trim();
        ui.input.value = finalTranscript;

        const latestResult = event.results[event.results.length - 1];
        shouldSubmit = Boolean(latestResult?.isFinal && finalTranscript);
      };

      recognition.onerror = (event) => {
        recognitionErrorCode = event.error || "";
        const message = speechRecognitionError(recognitionErrorCode);
        showSystemNotice(message);
        setStatus("Voice error");
        setFootnote(message);
        state.isListening = false;
        state.recognition = null;
        updateListeningUI();
      };

      recognition.onend = () => {
        state.isListening = false;
        state.recognition = null;
        updateListeningUI();

        if (shouldSubmit && finalTranscript) {
          sendMessage(finalTranscript, "voice");
        } else if (!recognitionErrorCode) {
          setStatus("Ready");
          setFootnote(DEFAULT_FOOTNOTE);
        }
      };

      try {
        recognition.start();
      } catch (error) {
        const message = "Microphone start nahi ho paya. Browser reload karke dubara try karein.";
        showSystemNotice(message);
        setStatus("Mic error");
        setFootnote(message);
      }
    };

    beginRecognition();
  };

  const clearConversation = () => {
    window.AIShieldVoice?.cancel?.();
    stopListening();
    state.history = [];
    state.sessionId = window.crypto?.randomUUID
      ? window.crypto.randomUUID()
      : `assistant-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

    getStorage().setItem(SESSION_KEY, state.sessionId);
    persistHistory();
    renderHistory();
    setStatus("Ready");
    setFootnote("Conversation cleared.");

    if (ui.popup?.classList.contains("open")) {
      maybePlayWelcomeMessage();
    }
  };

  const mountAssistant = async () => {
    if (document.getElementById("assistantRoot")) {
      return;
    }

    const response = await fetch(COMPONENT_PATH);
    if (!response.ok) {
      throw new Error("Unable to load AI Shield Assistant.");
    }

    const host = document.createElement("div");
    host.innerHTML = await response.text();
    document.body.appendChild(host.firstElementChild);
  };

  const bindUI = () => {
    ui.launcher = document.getElementById("assistantLauncher");
    ui.popup = document.getElementById("assistantPopup");
    ui.overlay = document.getElementById("assistantOverlay");
    ui.closeButton = document.getElementById("assistantCloseBtn");
    ui.chatLog = document.getElementById("assistantChatLog");
    ui.form = document.getElementById("assistantForm");
    ui.input = document.getElementById("assistantInput");
    ui.micButton = document.getElementById("assistantMicBtn");
    ui.sendButton = document.getElementById("assistantSendBtn");
    ui.statusPill = document.getElementById("assistantStatusPill");
    ui.footnote = document.getElementById("assistantFootnote");
    ui.wave = document.getElementById("assistantWave");
    ui.muteToggle = document.getElementById("assistantMuteToggle");
    ui.clearButton = document.getElementById("assistantClearBtn");
    ui.languageLabel = document.getElementById("assistantLanguageLabel");
    ui.languageButtons = Array.from(document.querySelectorAll(".assistant-language-btn"));
    ui.promptButtons = Array.from(document.querySelectorAll(".assistant-prompt"));
    ui.viewButtons = Array.from(document.querySelectorAll(".assistant-view-btn"));
    ui.chatPanel = document.getElementById("assistantChatPanel");
    ui.messagePanel = document.getElementById("assistantMessagePanel");
    ui.messageCenter = document.getElementById("assistantMessageCenter");

    ui.launcher.addEventListener("click", () => togglePopup());
    ui.overlay.addEventListener("click", () => togglePopup(false));
    ui.closeButton.addEventListener("click", () => togglePopup(false));
    ui.micButton.addEventListener("click", startListening);
    ui.clearButton.addEventListener("click", clearConversation);
    ui.viewButtons.forEach((button) => {
      button.addEventListener("click", () => {
        switchView(button.dataset.view);
      });
    });

    ui.muteToggle.addEventListener("click", () => {
      state.isMuted = !state.isMuted;
      persistSettings();
      updateMuteUI();
      if (state.isMuted) {
        window.AIShieldVoice?.cancel?.();
      }
    });

    ui.languageButtons.forEach((button) => {
      button.addEventListener("click", () => {
        state.language = button.dataset.language || DEFAULT_LANGUAGE;
        persistSettings();
        updateLanguageUI();
      });
    });

    ui.promptButtons.forEach((button) => {
      button.addEventListener("click", () => {
        togglePopup(true);
        sendMessage(button.dataset.prompt || button.textContent || "", "prompt");
      });
    });

    ui.form.addEventListener("submit", (event) => {
      event.preventDefault();
      sendMessage(ui.input.value, "text");
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && ui.popup.classList.contains("open")) {
        togglePopup(false);
      }
    });

    const unlockSpeech = () => {
      flushPendingSpeech();
    };
    document.addEventListener("pointerdown", unlockSpeech, { passive: true });
    document.addEventListener("keydown", unlockSpeech);

  };

  document.addEventListener("DOMContentLoaded", async () => {
    loadState();

    try {
      await mountAssistant();
      bindUI();
      renderHistory();
      updateLanguageUI();
      updateMuteUI();
      updateListeningUI();
      switchView(state.activeView);
      setStatus("Ready");
      setFootnote(DEFAULT_FOOTNOTE);
    } catch (error) {
      console.error(error);
    }
  });
})();
