import re
def validate_grounding(source: str, rewritten: str):
    issues = []
    new_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", rewritten)) - set(re.findall(r"\b\d+(?:\.\d+)?%?\b", source))
    if new_numbers: issues.append("New numeric claims: " + ", ".join(sorted(new_numbers)))
    source_caps = {x.lower() for x in re.findall(r"\b[A-Z][A-Za-z0-9+#.-]{2,}\b", source)}
    new_caps = {x.lower() for x in re.findall(r"\b[A-Z][A-Za-z0-9+#.-]{2,}\b", rewritten)} - source_caps
    harmless = {"experience", "professional", "responsibilities", "results", "impact", "team", "role"}
    if new_caps - harmless: issues.append("New named terms: " + ", ".join(sorted(new_caps - harmless)))
    return not issues, issues
