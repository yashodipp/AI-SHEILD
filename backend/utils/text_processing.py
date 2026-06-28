from __future__ import annotations

import re
from typing import List, Union

WORD_PATTERN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|[\u0900-\u097F]+")


SUSPICIOUS_TERMS = {
    "alert",
    "click here",
    "conspiracy",
    "exclusive",
    "forward",
    "fraud",
    "hidden",
    "shocking",
    "rumor",
    "viral",
    "secret",
    "exposed",
    "hoax",
    "leaked",
    "scam",
    "miracle",
    "unbelievable",
    "100% true",
    "breaking",
    "truth",
    "urgent",
    "अचानक",
    "अफवाह",
    "आश्चर्यजनक",
    "उजागर",
    "गुप्त",
    "चमत्कारी",
    "चौंकाने",
    "तुरंत",
    "दावा",
    "फॉरवर्ड",
    "बंद",
    "ब्रेकिंग",
    "भ्रामक",
    "वायरल",
    "लीक",
    "सच्चाई",
    "शेयर",
    "छिपा",
}

CREDIBLE_TERMS = {
    "advisory",
    "agency",
    "report",
    "analysis",
    "verified",
    "source",
    "data",
    "official",
    "statement",
    "evidence",
    "research",
    "methodology",
    "references",
    "bulletin",
    "confirmed",
    "published",
    "briefing",
    "financial",
    "quarterly",
    "study",
    "peer-reviewed",
    "peer",
    "reviewed",
    "laboratory",
    "lab",
    "investigation",
    "investigators",
    "researchers",
    "cited",
    "supporting",
    "sources",
    "statement",
    "आंकड़े",
    "आधिकारिक",
    "अध्ययन",
    "अनुसंधान",
    "जांच",
    "जारी",
    "डेटा",
    "प्रकाशित",
    "प्रमाण",
    "प्रेस",
    "बयान",
    "मंत्रालय",
    "रिपोर्ट",
    "रेल",
    "विज्ञप्ति",
    "सलाह",
    "सरकार",
    "साक्ष्य",
    "स्रोत",
}

SUSPICIOUS_PHRASES = {
    "without any source",
    "they don't want you to know",
    "media does not want you to know",
    "share before it is deleted",
    "whatsapp forward",
    "forwarded message",
    "secret source",
    "miracle cure",
    "100% true",
    "no official notice",
    "no source is provided",
    "no verified source",
    "you will not believe",
    "hidden truth",
    "viral post claims",
    "rumor says",
    "कोई आधिकारिक सूचना नहीं",
    "कोई स्रोत नहीं",
    "गुप्त तरीके से",
    "चमत्कारी इलाज",
    "तुरंत शेयर करें",
    "वायरल पोस्ट में दावा",
    "सोशल मीडिया पर दावा",
}

ABSOLUTIST_TERMS = {
    "all",
    "always",
    "everyone",
    "everything",
    "guaranteed",
    "immediately",
    "must",
    "never",
    "nobody",
    "prove",
}

EVIDENCE_PHRASES = {
    "according to",
    "official statement",
    "supporting data",
    "named sources",
    "peer-reviewed study",
    "peer reviewed study",
    "published study",
    "multiple agencies",
    "press release",
    "court filing",
    "methodology and references",
    "financial statement",
    "official bulletin",
    "official briefing",
    "peer-reviewed research",
    "आधिकारिक बयान",
    "आधिकारिक प्रेस नोट",
    "आधिकारिक सलाह",
    "आधिकारिक प्रेस विज्ञप्ति",
    "आधिकारिक विज्ञप्ति",
    "सहायक आंकड़े",
    "प्रेस नोट",
    "प्रेस विज्ञप्ति",
    "पीयर-रिव्यू अध्ययन",
}

MANIPULATION_PHRASES = {
    "without any source",
    "secret source",
    "miracle cure",
    "you will not believe",
    "hidden truth",
    "media does not want you to know",
    "share before it is deleted",
    "viral post claims",
    "whatsapp forward",
    "forwarded message",
    "no official notice",
    "no source is provided",
    "rumor says",
    "कोई आधिकारिक सूचना नहीं",
    "कोई स्रोत नहीं",
    "गुप्त तरीके से",
    "चमत्कारी इलाज",
    "तुरंत शेयर करें",
    "सोशल मीडिया पर दावा",
    "वायरल पोस्ट में दावा",
}

ATTRIBUTION_TERMS = {
    "according",
    "announced",
    "briefed",
    "cited",
    "confirmed",
    "issued",
    "published",
    "released",
    "reported",
    "said",
    "stated",
    "कहा",
    "जारी",
    "जारी किया",
    "घोषणा",
    "प्रकाशित",
    "बताया",
    "रिपोर्ट",
}

INSTITUTION_TERMS = {
    "agency",
    "bank",
    "commission",
    "company",
    "court",
    "department",
    "government",
    "health ministry",
    "hospital",
    "laboratory",
    "lab",
    "ministry",
    "police",
    "researchers",
    "scientists",
    "spokesperson",
    "state agency",
    "university",
    "आरबीआई",
    "कंपनी",
    "कोर्ट",
    "पुलिस",
    "भारत सरकार",
    "भारतीय रेल",
    "भारतीय रिजर्व बैंक",
    "मंत्रालय",
    "रिजर्व बैंक",
    "सरकार",
    "स्वास्थ्य मंत्रालय",
}

NEGATED_CREDIBILITY_PATTERNS = (
    "no official",
    "no verified",
    "without evidence",
    "without proof",
    "without source",
    "without any source",
    "no source",
    "not verified",
    "unverified",
    "कोई आधिकारिक",
    "कोई स्रोत नहीं",
    "बिना प्रमाण",
    "बिना सबूत",
    "बिना स्रोत",
    "स्रोत नहीं",
    "आधिकारिक सूचना नहीं",
)


def non_negated_matches(lowered: str, candidates: set[str]) -> list[str]:
    word_set = {word.lower() for word in extract_words(lowered)}
    matches: list[str] = []
    for term in candidates:
        if not term_present(lowered, word_set, term):
            continue
        negated = False
        for pattern in NEGATED_CREDIBILITY_PATTERNS:
            if f"{pattern} {term}" in lowered or f"{pattern} {term.replace(' ', ' ')}" in lowered:
                negated = True
                break
        if term == "official" and "no official" in lowered:
            negated = True
        if term == "verified" and ("not verified" in lowered or "unverified" in lowered):
            negated = True
        if term == "source" and ("no source" in lowered or "without source" in lowered or "without any source" in lowered):
            negated = True
        if term == "आधिकारिक" and ("कोई आधिकारिक" in lowered or "आधिकारिक सूचना नहीं" in lowered):
            negated = True
        if term == "स्रोत" and ("कोई स्रोत नहीं" in lowered or "बिना स्रोत" in lowered or "स्रोत नहीं" in lowered):
            negated = True
        if not negated:
            matches.append(term)
    return matches


def extract_words(text: str) -> list[str]:
    return WORD_PATTERN.findall(text)


def term_present(lowered: str, word_set: set[str], term: str) -> bool:
    if " " in term or "-" in term or "%" in term:
        return term in lowered
    return term in word_set


def extract_text_signals(text: str) -> dict[str, Union[float, int, List[str]]]:
    cleaned = " ".join(text.strip().split())
    lowered = cleaned.lower()
    words = extract_words(cleaned)
    word_set = {word.lower() for word in words}

    suspicious_matches = [term for term in SUSPICIOUS_TERMS if term_present(lowered, word_set, term)]
    credible_matches = non_negated_matches(lowered, CREDIBLE_TERMS)
    suspicious_phrases = [phrase for phrase in SUSPICIOUS_PHRASES if phrase in lowered]
    absolutist_matches = [term for term in ABSOLUTIST_TERMS if term_present(lowered, word_set, term)]
    evidence_phrases = [phrase for phrase in EVIDENCE_PHRASES if phrase in lowered]
    manipulation_phrases = [phrase for phrase in MANIPULATION_PHRASES if phrase in lowered]
    attribution_terms = [term for term in ATTRIBUTION_TERMS if term_present(lowered, word_set, term)]
    institution_terms = [term for term in INSTITUTION_TERMS if term_present(lowered, word_set, term)]
    negated_credibility = [pattern for pattern in NEGATED_CREDIBILITY_PATTERNS if pattern in lowered]

    uppercase_chars = sum(1 for char in cleaned if char.isupper())
    alpha_chars = sum(1 for char in cleaned if char.isalpha())
    uppercase_ratio = round(uppercase_chars / alpha_chars, 3) if alpha_chars else 0.0

    exclamation_count = cleaned.count("!")
    question_count = cleaned.count("?")
    url_count = lowered.count("http://") + lowered.count("https://")
    sentence_count = max(1, len(re.findall(r"[.!?]+", cleaned)))
    claim_count = (
        len(re.findall(r"\bclaim(?:s|ed)?\b", lowered))
        + lowered.count("दावा")
        + lowered.count("कहा गया")
    )
    number_count = len(re.findall(r"\d+(?:\.\d+)?", lowered))
    source_gap = int(bool(suspicious_matches or suspicious_phrases) and not credible_matches and url_count == 0)

    return {
        "word_count": len(words),
        "uppercase_ratio": uppercase_ratio,
        "exclamation_count": exclamation_count,
        "question_count": question_count,
        "url_count": url_count,
        "sentence_count": sentence_count,
        "claim_count": claim_count,
        "number_count": number_count,
        "source_gap": source_gap,
        "suspicious_terms": suspicious_matches,
        "suspicious_phrases": suspicious_phrases,
        "evidence_phrases": evidence_phrases,
        "manipulation_phrases": manipulation_phrases,
        "credible_terms": credible_matches,
        "attribution_terms": attribution_terms,
        "institution_terms": institution_terms,
        "negated_credibility": negated_credibility,
        "absolutist_terms": absolutist_matches,
    }
