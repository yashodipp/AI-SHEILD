from __future__ import annotations

import re
from collections import deque
from typing import Any, Deque, Dict, Optional

from backend.services.llm_service import generate_external_reply


MAX_MEMORY_ITEMS = 16
SESSION_MEMORY: Dict[str, Deque[Dict[str, str]]] = {}
ROMAN_HINDI_MARKERS = (
    "namaste",
    "kaise",
    "kya",
    "kyun",
    "mujhe",
    "mera",
    "madad",
    "samjhao",
    "batao",
    "hindi",
    "kripya",
    "shukriya",
    "dhanyavaad",
    "sahi",
    "galat",
)
TOPIC_KEYWORDS = {
    "video": ("video", "deepfake", "clip", "frame", "face", "वीडियो", "डीपफेक"),
    "audio": ("audio", "voice", "speech", "mic", "microphone", "synthetic voice", "voice clone", "ऑडियो", "आवाज", "वॉइस", "माइक"),
    "text": ("news", "text", "article", "headline", "claim", "fake news", "misinformation", "न्यूज़", "समाचार", "टेक्स्ट", "आर्टिकल"),
    "report": ("report", "pdf", "csv", "download", "रिपोर्ट", "डाउनलोड"),
    "dashboard": ("dashboard", "summary", "overview", "counts", "डैशबोर्ड"),
    "history": ("history", "recent", "latest analyses", "past analyses", "analysis history", "logs", "हिस्ट्री", "इतिहास", "लॉग"),
    "feedback": ("feedback", "rating", "bug", "problem", "issue", "फीडबैक", "समस्या"),
    "score": ("score", "confidence", "probability", "result", "explain", "स्कोर", "कॉन्फिडेंस", "प्रायिकता", "रिजल्ट"),
    "assistant": ("assistant", "help", "guide", "chat", "popup", "voice input", "voice output", "असिस्टेंट", "मदद", "गाइड", "चैट"),
}
FOLLOW_UP_MARKERS = (
    "and ",
    "also",
    "what about",
    "aur",
    "uska",
    "iske baare",
    "phir",
    "then",
)
RESULT_KEYWORDS = (
    "latest result",
    "this result",
    "the result",
    "confidence score",
    "fake probability",
    "real probability",
    "what does this mean",
    "explain the result",
    "explain result",
    "summary",
    "status",
)
HISTORY_KEYWORDS = (
    "history",
    "analysis history",
    "recent history",
    "recent analyses",
    "past analyses",
    "analysis logs",
    "latest analysis logs",
    "recent downloads",
)
HELP_KEYWORDS = ("how to use", "how do i use", "guide", "help", "what can you do", "features")
COMPARISON_KEYWORDS = ("difference", "compare", "versus", "vs", "better")
TROUBLESHOOTING_KEYWORDS = (
    "not working",
    "problem",
    "issue",
    "error",
    "failed",
    "network",
    "mic",
    "microphone",
    "speech",
    "upload",
    "wrong result",
    "incorrect",
    "galat",
    "sahi nahi",
)
CLEAR_MEMORY_KEYWORDS = ("clear chat", "forget this", "clear memory", "reset conversation")
DETAIL_MARKERS = ("detail", "detailed", "detail me", "detail mein", "explain", "why", "how", "breakdown")
STEP_MARKERS = ("how", "steps", "process", "workflow", "kaise", "step")


def contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def detect_language(text: str, preferred_language: Optional[str] = None) -> str:
    normalized_language = (preferred_language or "").strip().lower()
    if normalized_language in {"hi", "en"}:
        return normalized_language

    if re.search(r"[\u0900-\u097F]", text):
        return "hi"

    lowered = text.lower()
    if any(marker in lowered for marker in ROMAN_HINDI_MARKERS):
        return "hi"

    return "en"


def localize(language: str, english_text: str, hindi_text: str) -> str:
    return hindi_text if language == "hi" else english_text


def normalize_message(message: str) -> str:
    return " ".join(message.strip().split())


def get_session_memory(session_id: Optional[str]) -> Optional[Deque[Dict[str, str]]]:
    if not session_id:
        return None

    if session_id not in SESSION_MEMORY:
        SESSION_MEMORY[session_id] = deque(maxlen=MAX_MEMORY_ITEMS)
    return SESSION_MEMORY[session_id]


def remember_turn(session_id: Optional[str], role: str, text: str) -> None:
    memory = get_session_memory(session_id)
    if memory is None:
        return
    memory.append({"role": role, "text": text})


def conversation_history(session_id: Optional[str]) -> list[Dict[str, str]]:
    memory = get_session_memory(session_id)
    return list(memory) if memory is not None else []


def clear_memory(session_id: Optional[str]) -> None:
    if session_id and session_id in SESSION_MEMORY:
        SESSION_MEMORY[session_id].clear()


def extract_topic(message: str) -> Optional[str]:
    lowered = message.lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return topic
    return None


def infer_recent_topic(session_id: Optional[str]) -> Optional[str]:
    memory = get_session_memory(session_id)
    if memory is None:
        return None

    for item in reversed(memory):
        if item["role"] == "user":
            topic = extract_topic(item["text"])
            if topic:
                return topic
    return None


def is_follow_up_message(message: str) -> bool:
    lowered = message.lower()
    return len(message.split()) <= 6 or contains_any(lowered, FOLLOW_UP_MARKERS)


def wants_detailed_answer(message: str) -> bool:
    lowered = message.lower()
    return contains_any(lowered, DETAIL_MARKERS)


def mentions_history_request(message: str) -> bool:
    lowered = message.lower()
    if contains_any(lowered, HISTORY_KEYWORDS):
        return True
    if "history" in lowered or "logs" in lowered:
        return True
    if "recent" in lowered and any(word in lowered for word in ("analysis", "analyses", "downloads")):
        return True
    if "latest" in lowered and "analysis" in lowered:
        return True
    return False


def mentions_result_request(message: str, latest_result_available: bool) -> bool:
    if not latest_result_available:
        return False

    lowered = message.lower()
    if contains_any(lowered, RESULT_KEYWORDS):
        return True
    if ("confidence" in lowered or "probability" in lowered or "score" in lowered) and "compare" not in lowered:
        return True
    if "latest" in lowered and "result" in lowered:
        return True
    if "what does it mean" in lowered or "is this fake" in lowered or "is this real" in lowered:
        return True
    return False


def format_reply(intro: str, bullets: Optional[list[str]] = None, closing: Optional[str] = None) -> str:
    parts = [intro]
    for bullet in bullets or []:
        parts.append(f"- {bullet}")
    if closing:
        parts.append(closing)
    return "\n".join(parts)


def friendly_analysis_type(analysis_type: str, language: str) -> str:
    labels = {
        "video": ("video analysis", "वीडियो विश्लेषण"),
        "audio": ("audio analysis", "ऑडियो विश्लेषण"),
        "text": ("news analysis", "टेक्स्ट विश्लेषण"),
    }
    english_label, hindi_label = labels.get(analysis_type, ("analysis", "विश्लेषण"))
    return hindi_label if language == "hi" else english_label


def page_guidance(page_path: str, language: str) -> str:
    if page_path == "/upload.html":
        return localize(
            language,
            "You are on the Analyze page, where Video, Voice, and News modules each support a horizontal upload-or-URL workflow with result cards and downloadable reports.",
            "आप Analyze पेज पर हैं, जहाँ Video, Voice और News modules में horizontal upload या URL workflow, result cards और downloadable reports मिलते हैं।",
        )
    if page_path == "/dashboard.html":
        return localize(
            language,
            "You are on the Dashboard, which shows summary cards, recent activity, and quick navigation to analysis tools.",
            "आप Dashboard पर हैं, जहाँ summary cards, recent activity और analysis tools की quick navigation मिलती है।",
        )
    if page_path == "/history.html":
        return localize(
            language,
            "You are on the History page, where the latest analysis logs and recent report downloads are shown together.",
            "आप History page पर हैं, जहाँ latest analysis logs और recent report downloads साथ में दिखते हैं।",
        )
    if page_path == "/feedback.html":
        return localize(
            language,
            "You are on the Feedback page, where you can submit suggestions, bugs, or experience notes.",
            "आप Feedback page पर हैं, जहाँ आप suggestions, bugs या experience notes भेज सकते हैं।",
        )
    return localize(
        language,
        "You are on the Home page, which introduces AI Shield and links to the main workflow.",
        "आप Home page पर हैं, जहाँ AI Shield का overview और main workflow links मिलते हैं।",
    )


def summarize_analysis_result(result: Dict[str, Any], language: str, detailed: bool = False) -> str:
    analysis_type = friendly_analysis_type(str(result.get("analysis_type", "analysis")), language)
    status = str(result.get("status", "Ready"))
    fake_probability = int(float(result.get("fake_probability", 0)) * 100)
    real_probability = int(float(result.get("real_probability", 0)) * 100)
    confidence = int(float(result.get("confidence", 0)) * 100)
    summary = str(result.get("summary", "")).strip()
    explanation = result.get("explanation") if isinstance(result.get("explanation"), list) else []
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    live_headlines = metadata.get("live_latest_headlines") if isinstance(metadata.get("live_latest_headlines"), list) else []
    live_used = bool(metadata.get("live_lookup_used"))

    if language == "hi":
        bullets = [
            f"स्थिति: {status}",
            f"फेक प्रायिकता: {fake_probability}%",
            f"रियल प्रायिकता: {real_probability}%",
            f"कॉन्फिडेंस: {confidence}%",
        ]
        if summary:
            bullets.append(f"सारांश: {summary}")
        if explanation and not detailed:
            bullets.append(f"मुख्य कारण: {explanation[0]}")
        if detailed:
            for reason in explanation[:3]:
                bullets.append(f"कारण: {reason}")
            if live_used:
                bullets.append("Live news lookup भी इस result में शामिल था।")
            if live_headlines:
                headline = live_headlines[0]
                bullets.append(f"मिलती-जुलती हाल की coverage: {headline.get('title', '')}")
        return format_reply(
            f"यह आपके नवीनतम {analysis_type} का {'detail' if detailed else 'सरल'} breakdown है:",
            bullets,
            "इसका practical मतलब यह है कि system को text में real-world credibility signals ज़्यादा या कम कितने मिले. High-stakes claim के लिए trusted current sources से cross-check करना हमेशा बेहतर रहता है।"
            if detailed
            else "अगर आप चाहें, तो मैं इस परिणाम का मतलब भी आसान भाषा में समझा सकता हूँ।",
        )

    bullets = [
        f"Status: {status}",
        f"Fake probability: {fake_probability}%",
        f"Real probability: {real_probability}%",
        f"Confidence: {confidence}%",
    ]
    if summary:
        bullets.append(f"Summary: {summary}")
    if explanation and not detailed:
        bullets.append(f"Main reason: {explanation[0]}")
    if detailed:
        for reason in explanation[:3]:
            bullets.append(f"Reason: {reason}")
        if live_used:
            bullets.append("This response also included a live news corroboration lookup.")
        if live_headlines:
            headline = live_headlines[0]
            bullets.append(f"Closest recent coverage checked: {headline.get('title', '')}")
    return format_reply(
        f"Here is the latest {analysis_type} {'with a clearer breakdown' if detailed else 'in simple terms'}:",
        bullets,
        "In practical terms, this means the system saw stronger credibility signals than manipulation cues, or the reverse if the fake probability is higher. For important claims, it is still best to cross-check with trusted current reporting."
        if detailed
        else "If you want, I can also explain what this result means practically.",
    )


def summarize_recent_analyses(items: Any, language: str) -> Optional[str]:
    if not isinstance(items, list) or not items:
        return None

    recent_items = items[:4]
    if language == "hi":
        bullets = [
            (
                f"{friendly_analysis_type(str(item.get('analysis_type', 'analysis')), language)} में "
                f"{item.get('input_name', 'item')} का परिणाम {item.get('status', 'Ready')} रहा "
                f"और confidence {int(float(item.get('confidence', 0)) * 100)}% था।"
            )
            for item in recent_items
        ]
        return format_reply(
            "यह आपकी हाल की analysis history है:",
            bullets,
            "अगर आप चाहें, तो मैं इनमें से किसी एक result को detail में explain कर सकता हूँ।",
        )

    bullets = [
        (
            f"{friendly_analysis_type(str(item.get('analysis_type', 'analysis')), language).capitalize()} for "
            f"{item.get('input_name', 'item')} was marked {item.get('status', 'Ready')} "
            f"with {int(float(item.get('confidence', 0)) * 100)}% confidence."
        )
        for item in recent_items
    ]
    return format_reply(
        "Here is your recent analysis history:",
        bullets,
        "If you want, I can explain any one of these results in more detail.",
    )


def build_capabilities_reply(language: str, page_path: str) -> str:
    if language == "hi":
        return format_reply(
            "मैं AI Shield Assistant हूँ, और मैं आपको chat-style help दे सकता हूँ.",
            [
                "वीडियो, ऑडियो और fake news analysis use करने के steps बता सकता हूँ।",
                "Headline/body, URL scan, और image verification ke fake-news workflow ko explain kar सकता हूँ।",
                "Result, fake probability, confidence score और summary समझा सकता हूँ।",
                "Report download, history page, dashboard और website navigation में guide कर सकता हूँ।",
                "Hindi या English में text और voice दोनों में मदद कर सकता हूँ।",
            ],
            page_guidance(page_path, language),
        )

    return format_reply(
        "I am AI Shield Assistant, and I can help in a more conversational way.",
        [
            "I can walk you through the new video, voice, and news modules step by step.",
            "I can explain the upload-versus-URL flow in each analysis section.",
            "I can explain the headline or body check and URL scanner flow for fake news.",
            "I can explain scores, confidence, summaries, and what a result really means.",
            "I can guide you through reports, history, dashboard activity, and report downloads after each analysis.",
            "I can respond in Hindi or English through both chat and voice.",
        ],
        page_guidance(page_path, language),
    )


def build_smalltalk_reply(message: str, language: str) -> Optional[str]:
    lowered = message.lower()

    if re.search(r"^(hello|hi|hey|namaste)\b", lowered):
        return localize(
            language,
            "Hello. I am AI Shield Assistant. I am ready to help with analysis, reports, website guidance, or general AI-related questions.",
            "नमस्ते। मैं AI Shield Assistant हूँ। मैं analysis, reports, website guidance और general AI-related questions में मदद के लिए तैयार हूँ।",
        )

    if any(phrase in lowered for phrase in ("how are you", "kaise ho", "kaise hain")):
        return localize(
            language,
            "I am doing well and ready to help. Tell me what you want to understand, fix, or use in AI Shield.",
            "मैं ठीक हूँ और मदद के लिए तैयार हूँ। आप AI Shield में क्या समझना, ठीक करना या use करना चाहते हैं, बताइए।",
        )

    if any(phrase in lowered for phrase in ("thank you", "thanks", "dhanyavaad", "shukriya")):
        return localize(
            language,
            "You are welcome. If you want, you can continue with another question and I will stay in the same conversation context.",
            "आपका स्वागत है। अगर आप चाहें, तो अगला सवाल पूछ सकते हैं और मैं उसी conversation context में मदद करता रहूँगा।",
        )

    if any(phrase in lowered for phrase in ("who are you", "what are you", "tum kaun", "aap kaun")):
        return localize(
            language,
            "I am AI Shield Assistant, a conversational guide built into this project to help with analysis, reports, troubleshooting, and website usage.",
            "मैं AI Shield Assistant हूँ, जो इस project में built-in conversational guide है और analysis, reports, troubleshooting और website usage में मदद करता है।",
        )

    return None


def build_comparison_reply(message: str, language: str) -> str:
    lowered = message.lower()

    if "probability" in lowered and "confidence" in lowered:
        return localize(
            language,
            "Fake probability tells you how likely the content is to be manipulated. Confidence tells you how strongly the system trusts that prediction. In short, probability is the risk estimate, and confidence is the certainty of the model about that estimate.",
            "Fake probability बताती है कि content के manipulated होने की संभावना कितनी है। Confidence बताता है कि system अपने prediction पर कितना भरोसा करता है। सरल भाषा में, probability risk estimate है और confidence उस estimate पर model की certainty है।",
        )

    if "chat" in lowered and "voice" in lowered:
        return localize(
            language,
            "Chat mode is better when you want to read, copy, or review messages carefully. Voice mode is better for hands-free interaction, quick guidance, and spoken replies. Both use the same assistant logic.",
            "Chat mode तब बेहतर है जब आप messages को पढ़ना, copy करना या ध्यान से review करना चाहते हैं। Voice mode hands-free interaction, quick guidance और spoken replies के लिए बेहतर है। दोनों same assistant logic use करते हैं।",
        )

    if "dashboard" in lowered and "history" in lowered:
        return localize(
            language,
            "Dashboard is for quick overview and current activity. History is for reviewing past analysis logs and recent downloads in a more dedicated way.",
            "Dashboard quick overview और current activity के लिए है। History past analysis logs और recent downloads को dedicated तरीके से review करने के लिए है।",
        )

    return localize(
        language,
        "I can compare features, scores, pages, or analysis types for you. Tell me the two things you want to compare, and I will break down the difference clearly.",
        "मैं आपके लिए features, scores, pages या analysis types compare कर सकता हूँ। आप जिन दो चीज़ों का comparison चाहते हैं, उन्हें बताइए, मैं clear difference समझा दूँगा।",
    )


def build_topic_reply(topic: str, language: str, context: Dict[str, Any], message: str) -> str:
    latest_result = context.get("latest_result") if isinstance(context, dict) else None
    wants_steps = any(token in message.lower() for token in STEP_MARKERS)

    if topic == "video":
        if wants_steps:
            return localize(
                language,
                format_reply(
                    "To analyze a video in AI Shield, follow these steps:",
                    [
                        "Open the Analyze page.",
                        "Use either the video upload card or the video URL card in the horizontal intake row.",
                        "Submit an MP4, MOV, AVI, MKV, or WEBM file, or paste a video link.",
                        "Wait for the system to calculate fake probability, confidence, and suspicious segments.",
                        "Review the explanation card and download the PDF or CSV report if needed.",
                    ],
                ),
                format_reply(
                    "AI Shield में video analyze करने के लिए ये steps follow करें:",
                    [
                        "Analyze page खोलें।",
                        "Horizontal intake row में video upload card या video URL card use करें।",
                        "MP4, MOV, AVI, MKV या WEBM file upload करें, या video link paste करें।",
                        "System के fake probability, confidence और suspicious segments calculate करने का wait करें।",
                        "Explanation card देखें और जरूरत हो तो PDF या CSV report download करें।",
                    ],
                ),
            )
        return localize(
            language,
            "Video analysis now supports both file upload and URL paste. It checks deepfake risk using media-level clues and then returns prediction, confidence, suspicious segments, explanation points, and downloadable reports.",
            "Video analysis अब file upload और URL paste दोनों support करता है। यह media-level clues से deepfake risk check करता है और फिर prediction, confidence, suspicious segments, explanation points और downloadable reports देता है।",
        )

    if topic == "audio":
        if wants_steps:
            return localize(
                language,
                format_reply(
                    "To analyze audio or voice clips, do this:",
                    [
                        "Open the Analyze page.",
                        "Use the voice upload card, the voice URL card, or the microphone recorder.",
                        "Submit a WAV, MP3, AAC, M4A, or OGG file, or paste a direct audio link.",
                        "Wait for prediction, confidence, branch scores, and explanation signals.",
                        "Review the result summary and download the report if you need a record.",
                    ],
                ),
                format_reply(
                    "Audio ya voice clip analyze करने के लिए ये करें:",
                    [
                        "Analyze page खोलें।",
                        "Voice upload card, voice URL card या microphone recorder use करें।",
                        "WAV, MP3, AAC, M4A या OGG file upload करें, या direct audio link paste करें।",
                        "Prediction, confidence, branch scores और explanation signals आने का wait करें।",
                        "Result summary देखें और जरूरत हो तो report download करें।",
                    ],
                ),
            )
        return localize(
            language,
            "Voice analysis now supports upload, URL paste, and microphone recording. It estimates whether a voice is human or synthetic and reports prediction, confidence, reasons, suspicious regions, and report downloads.",
            "Voice analysis अब upload, URL paste और microphone recording support करता है। यह estimate करता है कि voice human है या synthetic, और prediction, confidence, reasons, suspicious regions और report downloads दिखाता है।",
        )

    if topic == "text":
        return localize(
            language,
            "News detection now has two main inputs on the same row: text analysis and news URL analysis. It reviews suspicious wording, credibility indicators, and corroboration hints before showing prediction and report downloads.",
            "News detection में अब same row पर दो main inputs हैं: text analysis और news URL analysis। यह suspicious wording, credibility indicators और corroboration hints को check करता है, फिर prediction और report downloads दिखाता है।",
        )

    if topic == "report":
        return localize(
            language,
            "After each completed video, voice, or news analysis, use the PDF and CSV buttons shown on the result card. You can also review recent downloads on the History page.",
            "हर completed video, voice या news analysis के बाद result card पर दिखने वाले PDF और CSV रिपोर्ट download buttons use करें। Recent downloads को History page पर भी देख सकते हैं।",
        )

    if topic in {"dashboard", "history"}:
        return localize(
            language,
            "Dashboard gives you the quick overview. History gives you a more dedicated review area for latest analysis logs and recent report downloads.",
            "Dashboard आपको quick overview देता है। History latest analysis logs और recent report downloads के लिए dedicated review area देता है।",
        )

    if topic == "feedback":
        return localize(
            language,
            "Use the Feedback page to submit bugs, false results, UI issues, or suggestions. That helps improve both the assistant and the detection workflow.",
            "Feedback page का use bugs, false results, UI issues या suggestions भेजने के लिए करें। इससे assistant और detection workflow दोनों improve होते हैं।",
        )

    if topic == "assistant":
        return build_capabilities_reply(language, str(context.get("current_page", "/")))

    if topic == "score":
        if latest_result:
            return summarize_analysis_result(latest_result, language)
        return localize(
            language,
            "Confidence tells you how sure the system is. Fake probability tells you how likely the content is to be manipulated or misleading.",
            "Confidence बताता है कि system अपने result को लेकर कितना sure है। Fake probability बताती है कि content manipulated या misleading होने की संभावना कितनी है।",
        )

    return build_capabilities_reply(language, str(context.get("current_page", "/")))


def build_troubleshooting_reply(message: str, language: str, page_path: str) -> str:
    lowered = message.lower()

    if any(keyword in lowered for keyword in ("mic", "microphone", "speech", "voice", "network")):
        return localize(
            language,
            format_reply(
                "Let us troubleshoot the voice flow step by step:",
                [
                    "Use Chrome or Edge if possible, because browser speech support is better there.",
                    "Check microphone permission in the browser settings.",
                    "If you are analyzing a voice URL, make sure the pasted link points to a directly reachable audio file or playable page.",
                    "Make sure your internet connection is active, because some browsers use a network speech service.",
                    "If voice still fails, you can continue using typed chat and I can still help normally.",
                ],
                "If you share the exact error text, I can narrow it down further.",
            ),
            format_reply(
                "चलिये voice flow को step by step troubleshoot करते हैं:",
                [
                    "अगर possible हो तो Chrome या Edge use करें, क्योंकि वहाँ browser speech support बेहतर रहती है।",
                    "Browser settings में microphone permission check करें।",
                    "अगर आप voice URL analyze कर रहे हैं, तो pasted link direct audio file या playable page होना चाहिए।",
                    "Internet connection active रखें, क्योंकि कुछ browsers network speech service use करते हैं।",
                    "अगर voice फिर भी fail हो, तो typed chat use करके भी normal help ली जा सकती है।",
                ],
                "अगर exact error text भेजेंगे, तो मैं issue aur narrow down कर दूँगा।",
            ),
        )

    if any(keyword in lowered for keyword in ("wrong result", "incorrect", "galat", "sahi nahi", "fake ko real", "real ko fake")):
        return localize(
            language,
            format_reply(
                "If a result looks wrong, this is the best way to verify it:",
                [
                    "Run the same sample again after the latest model update.",
                    "Check the fake probability and confidence together instead of only the status badge.",
                    "Use clearer source media when possible, because very compressed files can distort the signal.",
                    "Compare the explanation points to see which cues pushed the result.",
                ],
                "If you want, send me the exact result values and I will help interpret them.",
            ),
            format_reply(
                "अगर result गलत लग रहा है, तो इसे verify करने का सबसे अच्छा तरीका ये है:",
                [
                    "Latest model update के बाद same sample को फिर से run करें।",
                    "Sirf status badge नहीं, fake probability और confidence दोनों साथ में देखें।",
                    "जहाँ possible हो, clearer source media use करें, क्योंकि बहुत compressed files signal distort कर सकती हैं।",
                    "Explanation points compare करें कि result किन cues की वजह से आया।",
                ],
                "अगर आप exact result values भेजें, तो मैं उनका मतलब detail में समझा दूँगा।",
            ),
        )

    return localize(
        language,
        f"I can help troubleshoot that. {page_guidance(page_path, language)} Share the exact error, page name, or result you are seeing, and I will guide you step by step.",
        f"मैं इसमें troubleshoot करने में मदद कर सकता हूँ। {page_guidance(page_path, language)} आप exact error, page name या result भेजिए, मैं step by step guide करूँगा।",
    )


def build_general_knowledge_reply(message: str, language: str) -> Optional[str]:
    lowered = message.lower()

    if "deepfake" in lowered:
        return localize(
            language,
            "A deepfake is AI-generated or AI-manipulated media that imitates a real person or event. In practice, people look for unnatural motion, artifacts, inconsistent lip sync, or suspicious compression patterns.",
            "Deepfake वह AI-generated या AI-manipulated media होती है जो किसी असली व्यक्ति या घटना की नकल करती है। Practical level पर लोग unnatural motion, artifacts, inconsistent lip sync और suspicious compression patterns देखते हैं।",
        )

    if "voice clone" in lowered or "synthetic voice" in lowered:
        return localize(
            language,
            "A synthetic voice or voice clone is generated to imitate human speech. Common clues include overly clean delivery, limited natural pauses, and repeated voice texture across different phrases.",
            "Synthetic voice या voice clone ऐसी generated आवाज़ होती है जो human speech की नकल करती है। Common clues में overly clean delivery, natural pauses की कमी और अलग phrases में repeated voice texture शामिल हैं।",
        )

    if "misinformation" in lowered or "fake news" in lowered:
        return localize(
            language,
            "Fake news detection usually looks for sensational claims, weak or missing evidence, suspicious phrasing, and whether the content cites trustworthy sources or data.",
            "Fake news detection आमतौर पर sensational claims, weak या missing evidence, suspicious phrasing और trustworthy sources या data references को देखकर काम करता है।",
        )

    if "confidence" in lowered or "probability" in lowered:
        return localize(
            language,
            "Probability estimates risk. Confidence estimates how strongly the system trusts its own prediction. Reading both together gives a better interpretation than relying on a single label.",
            "Probability risk estimate देती है। Confidence बताती है कि system अपने prediction पर कितना भरोसा करता है। दोनों को साथ में पढ़ना single label देखने से बेहतर interpretation देता है।",
        )

    if lowered.endswith("?") and any(lowered.startswith(prefix) for prefix in ("what", "why", "how", "can", "does", "is", "are")):
        return localize(
            language,
            "I can help with that. If your question is about AI Shield, ask me about analysis, reports, scores, history, voice features, or troubleshooting and I will answer directly. If it is a general AI question, I can explain the concept in simple terms too.",
            "मैं इसमें मदद कर सकता हूँ। अगर आपका सवाल AI Shield के बारे में है, तो analysis, reports, scores, history, voice features या troubleshooting के बारे में पूछिए और मैं सीधे answer दूँगा। अगर यह general AI question है, तो मैं concept को simple terms में भी समझा सकता हूँ।",
        )

    return None


def build_fallback_reply(language: str, page_path: str, session_id: Optional[str]) -> str:
    recent_topic = infer_recent_topic(session_id)
    if recent_topic:
        return localize(
            language,
            f"I can continue from our recent conversation about {recent_topic}. {page_guidance(page_path, language)} If you want, ask me for steps, explanation, troubleshooting, or a simpler summary.",
            f"मैं हमारी recent conversation को {recent_topic} topic से आगे continue कर सकता हूँ। {page_guidance(page_path, language)} अगर चाहें, तो steps, explanation, troubleshooting या simple summary पूछ सकते हैं।",
        )

    return localize(
        language,
        f"I am here to help in a conversational way. {page_guidance(page_path, language)} Ask me anything about analysis, scores, reports, voice features, history, or website usage, and I will answer clearly.",
        f"मैं conversational तरीके से मदद के लिए यहाँ हूँ। {page_guidance(page_path, language)} आप analysis, scores, reports, voice features, history या website usage के बारे में कुछ भी पूछ सकते हैं, और मैं clear answer दूँगा।",
    )


def generate_chat_reply(
    message: str,
    context: Optional[Dict[str, Any]] = None,
    language: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_message = normalize_message(message)
    selected_language = detect_language(normalized_message, language)
    lowered_message = normalized_message.lower()
    safe_context = context or {}
    page_path = str(safe_context.get("current_page", "/"))
    latest_result = safe_context.get("latest_result")
    recent_analyses = safe_context.get("recent_analyses")
    detected_topic = extract_topic(lowered_message)
    prior_conversation = conversation_history(session_id)
    wants_detail = wants_detailed_answer(normalized_message)

    if not detected_topic and is_follow_up_message(normalized_message):
        detected_topic = infer_recent_topic(session_id)

    smalltalk_reply = build_smalltalk_reply(normalized_message, selected_language)
    if contains_any(lowered_message, CLEAR_MEMORY_KEYWORDS):
        clear_memory(session_id)
        reply = localize(
            selected_language,
            "I cleared the conversation memory for this session. You can start fresh anytime.",
            "मैंने इस session की conversation memory clear कर दी है। अब आप fresh start कर सकते हैं।",
        )
        remember_turn(session_id, "assistant", reply)
        return {
            "language": selected_language,
            "reply": reply,
            "session_id": session_id,
        }

    remember_turn(session_id, "user", normalized_message)
    external_reply = generate_external_reply(
        normalized_message,
        language=selected_language,
        context=safe_context,
        conversation=prior_conversation,
    )
    if external_reply:
        remember_turn(session_id, "assistant", external_reply)
        return {
            "language": selected_language,
            "reply": external_reply,
            "session_id": session_id,
        }

    if smalltalk_reply:
        reply = smalltalk_reply
    elif contains_any(lowered_message, HELP_KEYWORDS):
        reply = build_capabilities_reply(selected_language, page_path)
    elif mentions_history_request(lowered_message):
        reply = summarize_recent_analyses(recent_analyses, selected_language) or build_topic_reply("history", selected_language, safe_context, normalized_message)
    elif mentions_result_request(lowered_message, latest_result is not None):
        reply = summarize_analysis_result(latest_result, selected_language, detailed=wants_detail)
    elif contains_any(lowered_message, TROUBLESHOOTING_KEYWORDS):
        reply = build_troubleshooting_reply(normalized_message, selected_language, page_path)
    elif contains_any(lowered_message, COMPARISON_KEYWORDS):
        reply = build_comparison_reply(normalized_message, selected_language)
    elif detected_topic:
        reply = build_topic_reply(detected_topic, selected_language, safe_context, normalized_message)
    else:
        reply = build_general_knowledge_reply(normalized_message, selected_language) or build_fallback_reply(
            selected_language,
            page_path,
            session_id,
        )

    remember_turn(session_id, "assistant", reply)
    return {
        "language": selected_language,
        "reply": reply,
        "session_id": session_id,
    }
