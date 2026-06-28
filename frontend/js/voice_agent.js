(function createAIShieldVoiceHelpers() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis || null;
  const FEMALE_VOICE_MARKERS = [
    "female",
    "samantha",
    "zira",
    "ava",
    "karen",
    "aria",
    "jenny",
    "sonia",
    "emma",
    "serena",
    "allison",
    "susan",
    "hazel",
    "victoria",
    "moira",
    "tessa",
    "veena",
    "heera",
    "lekha",
    "google hindi",
    "google हिन्दी",
    "uk english female",
  ];
  const TTS_PRESETS = {
    en: {
      lang: "en-US",
      voice_hints: [
        "Samantha",
        "Google UK English Female",
        "Google US English",
        "Google UK English",
        "Microsoft Aria",
        "Microsoft Jenny",
        "Microsoft Sonia",
        "Zira",
        "Ava",
        "Karen",
      ],
      provider_hints: ["google", "microsoft", "apple"],
      gender: "female",
      rate: 0.92,
      pitch: 1.02,
    },
    hi: {
      lang: "hi-IN",
      voice_hints: ["Google हिन्दी", "Google Hindi", "Microsoft Heera", "Veena", "Lekha"],
      provider_hints: ["google", "microsoft", "apple"],
      gender: "female",
      rate: 0.92,
      pitch: 1.02,
    },
  };
  let cachedVoices = [];

  const syncVoices = () => {
    if (!synth) {
      cachedVoices = [];
      return cachedVoices;
    }

    cachedVoices = synth.getVoices();
    return cachedVoices;
  };

  if (synth) {
    syncVoices();
    if (typeof synth.addEventListener === "function") {
      synth.addEventListener("voiceschanged", syncVoices);
    } else {
      synth.onvoiceschanged = syncVoices;
    }
  }

  const normalizeHints = (tts) => {
    if (!tts) {
      return [];
    }

    const hints = [];
    if (Array.isArray(tts.voice_hints)) {
      hints.push(...tts.voice_hints);
    }
    if (tts.voice_hint) {
      hints.push(tts.voice_hint);
    }
    return hints.map((value) => String(value).toLowerCase());
  };

  const normalizeProviderHints = (tts) => {
    if (!tts || !Array.isArray(tts.provider_hints)) {
      return [];
    }
    return tts.provider_hints.map((value) => String(value).toLowerCase());
  };

  const resolveOutputLanguage = (language) => {
    if (language === "hi" || language === "en") {
      return language;
    }

    const browserLanguages = [navigator.language, ...(navigator.languages || [])]
      .filter(Boolean)
      .map((value) => String(value).toLowerCase());

    return browserLanguages.some((value) => value.startsWith("hi")) ? "hi" : "en";
  };

  const getPreferredTTS = (language) => ({ ...TTS_PRESETS[resolveOutputLanguage(language)] });

  const voiceLabel = (voice) => `${voice.name} ${voice.voiceURI}`.toLowerCase();
  const voiceLanguage = (voice) => String(voice?.lang || "").toLowerCase();

  const voiceScore = (voice, tts) => {
    const label = voiceLabel(voice);
    const language = (tts?.lang || "").toLowerCase();
    const languagePrefix = language.split("-")[0];
    const hints = normalizeHints(tts);
    const providerHints = normalizeProviderHints(tts);

    let score = 0;
    if (language && voice.lang.toLowerCase() === language) {
      score += 14;
    } else if (languagePrefix && voice.lang.toLowerCase().startsWith(languagePrefix)) {
      score += 10;
    } else if (languagePrefix) {
      score -= 24;
    }

    if (hints.some((hint) => label.includes(hint))) {
      score += 18;
    }

    if (providerHints.some((hint) => label.includes(hint))) {
      score += 4;
    }

    if (tts?.gender === "female" && FEMALE_VOICE_MARKERS.some((marker) => label.includes(marker))) {
      score += 7;
    }

    if (voice.default) {
      score += 1;
    }

    return score;
  };

  const pickVoice = (tts) => {
    const voices = syncVoices();
    if (!voices.length) {
      return null;
    }

    const language = (tts?.lang || "").toLowerCase();
    const languagePrefix = language.split("-")[0];
    const languageMatchedVoices = languagePrefix
      ? voices.filter((voice) => voiceLanguage(voice).startsWith(languagePrefix))
      : [];
    const candidateVoices = languageMatchedVoices.length ? languageMatchedVoices : voices;

    const rankedVoices = candidateVoices
      .map((voice) => ({ voice, score: voiceScore(voice, tts) }))
      .sort((first, second) => second.score - first.score);

    return rankedVoices[0]?.voice || candidateVoices[0] || voices[0];
  };

  const speak = (text, tts, lifecycle) =>
    new Promise((resolve) => {
      if (!synth || !text || !text.trim()) {
        resolve(false);
        return;
      }

      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = tts?.lang || "en-US";
      utterance.rate = Number(tts?.rate || 0.96);
      utterance.pitch = Number(tts?.pitch || 1);

      const selectedVoice = pickVoice(tts);
      if (selectedVoice) {
        utterance.voice = selectedVoice;
      }

      utterance.onstart = () => lifecycle?.onstart?.();
      utterance.onend = () => {
        lifecycle?.onend?.();
        resolve(true);
      };
      utterance.onerror = () => {
        lifecycle?.onerror?.();
        resolve(false);
      };

      synth.cancel();
      synth.speak(utterance);
    });

  const requestMicrophoneAccess = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      return { ok: true, unsupported: true };
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      return { ok: true };
    } catch (error) {
      return {
        ok: false,
        reason: error?.name || "not-allowed",
      };
    }
  };

  window.AIShieldVoice = {
    cancel() {
      synth?.cancel();
    },
    createRecognition() {
      return Recognition ? new Recognition() : null;
    },
    getVoices() {
      return syncVoices();
    },
    getPreferredTTS,
    isRecognitionSupported() {
      return Boolean(Recognition);
    },
    requestMicrophoneAccess,
    resolveOutputLanguage,
    speak,
  };
})();
