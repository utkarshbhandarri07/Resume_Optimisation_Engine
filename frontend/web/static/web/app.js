(() => {
  "use strict";
  const API = window.RESUME_API_BASE;
  const MODELS = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"];
  const KEYS = {token:"ro_token",name:"ro_name",email:"ro_email",gemini:"ro_gemini_key",model:"ro_writer_model",active:"ro_active_session"};
  const app = document.getElementById("app");
  let otpSent = false;

  const read = (key, storage=localStorage) => storage.getItem(key) || "";
  const write = (key, value, storage=localStorage) => storage.setItem(key, value);
  const token = () => read(KEYS.token);
  const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
  const clearBrowserData = () => Object.values(KEYS).forEach(key => {localStorage.removeItem(key);sessionStorage.removeItem(key);});
  const cachedSession = () => {try {const item=JSON.parse(read(KEYS.active,sessionStorage));return item && Date.now()-item.cached_at<300000 ? item.data : null;} catch {return null;}};
  const cacheSession = data => write(KEYS.active,JSON.stringify({cached_at:Date.now(),data}),sessionStorage);
  const message = text => text ? `<p class="error">${escapeHtml(text)}</p>` : "";
  const disableButtons = disabled => document.querySelectorAll("button").forEach(button => button.disabled=disabled);

  async function api(path, options={}) {
    const headers = new Headers(options.headers || {});
    if (token()) headers.set("Authorization", `Bearer ${token()}`);
    const response = await fetch(`${API}${path}`, {...options, headers});
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const wait = response.headers.get("Retry-After") || data.retry_after;
      throw new Error(`${data.detail || "Request failed."}${response.status===429 && wait ? ` Please wait ${wait} seconds.` : ""}`);
    }
    return response;
  }

  const header = () => `<header><a class="brand" href="#">Resume Optimizer</a><div class="profile"><button id="profile-button">Profile ▾</button><div id="profile-menu" class="menu hidden"><button id="new-session">New session</button><button id="open-settings">Settings</button><button id="logout">Logout</button></div></div></header>`;
  const settings = () => `<dialog id="settings-dialog"><form method="dialog" class="settings-card"><button class="close" value="cancel" aria-label="Close">×</button><p class="eyebrow">MODEL CONFIGURATION</p><h2>Settings</h2><label>Evaluator model<input value="gemini-3.7-flash" disabled></label><small class="muted">Fixed evaluator model.</small><label>Generation model<select id="settings-model">${MODELS.map(model=>`<option ${model===(read(KEYS.model)||MODELS[0])?"selected":""}>${model}</option>`).join("")}</select></label><label>Gemini API key<input id="settings-key" type="password" value="${escapeHtml(read(KEYS.gemini))}" autocomplete="off"></label><button id="save-settings" value="default">Save settings</button></form></dialog>`;

  function wireHeader() {
    document.getElementById("profile-button")?.addEventListener("click",()=>document.getElementById("profile-menu").classList.toggle("hidden"));
    document.getElementById("new-session")?.addEventListener("click",()=>{sessionStorage.removeItem(KEYS.active);renderUpload();});
    document.getElementById("logout")?.addEventListener("click",()=>{clearBrowserData();otpSent=false;renderAuth();});
    document.getElementById("open-settings")?.addEventListener("click",()=>document.getElementById("settings-dialog").showModal());
    document.getElementById("save-settings")?.addEventListener("click",event=>{event.preventDefault();write(KEYS.model,document.getElementById("settings-model").value);write(KEYS.gemini,document.getElementById("settings-key").value);document.getElementById("settings-dialog").close();});
  }

  function renderAuth(status="") {
    app.innerHTML=`<section class="shell auth-shell"><section class="hero"><p class="eyebrow">RESUME OPTIMIZER</p><h1>Make your experience impossible to overlook.</h1><p>Start with a verified email.</p></section><section class="card auth"><h2>Email verification</h2>${!otpSent?`<label>Your name<input id="name" value="${escapeHtml(read(KEYS.name))}" autocomplete="name"></label><label>Email address<input id="email" type="email" value="${escapeHtml(read(KEYS.email))}" autocomplete="email"></label><button id="send-otp">Send OTP</button>`:`<p class="muted">Check your inbox for the six-digit code.</p><label>Verification code<input id="otp" inputmode="numeric" maxlength="6" autocomplete="one-time-code"></label><button id="verify-otp">Verify and continue</button>`}${message(status)}</section></section>`;
    document.getElementById("send-otp")?.addEventListener("click",async()=>{
      const name=document.getElementById("name").value.trim(),email=document.getElementById("email").value.trim();
      if(!name||!email)return renderAuth("Enter your name and email address.");
      try{disableButtons(true);const result=await (await api("/auth/request-otp",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,email})})).json();write(KEYS.name,name);write(KEYS.email,email);otpSent=true;renderAuth(result.development_otp?`Development OTP: ${result.development_otp}`:"");}catch(err){renderAuth(err.message);}finally{disableButtons(false);}
    });
    document.getElementById("verify-otp")?.addEventListener("click",async()=>{
      const otp=document.getElementById("otp").value.trim();if(otp.length!==6)return renderAuth("Enter the six-digit verification code.");
      try{disableButtons(true);const result=await (await api("/auth/verify-otp",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:read(KEYS.email),otp})})).json();write(KEYS.token,result.access_token);renderUpload();}catch(err){renderAuth(err.message);}finally{disableButtons(false);}
    });
  }

  function renderUpload(status="") {
    app.innerHTML=`<section class="shell">${header()}${settings()}<section class="hero compact"><p class="eyebrow">NEW SESSION</p><h1>Bring the role into focus.</h1><p>Each session starts a fresh evaluator conversation.</p></section><section class="card"><label>Gemini API key<input id="gemini-key" type="password" value="${escapeHtml(read(KEYS.gemini))}" autocomplete="off"></label><small class="muted">Stored only in this browser until Logout.</small><label>Generation model<select id="writer-model">${MODELS.map(model=>`<option ${model===(read(KEYS.model)||MODELS[0])?"selected":""}>${model}</option>`).join("")}</select></label><label>Resume<input id="resume-file" type="file" accept=".pdf,.docx"></label><label>Job description<textarea id="job-description" rows="12" placeholder="Paste the complete job description..."></textarea></label><button id="evaluate">Evaluate resume</button>${message(status)}</section></section>`;
    wireHeader();
    document.getElementById("evaluate").addEventListener("click",async()=>{
      const file=document.getElementById("resume-file").files[0],jd=document.getElementById("job-description").value.trim(),key=document.getElementById("gemini-key").value.trim(),model=document.getElementById("writer-model").value;
      if(!file||jd.length<30||!key)return renderUpload("Add a PDF/DOCX, a complete job description, and your Gemini API key.");
      try{disableButtons(true);write(KEYS.gemini,key);write(KEYS.model,model);const form=new FormData();form.append("resume",file);form.append("jd",jd);form.append("writer_model",model);const session=await (await api("/sessions",{method:"POST",headers:{"X-Gemini-API-Key":key},body:form})).json();cacheSession(session);renderReview(session);}catch(err){renderUpload(err.message);}finally{disableButtons(false);}
    });
  }

  function renderReview(session,status="") {
    const evaluation=session.evaluation||{};
    const issues=(session.improvement_items||[]).map(item=>`<label class="issue"><input type="checkbox" value="${escapeHtml(item.id)}" checked><span><b>${escapeHtml(item.priority||"medium")}</b> · ${escapeHtml(item.target_section||"Resume")}<br>${escapeHtml(item.recommendation)}</span></label>`).join("")||"<p class='muted'>No open improvement points.</p>";
    const resume=session.current_resume?`<section class="compare"><article><h2>Current best resume</h2><pre>${escapeHtml(session.current_resume)}</pre></article></section>`:"";
    const download=session.download_ready?"<button id='download'>Download optimized PDF</button>":"";
    app.innerHTML=`<section class="shell">${header()}${settings()}<section class="hero compact"><p class="eyebrow">EVALUATOR REVIEW</p><h1>${escapeHtml(evaluation.overall_score||0)}/100 fit score</h1><p>${escapeHtml(evaluation.executive_assessment||"Review the evaluator findings below.")}</p></section><section class="card"><h2>Key improvement points</h2>${issues}${session.feedback_error?message(session.feedback_error):""}<div class="actions"><button id="improve">Improve resume</button><button class="secondary" id="feedback">Give feedback</button><button class="secondary" id="accept">Accept</button>${download}</div>${message(status)}</section>${resume}</section>`;
    wireHeader();
    const continueSession=async data=>{const key=read(KEYS.gemini);if(!key)throw new Error("Add your Gemini API key in Settings before continuing.");const updated=await (await api(`/sessions/${session.session_id}/decision`,{method:"POST",headers:{"Content-Type":"application/json","X-Gemini-API-Key":key},body:JSON.stringify(data)})).json();cacheSession(updated);renderReview(updated);};
    document.getElementById("improve")?.addEventListener("click",async()=>{try{disableButtons(true);await continueSession({action:"improve",approved_improvement_ids:[...document.querySelectorAll(".issue input:checked")].map(input=>input.value)});}catch(err){renderReview(session,err.message);}finally{disableButtons(false);}});
    document.getElementById("feedback")?.addEventListener("click",async()=>{const feedback=window.prompt("Enter feedback about the resume or job description:");if(!feedback?.trim())return;try{disableButtons(true);await continueSession({action:"feedback",feedback});}catch(err){renderReview(session,err.message);}finally{disableButtons(false);}});
    document.getElementById("accept")?.addEventListener("click",async()=>{try{disableButtons(true);await continueSession({action:"accept"});}catch(err){renderReview(session,err.message);}finally{disableButtons(false);}});
    document.getElementById("download")?.addEventListener("click",async()=>{try{disableButtons(true);const response=await api(`/sessions/${session.session_id}/download`);const blob=await response.blob(),link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download="optimized-resume.pdf";link.click();URL.revokeObjectURL(link.href);}catch(err){renderReview(session,err.message);}finally{disableButtons(false);}});
  }

  token()?(cachedSession()?renderReview(cachedSession()):renderUpload()):renderAuth();
})();
