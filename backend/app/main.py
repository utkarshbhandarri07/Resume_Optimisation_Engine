from io import BytesIO
from time import perf_counter
from uuid import uuid4
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from langgraph.types import Command
from .config import get_settings
from .models import OtpRequest, OtpVerify, ReviewRequest
from .auth import send_otp, verify_otp, current_user
from .resume_parser import parse_resume
from .graph import build_graph, EVALUATOR_MODELS, WRITER_MODELS
from .store import create_session, get_session, save_session, save_pdf, list_sessions
from .pdf_generator import build_resume_pdf
from .resume_layout import ResumeLayoutError, source_template_data
from .oracle import get_pool
from .ats_scorer import score_experience
from .rate_limit import SlidingWindowRateLimiter
from .logging_config import configure_application_logging
from .llm import ModelTemporarilyUnavailable

app=FastAPI(title="Resume Optimization Agent",version="2.0.0"); settings=get_settings(); logger=configure_application_logging(settings.log_dir,settings.log_level); app.add_middleware(CORSMiddleware,allow_origins=settings.allowed_origins,allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
rate_limiter=SlidingWindowRateLimiter(settings.rate_limit_requests,settings.rate_limit_window_seconds)
oracle_pool=None

@app.middleware("http")
async def limit_api_requests(request, call_next):
    """Log API outcomes and enforce a three-requests-per-ten-seconds limit."""
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    started = perf_counter()
    if request.url.path.startswith("/api/"):
        authorization=request.headers.get("authorization", "")
        client_key=authorization or (request.client.host if request.client else "unknown")
        allowed, retry_after=rate_limiter.allow(client_key, oracle_pool)
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={"detail":"Rate limit exceeded. Try again shortly.","retry_after":retry_after},
                headers={"Retry-After":str(retry_after)},
            )
            response.headers["X-Request-ID"] = request_id
            logger.warning("request_rate_limited id=%s method=%s path=%s retry_after=%s", request_id, request.method, request.url.path, retry_after)
            return response
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed id=%s method=%s path=%s", request_id, request.method, request.url.path)
        raise
    response.headers["X-Request-ID"] = request_id
    logger.info("request_completed id=%s method=%s path=%s status=%s duration_ms=%d", request_id, request.method, request.url.path, response.status_code, int((perf_counter()-started)*1000))
    return response
@app.on_event("startup")
def startup():
    global oracle_pool; oracle_pool=get_pool(); logger.info("application_started oracle_configured=%s", bool(oracle_pool))
def public(item):
    state=dict(item["state"]); state.pop("original_resume",None); state["session_id"]=item.get("id"); return state
@app.get("/api/health/live")
def live(): return {"status":"ok"}
@app.get("/api/health/ready")
def ready(): return {"status":"ok" if oracle_pool else "degraded","oracle_configured":bool(oracle_pool)}
@app.post("/api/auth/request-otp")
def request_otp(payload:OtpRequest):
    code=send_otp(str(payload.email),payload.name); result={"message":"If the address is valid, a verification code has been sent."}
    if settings.app_env=="development" and settings.otp_provider=="mock": result["development_otp"]=code
    return result
@app.post("/api/auth/verify-otp")
def verify(payload:OtpVerify): return {"access_token":verify_otp(str(payload.email),payload.otp),"token_type":"bearer"}
@app.post("/api/sessions")
async def create(jd:str=Form(...),resume:UploadFile=File(...),writer_model:str=Form("gemini-3.6-flash"),evaluator_model:str=Form("gemini-3.7-flash"),user:str=Depends(current_user),gemini_api_key:str|None=Header(default=None,alias="X-Gemini-API-Key")):
    if writer_model not in WRITER_MODELS: raise HTTPException(400,"Unsupported generation model")
    if evaluator_model not in EVALUATOR_MODELS: raise HTTPException(400,"Unsupported evaluator model")
    data=await resume.read()
    if len(data)>settings.max_upload_mb*1024*1024: raise HTTPException(413,"Resume is too large")
    try: original,experience,sections,target_page_count=parse_resume(data,resume.filename or "resume.pdf")
    except ValueError as exc: raise HTTPException(400,str(exc))
    source_data=source_template_data(original, sections)
    state={"original_resume":original,"current_resume":original,"jd":jd,"original_experience":experience,"resume_sections":sections,"source_template_data":source_data,"resume_template_data":source_data,"target_page_count":target_page_count,"iteration_count":0,"is_satisfied":False,"status":"evaluating","selected_writer_model":writer_model,"evaluator_model":evaluator_model,"ats_score_original":score_experience(original,jd)["score"]}
    sid=create_session(user,state,data,resume.filename or "resume.pdf")
    try: result=build_graph(gemini_api_key,writer_model).invoke(state,config={"configurable":{"thread_id":sid}})
    except ModelTemporarilyUnavailable as exc:
        logger.warning("session_initial_evaluation_deferred session_id=%s evaluator_model=%s", sid, evaluator_model)
        raise HTTPException(503, str(exc), headers={"Retry-After":"30"})
    except RuntimeError as exc:
        logger.exception("session_initial_evaluation_failed session_id=%s evaluator_model=%s", sid, evaluator_model)
        raise HTTPException(503,str(exc))
    save_session(sid,result); item=get_session(sid,user); return public(item)
@app.get("/api/sessions")
def sessions(user:str=Depends(current_user)): return {"sessions":[public(x) for x in list_sessions(user)]}
@app.get("/api/sessions/{sid}")
def session(sid:str,user:str=Depends(current_user)):
    item=get_session(sid,user)
    if not item: raise HTTPException(404,"Session not found")
    return public(item)
@app.post("/api/sessions/{sid}/decision")
def decision(sid:str,payload:ReviewRequest,user:str=Depends(current_user),gemini_api_key:str|None=Header(default=None,alias="X-Gemini-API-Key")):
    item=get_session(sid,user)
    if not item: raise HTTPException(404,"Session not found")
    if payload.action=="feedback" and not payload.feedback.strip(): raise HTTPException(400,"Feedback is required")
    try: result=build_graph(gemini_api_key,item["state"].get("selected_writer_model","gemini-3.6-flash")).invoke(Command(resume=payload.model_dump()),config={"configurable":{"thread_id":sid}})
    except ModelTemporarilyUnavailable as exc:
        logger.warning("session_decision_deferred session_id=%s action=%s", sid, payload.action)
        raise HTTPException(503, str(exc), headers={"Retry-After":"30"})
    except Exception as exc:
        logger.exception("session_decision_failed session_id=%s action=%s", sid, payload.action)
        raise HTTPException(502,f"Session could not continue: {exc}")
    save_session(sid,result); item=get_session(sid,user)
    if item["state"].get("download_ready") and not item.get("pdf"):
        save_pdf(sid, build_resume_pdf(item["state"]["resume_template_data"], item["state"]["target_page_count"]))
    return public(item)
@app.get("/api/sessions/{sid}/download")
def download(sid:str,user:str=Depends(current_user)):
    item=get_session(sid,user)
    if not item or not item["state"].get("download_ready"): raise HTTPException(409,"Resume is not ready for download")
    if not item.get("pdf"):
        try: save_pdf(sid, build_resume_pdf(item["state"]["resume_template_data"], item["state"]["target_page_count"]))
        except ResumeLayoutError as exc: raise HTTPException(409, str(exc))
    return StreamingResponse(BytesIO(item["pdf"]),media_type="application/pdf",headers={"Content-Disposition":"attachment; filename=optimized-resume.pdf"})
