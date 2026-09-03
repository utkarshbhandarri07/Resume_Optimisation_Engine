import re
from collections import Counter
ACTION_VERBS = {"built", "led", "designed", "developed", "implemented", "created", "managed", "improved", "delivered", "automated", "optimized", "reduced", "increased", "launched", "architected", "integrated"}
STOP = {"with", "from", "that", "this", "using", "your", "have", "will", "and", "the", "for", "are", "our", "you"}
def _terms(text): return [x for x in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{2,}", text.lower()) if x not in STOP]
def score_experience(experience: str, jd: str) -> dict:
    exp_terms, jd_terms = set(_terms(experience)), Counter(_terms(jd))
    important = {term for term in jd_terms if len(term) > 2}
    matched = sorted(important & exp_terms)
    keyword = round(50 * len(matched) / max(len(important), 1))
    quantified = len(re.findall(r"(?:\d+(?:\.\d+)?\s*%|\$?\d[\d,.]*\+?|\b\d+\s*(?:x|years?|months?|users?|projects?))", experience, re.I))
    quantified_points = min(20, quantified * 5)
    verb_points = min(20, sum(1 for t in _terms(experience) if t in ACTION_VERBS) * 4)
    words = len(_terms(experience)); readability = 10 if 40 <= words <= 260 else 6 if 20 <= words <= 350 else 3
    total = min(100, keyword + quantified_points + verb_points + readability)
    explanation = f"{keyword}/50 keyword match ({len(matched)}/{len(important)}), {quantified_points}/20 quantified achievements, {verb_points}/20 action verbs, and {readability}/10 length/readability."
    return {"score": total, "explanation": explanation, "matched_keywords": matched, "missing_keywords": sorted(important - exp_terms)}
