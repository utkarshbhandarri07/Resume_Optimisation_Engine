import hashlib, secrets, time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import smtplib
from uuid import uuid4
from jose import jwt, JWTError
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .config import get_settings
from .oracle import get_pool

_otp_store = {}
_users = {}
security = HTTPBearer(auto_error=False)

def send_otp(email: str, name: str) -> str:
    settings = get_settings(); code = f"{secrets.randbelow(1_000_000):06d}"
    _otp_store[email.lower()] = {"hash": hashlib.sha256(code.encode()).hexdigest(), "expires": time.time() + settings.otp_expiry_minutes * 60, "attempts": 0, "name": name}
    pool = get_pool()
    if pool:
        with pool.acquire() as con:
            with con.cursor() as cur:
                cur.execute("INSERT INTO ro_otp_requests (id,email,otp_hash,expires_at) VALUES (:id,:email,:hash,SYSTIMESTAMP + NUMTODSINTERVAL(:minutes,'MINUTE'))", {"id":str(uuid4()),"email":email.lower(),"hash":hashlib.sha256(code.encode()).hexdigest(),"minutes":settings.otp_expiry_minutes})
            con.commit()
    if settings.otp_provider == "mock":
        if settings.app_env != "development": raise HTTPException(503, "Mock email provider is disabled")
        return code
    if not settings.smtp_host: raise HTTPException(503, "Email provider is not configured")
    # A dedicated verified sender is preferred; using the authenticated SMTP
    # account as the fallback keeps deployments with a single mailbox usable.
    msg = EmailMessage(); msg["Subject"] = "Your Resume Optimizer verification code"; msg["From"] = settings.email_from or settings.smtp_username; msg["To"] = email; msg.set_content(f"Your verification code is {code}. It expires in {settings.otp_expiry_minutes} minutes.")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        server.starttls(); server.login(settings.smtp_username, settings.smtp_password); server.send_message(msg)
    return ""

def verify_otp(email: str, code: str) -> str:
    settings = get_settings(); email = email.lower(); item = _otp_store.get(email)
    pool = get_pool()
    if pool:
        with pool.acquire() as con:
            with con.cursor() as cur:
                cur.execute("SELECT id,otp_hash,expires_at,attempts FROM (SELECT id,otp_hash,expires_at,attempts FROM ro_otp_requests WHERE email=:email ORDER BY created_at DESC) WHERE ROWNUM=1", {"email":email}); row=cur.fetchone()
                if not row: raise HTTPException(401, "Invalid or expired verification code")
                cur.execute("UPDATE ro_otp_requests SET attempts=attempts+1 WHERE id=:id", {"id":row[0]}); con.commit()
                if row[3] >= 5 or row[2] < datetime.now(timezone.utc) or not secrets.compare_digest(row[1], hashlib.sha256(code.encode()).hexdigest()): raise HTTPException(401, "Invalid or expired verification code")
                cur.execute("SELECT id,display_name FROM ro_users WHERE email=:email", {"email":email}); existing=cur.fetchone()
                if existing: name=existing[1]
                else:
                    name=(item or {}).get("name", email.split("@",1)[0]); cur.execute("INSERT INTO ro_users (id,email,display_name) VALUES (:id,:email,:name)", {"id":str(uuid4()),"email":email,"name":name}); con.commit()
                payload = {"sub": email, "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiry_minutes)}; return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    if not item or item["expires"] < time.time() or item["attempts"] >= 5: raise HTTPException(401, "Invalid or expired verification code")
    item["attempts"] += 1
    if not secrets.compare_digest(item["hash"], hashlib.sha256(code.encode()).hexdigest()): raise HTTPException(401, "Invalid or expired verification code")
    _users[email] = {"email": email, "name": item["name"]}; payload = {"sub": email, "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiry_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

def current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    if not credentials: raise HTTPException(401, "Authentication required")
    try: return jwt.decode(credentials.credentials, get_settings().jwt_secret, algorithms=["HS256"])["sub"]
    except (JWTError, KeyError): raise HTTPException(401, "Invalid or expired token")
