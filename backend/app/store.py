import json
from uuid import uuid4
from .oracle import get_pool

_sessions = {}
def _safe(state):
    return json.dumps(state, default=str)
def create_session(user, state, source_bytes, filename):
    sid = str(uuid4()); item={"id":sid,"user":user,"state":state,"source":source_bytes,"filename":filename,"pdf":None}; _sessions[sid]=item
    pool=get_pool()
    if pool:
        with pool.acquire() as con:
            with con.cursor() as cur:
                cur.execute("MERGE INTO ro_users u USING (SELECT :email email FROM dual) x ON (u.email=x.email) WHEN NOT MATCHED THEN INSERT (id,email,display_name) VALUES (:id,:email,:name)", {"id":str(uuid4()),"email":user,"name":user})
            # Autonomous Database can reject a read-after-write on the same
            # table in a parallel DML transaction (ORA-12839). Finalize the
            # idempotent user upsert before resolving its stable user ID.
            con.commit()
            with con.cursor() as cur:
                cur.execute("SELECT id FROM ro_users WHERE email=:email", {"email":user})
                user_id = cur.fetchone()[0]
                cur.execute("INSERT INTO ro_sessions (id,user_id,jd,state_json,status,evaluator_model,writer_model) VALUES (:sid,:user_id,:jd,:state,:status,:eval,:writer)", {"sid":sid,"user_id":user_id,"jd":state["jd"],"state":_safe(state),"status":state.get("status","processing"),"eval":state.get("evaluator_model","gemini-3.7-flash"),"writer":state.get("selected_writer_model","gemini-3.6-flash")})
                cur.execute("INSERT INTO ro_documents (id,session_id,kind,filename,mime_type,content) VALUES (:id,:sid,'SOURCE',:filename,:mime,:content)", {"id":str(uuid4()),"sid":sid,"filename":filename,"mime":"application/octet-stream","content":source_bytes})
            con.commit()
    return sid
def get_session(sid,user):
    item=_sessions.get(sid)
    if item and item["user"]==user:return item
    pool=get_pool()
    if not pool:return None
    with pool.acquire() as con:
        with con.cursor() as cur:
            cur.execute("SELECT s.state_json,src.content,src.filename,gen.content FROM ro_sessions s JOIN ro_users u ON u.id=s.user_id LEFT JOIN ro_documents src ON src.session_id=s.id AND src.kind='SOURCE' LEFT JOIN ro_documents gen ON gen.session_id=s.id AND gen.kind='GENERATED' WHERE s.id=:sid AND u.email=:email", {"sid":sid,"email":user})
            row=cur.fetchone()
    if not row:return None
    state=json.loads(row[0].read() if hasattr(row[0],"read") else row[0]); item={"id":sid,"user":user,"state":state,"source":row[1].read() if hasattr(row[1],"read") else row[1],"filename":row[2],"pdf":row[3].read() if hasattr(row[3],"read") else row[3]}; _sessions[sid]=item; return item
def save_session(sid,state):
    if sid in _sessions:_sessions[sid]["state"]=state
    pool=get_pool()
    if pool:
        with pool.acquire() as con:
            with con.cursor() as cur:
                cur.execute("UPDATE ro_sessions SET state_json=:state,status=:status,evaluator_model=:eval,writer_model=:writer,updated_at=SYSTIMESTAMP WHERE id=:sid", {"state":_safe(state),"status":state.get("status","processing"),"eval":state.get("evaluator_model","gemini-3.7-flash"),"writer":state.get("selected_writer_model","gemini-3.6-flash"),"sid":sid})
                version_id=str(uuid4())
                cur.execute("INSERT INTO ro_resume_versions (id,session_id,version_no,sections_json,resume_text,ats_score,ats_breakdown_json,evaluator_score,grounding_valid) VALUES (:id,:sid,(SELECT NVL(MAX(version_no),0)+1 FROM ro_resume_versions WHERE session_id=:sid),:sections,:text,:ats,:breakdown,:eval,:grounding)", {"id":version_id,"sid":sid,"sections":json.dumps(state.get("resume_sections",[]),default=str),"text":state.get("current_resume",""),"ats":state.get("ats_score_rewritten") or state.get("ats_score_original"),"breakdown":json.dumps({"original":state.get("ats_explanation_original"),"rewritten":state.get("ats_explanation_rewritten")}),"eval":(state.get("evaluation") or {}).get("overall_score"),"grounding":"Y" if state.get("grounding_valid",True) else "N"})
                ev=state.get("evaluation")
                if ev:
                    evaluation_id=str(uuid4()); cur.execute("INSERT INTO ro_evaluations (id,session_id,version_id,evaluation_json,score_delta) VALUES (:id,:sid,:vid,:json,:delta)", {"id":evaluation_id,"sid":sid,"vid":version_id,"json":json.dumps(ev,default=str),"delta":ev.get("score_delta",0)})
                    for sequence,message in enumerate(state.get("evaluator_messages",[]),1):
                        cur.execute("MERGE INTO ro_evaluator_messages m USING (SELECT :sid sid,:seq seq FROM dual) x ON (m.session_id=x.sid AND m.sequence_no=x.seq) WHEN NOT MATCHED THEN INSERT (session_id,sequence_no,role,content) VALUES (:sid,:seq,:role,:content)", {"sid":sid,"seq":sequence,"role":message.get("role","user"),"content":message.get("content","")})
            con.commit()
def save_pdf(sid,pdf):
    if sid in _sessions:_sessions[sid]["pdf"]=pdf
    pool=get_pool()
    if pool:
        with pool.acquire() as con:
            with con.cursor() as cur: cur.execute("INSERT INTO ro_documents (id,session_id,kind,filename,mime_type,content) VALUES (:id,:sid,'GENERATED','optimized-resume.pdf','application/pdf',:content)", {"id":str(uuid4()),"sid":sid,"content":pdf})
            con.commit()
def list_sessions(user):
    local=[x for x in _sessions.values() if x["user"]==user]
    pool=get_pool()
    if not pool:return local
    with pool.acquire() as con:
        with con.cursor() as cur:
            cur.execute("SELECT s.id,s.state_json FROM ro_sessions s JOIN ro_users u ON u.id=s.user_id WHERE u.email=:email ORDER BY s.updated_at DESC", {"email":user})
            rows=cur.fetchall()
    result=[]
    for sid,state_json in rows:
        item=get_session(sid,user)
        if item: result.append(item)
    return result
