import json
import re
from google import genai
from google.genai import types
from .config import get_settings
from .prompts import evaluator_prompt, generation_prompt


class ModelTemporarilyUnavailable(RuntimeError):
    """A retryable model-provider capacity error safe to return to clients."""


class ModelExecutionError(RuntimeError):
    """A safe summary of a model failure that can trigger model selection."""


def _model_error(exc: Exception, operation: str) -> ModelExecutionError:
    status = getattr(exc, "status_code", None)
    if status == 503 or "503 UNAVAILABLE" in str(exc):
        return ModelTemporarilyUnavailable("Gemini is temporarily at capacity. Choose another model or retry shortly.")
    detail = f"HTTP {status}" if status else type(exc).__name__
    return ModelExecutionError(f"Gemini {operation} failed ({detail}). Choose another model and retry.")

def _json(text: str) -> dict:
    text = (text or "").strip()
    try: return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match: raise RuntimeError("Gemini returned invalid JSON")
        return json.loads(match.group(0))

class GeminiEvaluator:
    def __init__(self, api_key: str, model: str = "gemini-3.7-flash"):
        if not api_key: raise RuntimeError("Gemini API key is required")
        self.client, self.model = genai.Client(api_key=api_key), model
    def evaluate(self, resume, jd, history, previous=None, feedback=""):
        try:
            result = self.client.models.generate_content(model=self.model, contents=evaluator_prompt(resume, jd, history, feedback, previous), config=types.GenerateContentConfig(response_mime_type="application/json", max_output_tokens=3000))
            data = _json(result.text)
        except Exception as exc:
            raise _model_error(exc, "evaluation") from exc
        data.setdefault("improvement_items", []); data.setdefault("overall_score", 0); data.setdefault("feedback_relevant", True)
        return data

class GeminiWriter:
    def __init__(self, api_key: str, model: str):
        if not api_key: raise RuntimeError("Gemini API key is required")
        self.client, self.model = genai.Client(api_key=api_key), model
    def rewrite(self, resume, jd, items, feedback=""):
        try:
            result = self.client.models.generate_content(model=self.model, contents=generation_prompt(resume, jd, items, feedback, self.model), config=types.GenerateContentConfig(response_mime_type="application/json", max_output_tokens=5000))
            data = _json(result.text)
        except Exception as exc:
            raise _model_error(exc, "rewrite") from exc
        return data
