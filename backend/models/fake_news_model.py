from __future__ import annotations

import csv
import math
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from backend.utils.scoring import clamp
from backend.utils.text_processing import extract_text_signals, extract_words


CURATED_FAKE_SAMPLES = [
    "Breaking! This unbelievable miracle cure was exposed by a secret source!!!",
    "You will not believe this hidden truth the media does not want you to know!",
    "Viral post claims shocking election fraud without any source.",
    "Exclusive leaked alert says everyone must share before it is deleted.",
    "Secret insider reveals unbelievable scam that officials are hiding.",
    "A WhatsApp forward claims that banks will shut down tomorrow, but provides no official notice.",
    "Rumor says the government is hiding a secret cure and everyone must share this alert immediately.",
    "Forwarded message warns that celebrities are part of a shocking conspiracy with no verified source.",
    "Breaking claim says voting machines changed results, but no source is provided.",
    "This one trick was banned because it exposes the truth about cancer cures.",
    "Hidden truth alert says the media is covering up a miracle drink.",
    "Fake post claims leaked documents prove a fraud without evidence.",
    "सोशल मीडिया पर दावा किया जा रहा है कि भारत में अगले हफ्ते सभी बैंक अचानक बंद होने वाले हैं।",
    "एक वायरल पोस्ट में कहा गया है कि चुनाव के नतीजे गुप्त तरीके से बदल दिए गए हैं।",
    "इंटरनेट पर फैल रही खबर के अनुसार एक घरेलू पेय से तीन दिन में मधुमेह पूरी तरह ठीक हो सकती है।",
    "एक व्हाट्सएप फॉरवर्ड में दावा किया गया है कि कल सभी बैंक बंद रहेंगे।",
    "वायरल संदेश कहता है कि यह चमत्कारी इलाज सरकार छिपा रही है।",
    "एक पोस्ट में दावा किया गया है कि वोटिंग मशीनों के नतीजे गुप्त रूप से बदल दिए गए।",
]

CURATED_REAL_SAMPLES = [
    "Official report cites verified data and evidence from multiple agencies.",
    "Research analysis from a national lab includes methodology and references.",
    "Scientists published a peer-reviewed study with methods and evidence.",
    "According to the official statement, investigators cited supporting data and named sources.",
    "The government released an official bulletin with supporting data and a named spokesperson.",
    "Police released an official statement and cited CCTV evidence in the investigation.",
    "The finance ministry published a report with methodology, references, and supporting statistics.",
    "The company reported quarterly revenue in its published financial statement.",
    "Officials confirmed the flood warning in a press release and cited rainfall data from the state agency.",
    "The court filing includes witness statements, dates, and documented evidence.",
    "The health ministry issued an advisory after researchers published a peer-reviewed study.",
    "A university research team released a verified report with supporting data and references.",
    "भारत सरकार ने नई स्वास्थ्य योजना से जुड़ा आधिकारिक प्रेस नोट जारी किया।",
    "भारतीय रिजर्व बैंक ने नई मौद्रिक नीति के संबंध में आधिकारिक बयान प्रकाशित किया।",
    "भारतीय रेल ने बदले हुए ट्रेन समय के लिए आधिकारिक सलाह जारी की।",
    "स्वास्थ्य मंत्रालय ने सहायक आंकड़ों के साथ आधिकारिक विज्ञप्ति जारी की।",
    "पुलिस ने जांच के संबंध में आधिकारिक बयान और साक्ष्य साझा किए।",
    "सरकार ने नई नीति पर आधिकारिक रिपोर्ट और डेटा प्रकाशित किया।",
]


def tokenize_for_model(text: str) -> list[str]:
    tokens = [token.lower() for token in extract_words(text)]
    bigrams = [f"{tokens[index]}_{tokens[index + 1]}" for index in range(len(tokens) - 1)]
    return tokens + bigrams


def load_training_samples() -> list[tuple[str, str]]:
    samples = [(text, "fake") for text in CURATED_FAKE_SAMPLES]
    samples.extend((text, "real") for text in CURATED_REAL_SAMPLES)

    dataset_path = Path(__file__).resolve().parents[2] / "dataset" / "fake_news_dataset.csv"
    if dataset_path.exists():
        with dataset_path.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                text = (row.get("text") or "").strip()
                label = (row.get("label") or "").strip().lower()
                if text and label in {"fake", "real"}:
                    samples.append((text, label))

    return samples


def build_language_model() -> dict[str, object]:
    fake_counts: Counter[str] = Counter()
    real_counts: Counter[str] = Counter()
    vocabulary: set[str] = set()

    for text, label in load_training_samples():
        tokens = tokenize_for_model(text)
        vocabulary.update(tokens)
        if label == "fake":
            fake_counts.update(tokens)
        else:
            real_counts.update(tokens)

    return {
        "fake_counts": fake_counts,
        "real_counts": real_counts,
        "vocabulary_size": max(1, len(vocabulary)),
        "fake_total": max(1, sum(fake_counts.values())),
        "real_total": max(1, sum(real_counts.values())),
    }


LANGUAGE_MODEL = build_language_model()


def bayes_fake_probability(text: str) -> float:
    tokens = tokenize_for_model(text)
    if not tokens:
        return 0.5

    fake_counts = LANGUAGE_MODEL["fake_counts"]
    real_counts = LANGUAGE_MODEL["real_counts"]
    fake_total = int(LANGUAGE_MODEL["fake_total"])
    real_total = int(LANGUAGE_MODEL["real_total"])
    vocabulary_size = int(LANGUAGE_MODEL["vocabulary_size"])

    fake_log = math.log(0.5)
    real_log = math.log(0.5)

    for token in tokens:
        fake_log += math.log((fake_counts[token] + 1) / (fake_total + vocabulary_size))
        real_log += math.log((real_counts[token] + 1) / (real_total + vocabulary_size))

    return 1 / (1 + math.exp(real_log - fake_log))


def analyze_news(text: str, live_context: Optional[dict[str, object]] = None) -> dict[str, object]:
    signals = extract_text_signals(text)
    lexical_probability = bayes_fake_probability(text)

    if signals["word_count"] < 18:
        word_count_factor = 0.18
    elif signals["word_count"] < 40:
        word_count_factor = 0.1
    else:
        word_count_factor = 0.03

    punctuation_factor = min(0.26, signals["exclamation_count"] * 0.05 + signals["question_count"] * 0.025)
    uppercase_factor = min(0.2, signals["uppercase_ratio"] * 0.62)
    suspicious_factor = min(
        0.62,
        len(signals["suspicious_terms"]) * 0.085
        + len(signals["suspicious_phrases"]) * 0.14
        + len(signals["manipulation_phrases"]) * 0.11
        + len(signals["negated_credibility"]) * 0.12,
    )
    absolutist_factor = min(0.2, len(signals["absolutist_terms"]) * 0.06)
    claim_factor = min(0.16, signals["claim_count"] * 0.05)
    source_gap_factor = 0.18 if signals["source_gap"] else 0.0
    credibility_offset = min(
        0.46,
        len(signals["credible_terms"]) * 0.045
        + len(signals["evidence_phrases"]) * 0.09
        + len(signals["attribution_terms"]) * 0.035
        + len(signals["institution_terms"]) * 0.03,
    )
    url_offset = min(0.12, signals["url_count"] * 0.04)
    structure_offset = 0.06 if signals["number_count"] > 0 and signals["evidence_phrases"] else 0.0
    real_bias_offset = 0.05 if len(signals["credible_terms"]) >= 3 else 0.0
    strong_evidence_offset = 0.08 if len(signals["evidence_phrases"]) >= 1 and len(signals["institution_terms"]) >= 1 else 0.0

    fake_probability = 0.24 + word_count_factor + punctuation_factor + uppercase_factor
    fake_probability += suspicious_factor + absolutist_factor + claim_factor + source_gap_factor
    fake_probability -= credibility_offset + url_offset + structure_offset + real_bias_offset + strong_evidence_offset
    heuristic_probability = clamp(fake_probability, 0.02, 0.98)
    blended_probability = 0.56 * lexical_probability + 0.44 * heuristic_probability
    if len(signals["credible_terms"]) >= 3 or len(signals["evidence_phrases"]) >= 1:
        blended_probability -= 0.05
    if len(signals["manipulation_phrases"]) >= 1 or len(signals["negated_credibility"]) >= 1:
        blended_probability += 0.12
    if signals["source_gap"] and (signals["suspicious_terms"] or signals["suspicious_phrases"] or signals["manipulation_phrases"]):
        blended_probability += 0.08
    if len(signals["suspicious_phrases"]) >= 1 and len(signals["credible_terms"]) == 0:
        blended_probability += 0.05

    live_used = False
    live_provider = ""
    live_headlines = []
    if isinstance(live_context, dict) and live_context.get("used"):
        live_used = True
        live_provider = str(live_context.get("provider", "") or "")
        live_headlines = list(live_context.get("latest_headlines") or [])
        corroboration_score = float(live_context.get("corroboration_score", 0.0) or 0.0)
        fact_check_score = float(live_context.get("fact_check_score", 0.0) or 0.0)
        article_count = int(live_context.get("article_count", 0) or 0)
        supporting_article_count = int(live_context.get("supporting_article_count", 0) or 0)

        if corroboration_score >= 0.45:
            blended_probability -= min(0.14, corroboration_score * 0.18)
        if fact_check_score > 0:
            blended_probability += min(0.26, fact_check_score * 0.5)
        if article_count == 0 and (signals["suspicious_terms"] or signals["suspicious_phrases"]):
            blended_probability += 0.08
        if supporting_article_count >= 2 and len(signals["credible_terms"]) >= 1 and not signals["source_gap"]:
            blended_probability -= 0.04

    fake_probability = round(clamp(blended_probability, 0.02, 0.98), 2)

    real_probability = round(1 - fake_probability, 2)
    confidence = round(min(0.98, 0.6 + abs(fake_probability - 0.52) * 0.82), 2)
    status = "Fake" if fake_probability >= 0.52 else "Real"

    explanation = [
        "Headline-style exaggeration and sensational wording increase the fake-risk score.",
        "References to sources, data, and evidence reduce the fake-risk score.",
        "This is a deterministic NLP-style heuristic module, not a trained misinformation model.",
    ]
    if signals["suspicious_terms"]:
        explanation.insert(0, f"Suspicious terms detected: {', '.join(signals['suspicious_terms'])}.")
    if signals["suspicious_phrases"]:
        explanation.insert(1, f"Suspicious phrases detected: {', '.join(signals['suspicious_phrases'])}.")
    if signals["evidence_phrases"]:
        explanation.insert(2, f"Evidence-style phrases detected: {', '.join(signals['evidence_phrases'])}.")
    if signals["credible_terms"]:
        explanation.insert(3, f"Credibility indicators detected: {', '.join(signals['credible_terms'])}.")
    if signals["negated_credibility"]:
        explanation.insert(1, f"Negated credibility cues detected: {', '.join(signals['negated_credibility'])}.")
    if live_used:
        article_count = int(live_context.get("article_count", 0) or 0)
        supporting_article_count = int(live_context.get("supporting_article_count", 0) or 0)
        sources = live_context.get("supporting_sources") or []
        if supporting_article_count:
            explanation.insert(
                0,
                f"Live news lookup{f' via {live_provider}' if live_provider else ''} found {supporting_article_count} matching recent articles across {len(sources)} sources.",
            )
        elif article_count == 0:
            explanation.insert(0, "Live news lookup found no recent corroborating coverage for this claim.")
        if float(live_context.get("fact_check_score", 0.0) or 0.0) > 0:
            explanation.insert(1, "Live lookup found fact-check style or debunk-style coverage related to this claim.")
        if live_headlines:
            first_headline = live_headlines[0]
            title = str(first_headline.get("title") or "").strip()
            source = str(first_headline.get("source") or "").strip()
            if title:
                explanation.insert(1, f"Closest recent headline checked: {title}" + (f" ({source})" if source else "."))

    summary = (
        f"The submitted news content was classified as {status.lower()} with "
        f"{int(fake_probability * 100)}% fake probability."
    )

    return {
        "analysis_type": "text",
        "status": status,
        "fake_probability": fake_probability,
        "real_probability": real_probability,
        "confidence": confidence,
        "summary": summary,
        "explanation": explanation,
        "metadata": {
            **signals,
            "live_lookup_used": int(live_used),
            "live_provider": live_provider,
            "live_article_count": int((live_context or {}).get("article_count", 0) or 0),
            "live_supporting_article_count": int((live_context or {}).get("supporting_article_count", 0) or 0),
            "live_corroboration_score": float((live_context or {}).get("corroboration_score", 0.0) or 0.0),
            "live_fact_check_score": float((live_context or {}).get("fact_check_score", 0.0) or 0.0),
            "live_latest_headlines": live_headlines[:3],
        },
    }
