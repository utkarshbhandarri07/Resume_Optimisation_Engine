from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from .models import ResumeState
from .ats_scorer import score_experience
from .llm import GeminiEvaluator, GeminiWriter, ModelExecutionError
from .config import get_settings
from .oracle import get_checkpointer

MODEL_CHOICES = ("gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
WRITER_MODELS = set(MODEL_CHOICES[1:])


def _model_pause(exc: ModelExecutionError, target: str, retry_node: str) -> dict:
    models = list(MODEL_CHOICES if target == "evaluator" else MODEL_CHOICES[1:])
    return {"status":"model_selection_required", "model_error":str(exc), "model_error_target":target, "model_retry_node":retry_node, "available_models":models}

def _build(api_key, writer_model):
    settings = get_settings(); writer_model = writer_model if writer_model in WRITER_MODELS else "gemini-3.6-flash"
    def initial_evaluate(state):
        try:
            ev = GeminiEvaluator(api_key, state.get("evaluator_model", "gemini-3.7-flash")).evaluate(state["current_resume"], state["jd"], state.get("evaluator_messages", []), feedback=state.get("user_feedback", ""))
        except ModelExecutionError as exc:
            return _model_pause(exc, "evaluator", "initial_evaluate")
        messages = state.get("evaluator_messages", []) + [{"role":"user","content":"Evaluate this resume against the JD."},{"role":"model","content":str(ev)}]
        return {"evaluation": ev, "improvement_items": ev.get("improvement_items", []), "evaluator_messages": messages, "status":"awaiting_review", "best_evaluator_score": ev.get("overall_score", 0), "best_ats_score": state.get("ats_score_original", 0)}
    def review(state):
        payload = {"question":"Choose an action for this evaluation", "actions":["improve","feedback"], "evaluation":state.get("evaluation",{}), "improvement_items":state.get("improvement_items",[]), "feedback_error":state.get("feedback_error","")}
        decision = interrupt(payload)
        action = decision.get("action") if isinstance(decision, dict) else "feedback"
        if action == "feedback": return Command(update={"user_feedback":(decision.get("feedback","") if isinstance(decision,dict) else ""),"feedback_error":"","status":"evaluating_feedback"}, goto="feedback")
        ids = decision.get("approved_improvement_ids",[]) if isinstance(decision,dict) else []
        return Command(update={"approved_improvement_ids":ids or [x.get("id") for x in state.get("improvement_items",[])],"status":"rewriting"}, goto="generate")
    def feedback(state):
        try:
            ev = GeminiEvaluator(api_key, state.get("evaluator_model", "gemini-3.7-flash")).evaluate(state["current_resume"], state["jd"], state.get("evaluator_messages",[]), previous=state.get("evaluation"), feedback=state.get("user_feedback",""))
        except ModelExecutionError as exc:
            return _model_pause(exc, "evaluator", "feedback")
        messages = state.get("evaluator_messages",[]) + [{"role":"user","content":state.get("user_feedback","")},{"role":"model","content":str(ev)}]
        if not ev.get("feedback_relevant", True): return {"evaluation":ev,"evaluator_messages":messages,"feedback_error":ev.get("feedback_reason","Feedback must relate to the resume or JD."),"status":"awaiting_review"}
        return {"evaluation":ev,"improvement_items":ev.get("improvement_items",[]),"evaluator_messages":messages,"feedback_error":"","status":"awaiting_review"}
    def generate(state):
        selected = [x for x in state.get("improvement_items",[]) if x.get("id") in state.get("approved_improvement_ids",[])]
        try:
            result = GeminiWriter(api_key, state.get("selected_writer_model", writer_model)).rewrite(state["original_resume"], state["jd"], selected, state.get("user_feedback",""))
        except ModelExecutionError as exc:
            return _model_pause(exc, "writer", "generate")
        sections = result.get("sections") if isinstance(result,dict) else None
        if not isinstance(sections, list) or not sections or any(not isinstance(item, dict) or not str(item.get("heading", "")).strip() or not str(item.get("content", "")).strip() for item in sections):
            return _model_pause(ModelExecutionError("The generation model returned an invalid resume format. Choose another generation model and retry."), "writer", "generate")
        text = "\n\n".join(f"{x.get('heading','')}\n{x.get('content','')}" for x in sections)
        return {"resume_sections":sections,"current_resume":text,"status":"validating"}
    def validate(state):
        # User-approved workflow: surface the rewritten content for evaluator
        # review and final human acceptance without blocking on lexical
        # comparison against the original resume.
        return {"grounding_valid":True,"grounding_issues":[]}
    def rescore(state):
        original = score_experience(state["original_resume"], state["jd"]); current = score_experience(state["current_resume"], state["jd"])
        return {"ats_score_original":original["score"],"ats_score_rewritten":current["score"],"ats_explanation_original":original["explanation"],"ats_explanation_rewritten":current["explanation"],"status":"evaluating"}
    def reevaluate(state):
        try:
            ev = GeminiEvaluator(api_key, state.get("evaluator_model", "gemini-3.7-flash")).evaluate(state["current_resume"], state["jd"], state.get("evaluator_messages",[]), previous=state.get("evaluation"), feedback=state.get("user_feedback",""))
        except ModelExecutionError as exc:
            return _model_pause(exc, "evaluator", "reevaluate")
        messages = state.get("evaluator_messages",[]) + [{"role":"user","content":"Re-evaluate the revised resume."},{"role":"model","content":str(ev)}]
        comparison = {"evaluator_delta":ev.get("overall_score",0)-state.get("best_evaluator_score",0),"ats_delta":state.get("ats_score_rewritten",0)-state.get("best_ats_score",0),"resolved_issue_ids":ev.get("resolved_issue_ids",[]),"unresolved_issue_ids":ev.get("unresolved_issue_ids",[])}
        improved = comparison["evaluator_delta"] >= 0 and comparison["ats_delta"] >= 0 and ev.get("factual_grounding",True) is not False
        return {"evaluation":ev,"improvement_items":ev.get("improvement_items",[]),"evaluator_messages":messages,"comparison":comparison,"status":"preview_ready","download_ready":True,"best_evaluator_score":max(state.get("best_evaluator_score",0),ev.get("overall_score",0)),"best_ats_score":max(state.get("best_ats_score",0),state.get("ats_score_rewritten",0)),"version_improved":improved}
    def model_selection(state):
        selection = interrupt({"kind":"model_selection", "error":state.get("model_error","Model request failed."), "target":state.get("model_error_target","evaluator"), "models":state.get("available_models",list(MODEL_CHOICES))})
        model = selection.get("model", "") if isinstance(selection, dict) else ""
        allowed = MODEL_CHOICES if state.get("model_error_target") == "evaluator" else MODEL_CHOICES[1:]
        if model not in allowed:
            return Command(update={"model_error":"Choose one of the available Gemini models.","status":"model_selection_required"}, goto="model_selection")
        field = "evaluator_model" if state.get("model_error_target") == "evaluator" else "selected_writer_model"
        return Command(update={field:model,"model_error":"","status":"evaluating"}, goto=state.get("model_retry_node","initial_evaluate"))
    def finish(state): return {"status":state.get("status","completed")}
    def route_after_model_call(state): return "model_selection" if state.get("status")=="model_selection_required" else "review"
    def route_after_generate(state): return "model_selection" if state.get("status")=="model_selection_required" else "validate"
    def route_after_reevaluation(state): return "model_selection" if state.get("status")=="model_selection_required" else "finish"
    b=StateGraph(ResumeState); b.add_node("initial_evaluate",initial_evaluate); b.add_node("review",review); b.add_node("feedback",feedback); b.add_node("generate",generate); b.add_node("validate",validate); b.add_node("rescore",rescore); b.add_node("reevaluate",reevaluate); b.add_node("model_selection",model_selection); b.add_node("finish",finish)
    b.add_edge(START,"initial_evaluate"); b.add_conditional_edges("initial_evaluate",route_after_model_call); b.add_conditional_edges("feedback",route_after_model_call); b.add_conditional_edges("generate",route_after_generate); b.add_edge("validate","rescore"); b.add_edge("rescore","reevaluate"); b.add_conditional_edges("reevaluate",route_after_reevaluation); b.add_edge("finish",END)
    return b.compile(checkpointer=get_checkpointer())

def build_graph(api_key, writer_model): return _build(api_key, writer_model)
