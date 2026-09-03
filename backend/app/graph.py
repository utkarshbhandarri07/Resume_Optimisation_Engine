from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from .models import ResumeState
from .ats_scorer import score_experience
from .grounding import validate_grounding
from .llm import GeminiEvaluator, GeminiWriter
from .config import get_settings
from .oracle import get_checkpointer

WRITER_MODELS = {"gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"}

def _build(api_key, writer_model):
    settings = get_settings(); writer_model = writer_model if writer_model in WRITER_MODELS else "gemini-3.6-flash"
    evaluator, writer = GeminiEvaluator(api_key), GeminiWriter(api_key, writer_model)
    def initial_evaluate(state):
        ev = evaluator.evaluate(state["current_resume"], state["jd"], state.get("evaluator_messages", []), feedback=state.get("user_feedback", ""))
        messages = state.get("evaluator_messages", []) + [{"role":"user","content":"Evaluate this resume against the JD."},{"role":"model","content":str(ev)}]
        return {"evaluation": ev, "improvement_items": ev.get("improvement_items", []), "evaluator_messages": messages, "status":"awaiting_review", "best_evaluator_score": ev.get("overall_score", 0), "best_ats_score": state.get("ats_score_original", 0)}
    def review(state):
        payload = {"question":"Choose an action for this evaluation", "actions":["improve","feedback","accept"], "evaluation":state.get("evaluation",{}), "improvement_items":state.get("improvement_items",[]), "feedback_error":state.get("feedback_error","")}
        decision = interrupt(payload)
        action = decision.get("action") if isinstance(decision, dict) else ("accept" if decision else "feedback")
        if action == "accept": return Command(update={"is_satisfied":True,"download_ready":True,"status":"completed"}, goto="finish")
        if action == "feedback": return Command(update={"user_feedback":(decision.get("feedback","") if isinstance(decision,dict) else ""),"feedback_error":"","status":"evaluating_feedback"}, goto="feedback")
        ids = decision.get("approved_improvement_ids",[]) if isinstance(decision,dict) else []
        return Command(update={"approved_improvement_ids":ids or [x.get("id") for x in state.get("improvement_items",[])],"status":"rewriting"}, goto="generate")
    def feedback(state):
        ev = evaluator.evaluate(state["current_resume"], state["jd"], state.get("evaluator_messages",[]), previous=state.get("evaluation"), feedback=state.get("user_feedback",""))
        messages = state.get("evaluator_messages",[]) + [{"role":"user","content":state.get("user_feedback","")},{"role":"model","content":str(ev)}]
        if not ev.get("feedback_relevant", True): return {"evaluation":ev,"evaluator_messages":messages,"feedback_error":ev.get("feedback_reason","Feedback must relate to the resume or JD."),"status":"awaiting_review"}
        return {"evaluation":ev,"improvement_items":ev.get("improvement_items",[]),"evaluator_messages":messages,"feedback_error":"","status":"awaiting_review"}
    def generate(state):
        selected = [x for x in state.get("improvement_items",[]) if x.get("id") in state.get("approved_improvement_ids",[])]
        result = writer.rewrite(state["original_resume"], state["jd"], selected, state.get("user_feedback",""))
        sections = result.get("sections") if isinstance(result,dict) else None
        if not sections: raise ValueError("Generation model must return a sections array")
        text = "\n\n".join(f"{x.get('heading','')}\n{x.get('content','')}" for x in sections)
        return {"resume_sections":sections,"current_resume":text,"status":"validating"}
    def validate(state):
        valid, issues = validate_grounding(state["original_resume"], state["current_resume"])
        if not valid: raise ValueError("Grounding validation failed: " + "; ".join(issues))
        return {"grounding_valid":True,"grounding_issues":[]}
    def rescore(state):
        original = score_experience(state["original_resume"], state["jd"]); current = score_experience(state["current_resume"], state["jd"])
        return {"ats_score_original":original["score"],"ats_score_rewritten":current["score"],"ats_explanation_original":original["explanation"],"ats_explanation_rewritten":current["explanation"],"status":"evaluating"}
    def reevaluate(state):
        ev = evaluator.evaluate(state["current_resume"], state["jd"], state.get("evaluator_messages",[]), previous=state.get("evaluation"), feedback=state.get("user_feedback",""))
        messages = state.get("evaluator_messages",[]) + [{"role":"user","content":"Re-evaluate the revised resume."},{"role":"model","content":str(ev)}]
        comparison = {"evaluator_delta":ev.get("overall_score",0)-state.get("best_evaluator_score",0),"ats_delta":state.get("ats_score_rewritten",0)-state.get("best_ats_score",0),"resolved_issue_ids":ev.get("resolved_issue_ids",[]),"unresolved_issue_ids":ev.get("unresolved_issue_ids",[])}
        improved = comparison["evaluator_delta"] >= 0 and comparison["ats_delta"] >= 0 and ev.get("factual_grounding",True) is not False
        return {"evaluation":ev,"improvement_items":ev.get("improvement_items",[]),"evaluator_messages":messages,"comparison":comparison,"status":"awaiting_review","best_evaluator_score":max(state.get("best_evaluator_score",0),ev.get("overall_score",0)),"best_ats_score":max(state.get("best_ats_score",0),state.get("ats_score_rewritten",0)),"version_improved":improved}
    def finish(state): return {"status":state.get("status","completed")}
    b=StateGraph(ResumeState); b.add_node("initial_evaluate",initial_evaluate); b.add_node("review",review); b.add_node("feedback",feedback); b.add_node("generate",generate); b.add_node("validate",validate); b.add_node("rescore",rescore); b.add_node("reevaluate",reevaluate); b.add_node("finish",finish)
    b.add_edge(START,"initial_evaluate"); b.add_edge("initial_evaluate","review"); b.add_edge("feedback","review"); b.add_edge("generate","validate"); b.add_edge("validate","rescore"); b.add_edge("rescore","reevaluate"); b.add_edge("reevaluate","review"); b.add_edge("finish",END)
    return b.compile(checkpointer=get_checkpointer())

def build_graph(api_key, writer_model): return _build(api_key, writer_model)
