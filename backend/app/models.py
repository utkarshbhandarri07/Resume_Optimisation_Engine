from typing import Any, TypedDict
from pydantic import BaseModel, EmailStr, Field

class ResumeState(TypedDict, total=False):
    original_resume: str
    jd: str
    original_experience: str
    rewritten_experience: str
    ats_score_original: int
    ats_score_rewritten: int
    ats_explanation_original: str
    ats_explanation_rewritten: str
    user_feedback: str
    iteration_count: int
    is_satisfied: bool
    iteration_limit_reached: bool
    resume_sections: list[dict[str, Any]]
    grounding_valid: bool
    grounding_issues: list[str]
    status: str
    download_ready: bool
    current_resume: str
    evaluation_history: list[dict[str, Any]]
    evaluator_messages: list[dict[str, str]]
    evaluation: dict[str, Any]
    improvement_items: list[dict[str, Any]]
    approved_improvement_ids: list[str]
    selected_writer_model: str
    feedback_relevant: bool
    feedback_error: str
    best_evaluator_score: int
    best_ats_score: int
    comparison: dict[str, Any]
    repair_attempted: bool
    evaluator_model: str
    model_error: str
    model_error_target: str
    model_retry_node: str
    available_models: list[str]

class ReviewRequest(BaseModel):
    action: str = Field(pattern=r"^(improve|feedback|retry_model)$")
    feedback: str = Field(default="", max_length=5000)
    approved_improvement_ids: list[str] = Field(default_factory=list)
    model: str = Field(default="", max_length=80)

class OtpRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr

class OtpVerify(BaseModel):
    email: EmailStr
    otp: str = Field(pattern=r"^\d{6}$")
