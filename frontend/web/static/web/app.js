(() => {
  "use strict";
  const API = window.RESUME_API_BASE;
  const MODELS = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"];
  const EVALUATOR_MODELS = ["gemini-3.7-flash", ...MODELS];
  const KEYS = {token:"ro_token",name:"ro_name",email:"ro_email",gemini:"ro_gemini_key",model:"ro_writer_model",evaluator:"ro_evaluator_model",active:"ro_active_session"};
  const app = document.getElementById("app");
  let otpSent = false;
  let draft = {file:null,jd:""};

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
      // Reverse proxies can return an HTML error page (not JSON) when a long
      // Gemini/PDF request exceeds their timeout. Keep its useful text and
      // turn a 504 into an actionable message instead of "Request failed.".
      const body = await response.text().catch(() => "");
      let data = {};
      try { data = body ? JSON.parse(body) : {}; } catch { data = {detail: body}; }
      const wait = response.headers.get("Retry-After") || data.retry_after;
      const fallback = response.status === 504
        ? "The optimization took longer than expected. Your uploaded resume and job description are preserved; wait a moment and refresh the session before trying again."
        : "Request failed.";
      const detail = typeof data.detail === "string" && data.detail.trim()
        ? data.detail
        : (data.detail?.message || fallback);
      const error = new Error(`${detail}${response.status===429 && wait ? ` Please wait ${wait} seconds.` : ""}`);
      error.payload=data; error.status=response.status; throw error;
    }
    return response;
  }

  function showErrorDialog(text) {
    const dialog=document.createElement("dialog"); dialog.className="error-dialog";
    dialog.innerHTML=`<section class="settings-card"><button class="close" aria-label="Close">×</button><p class="eyebrow">REQUEST ISSUE</p><h2>We could not complete that request</h2><p>${escapeHtml(text)}</p><button class="secondary" id="dismiss-error">Close</button></section>`;
    document.body.append(dialog); dialog.showModal(); const close=()=>{dialog.close();dialog.remove();}; dialog.querySelector(".close").onclick=close; dialog.querySelector("#dismiss-error").onclick=close;
  }

  function renderSession(session) {
    cacheSession(session);
    if(session.status==="model_selection_required"){renderUpload("Evaluation is paused until you choose a model.");showModelSelection(session);return;}
    renderReview(session);
  }

  function showModelSelection(session) {
    const models=session.available_models?.length?session.available_models:EVALUATOR_MODELS, target=session.model_error_target==="writer"?"generation":"evaluation", current=target==="evaluation"?(session.evaluator_model||read(KEYS.evaluator)||models[0]):(session.selected_writer_model||read(KEYS.model)||MODELS[0]);
    const dialog=document.createElement("dialog"); dialog.className="model-dialog";
    dialog.innerHTML=`<section class="settings-card"><p class="eyebrow">MODEL RETRY REQUIRED</p><h2>${target === "evaluation" ? "Evaluator" : "Generation"} model needs attention</h2><p>${escapeHtml(session.model_error||"The selected Gemini model could not complete this request.")}</p><label>Try another available model<select id="retry-model">${models.map(model=>`<option ${model===current?"selected":""}>${escapeHtml(model)}</option>`).join("")}</select></label><p class="muted">Your uploaded resume and LangGraph session are preserved.</p><button id="retry-model-button">Retry with selected model</button><p id="model-retry-status" class="error"></p></section>`;
    document.body.append(dialog); dialog.showModal();
    dialog.querySelector("#retry-model-button").addEventListener("click",async()=>{const button=dialog.querySelector("#retry-model-button"),status=dialog.querySelector("#model-retry-status"),model=dialog.querySelector("#retry-model").value,key=read(KEYS.gemini);if(!key){status.textContent="Add your Gemini API key in Settings before retrying.";return;}try{button.disabled=true;status.textContent="Retrying the paused LangGraph step…";const updated=await (await api(`/sessions/${session.session_id}/decision`,{method:"POST",headers:{"Content-Type":"application/json","X-Gemini-API-Key":key},body:JSON.stringify({action:"retry_model",model})})).json();write(target==="evaluation"?KEYS.evaluator:KEYS.model,model);dialog.close();dialog.remove();renderSession(updated);}catch(err){status.textContent=err.message;showErrorDialog(err.message);}finally{button.disabled=false;}});
  }

  const header = () => `<header><a class="brand" href="#">Resume Optimizer</a><div class="profile"><button id="profile-button">Profile ▾</button><div id="profile-menu" class="menu hidden"><button id="new-session">New session</button><button id="open-settings">Settings</button><button id="logout">Logout</button></div></div></header>`;
  const settings = () => `<dialog id="settings-dialog"><form method="dialog" class="settings-card"><button class="close" value="cancel" aria-label="Close">×</button><p class="eyebrow">MODEL CONFIGURATION</p><h2>Settings</h2><label>Evaluator model<select id="settings-evaluator-model">${EVALUATOR_MODELS.map(model=>`<option ${model===(read(KEYS.evaluator)||EVALUATOR_MODELS[0])?"selected":""}>${model}</option>`).join("")}</select></label><small class="muted">Used for new evaluation sessions. A paused session can also change its evaluator in the retry dialog.</small><label>Generation model<select id="settings-model">${MODELS.map(model=>`<option ${model===(read(KEYS.model)||MODELS[0])?"selected":""}>${model}</option>`).join("")}</select></label><label>Gemini API key<input id="settings-key" type="password" value="${escapeHtml(read(KEYS.gemini))}" autocomplete="off"></label><button id="save-settings" value="default">Save settings</button></form></dialog>`;

  function wireHeader() {
    document.getElementById("profile-button")?.addEventListener("click",()=>document.getElementById("profile-menu").classList.toggle("hidden"));
    document.getElementById("new-session")?.addEventListener("click",()=>{sessionStorage.removeItem(KEYS.active);draft={file:null,jd:""};renderUpload();});
    document.getElementById("logout")?.addEventListener("click",()=>{clearBrowserData();otpSent=false;draft={file:null,jd:""};renderAuth();});
    document.getElementById("open-settings")?.addEventListener("click",()=>document.getElementById("settings-dialog").showModal());
    document.getElementById("save-settings")?.addEventListener("click",event=>{event.preventDefault();write(KEYS.evaluator,document.getElementById("settings-evaluator-model").value);write(KEYS.model,document.getElementById("settings-model").value);write(KEYS.gemini,document.getElementById("settings-key").value);document.getElementById("settings-dialog").close();});
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
    const retained=Boolean(draft.file||draft.jd), label=retained?"RETAINED DRAFT":"NEW SESSION", description=retained?"Your resume and job description are preserved. Correct anything, then retry when ready.":"Each session starts a fresh evaluator conversation.";
    app.innerHTML=`<section class="shell">${header()}${settings()}<section class="hero compact"><p class="eyebrow">${label}</p><h1>Bring the role into focus.</h1><p>${description}</p></section><section class="card"><label>Gemini API key<input id="gemini-key" type="password" value="${escapeHtml(read(KEYS.gemini))}" autocomplete="off"></label><small class="muted">Stored only in this browser until Logout.</small><label>Evaluator model<select id="evaluator-model">${EVALUATOR_MODELS.map(model=>`<option ${model===(read(KEYS.evaluator)||EVALUATOR_MODELS[0])?"selected":""}>${model}</option>`).join("")}</select></label><label>Generation model<select id="writer-model">${MODELS.map(model=>`<option ${model===(read(KEYS.model)||MODELS[0])?"selected":""}>${model}</option>`).join("")}</select></label><label>Resume<input id="resume-file" type="file" accept=".pdf,.docx"></label>${draft.file?`<p class="muted">Using retained resume: ${escapeHtml(draft.file.name)}</p>`:""}<label>Job description<textarea id="job-description" rows="12" placeholder="Paste the complete job description...">${escapeHtml(draft.jd)}</textarea></label><button id="evaluate">Evaluate resume</button>${message(status)}</section></section>`;
    wireHeader();
    document.getElementById("evaluate").addEventListener("click",async()=>{
      const chosenFile=document.getElementById("resume-file").files[0],jd=document.getElementById("job-description").value.trim(),key=document.getElementById("gemini-key").value.trim(),model=document.getElementById("writer-model").value,evaluatorModel=document.getElementById("evaluator-model").value;if(chosenFile)draft.file=chosenFile;draft.jd=jd;const file=draft.file;
      if(!file||jd.length<30||!key)return renderUpload("Add a PDF/DOCX, a complete job description, and your Gemini API key.");
      try{disableButtons(true);write(KEYS.gemini,key);write(KEYS.model,model);write(KEYS.evaluator,evaluatorModel);const form=new FormData();form.append("resume",file);form.append("jd",jd);form.append("writer_model",model);form.append("evaluator_model",evaluatorModel);const session=await (await api("/sessions",{method:"POST",headers:{"X-Gemini-API-Key":key},body:form})).json();renderSession(session);}catch(err){renderUpload(err.message);showErrorDialog(err.message);}finally{disableButtons(false);}
    });
  }

  function renderReview(session,status="") {
    const evaluation=session.evaluation||{};
    const issues=(session.improvement_items||[]).map(item=>`<label class="issue"><input type="checkbox" value="${escapeHtml(item.id)}" checked><span><b>${escapeHtml(item.priority||"medium")}</b> · ${escapeHtml(item.target_section||"Resume")}<br>${escapeHtml(item.recommendation)}</span></label>`).join("")||"<p class='muted'>No open improvement points.</p>";
    const resume=session.current_resume?`<section class="compare"><article><h2>Current best resume</h2><pre>${escapeHtml(session.current_resume)}</pre></article></section>`:"";
    const preview=session.status==="preview_ready",download=session.download_ready?"<button id='download'>Download optimized PDF</button>":"",actions=preview?download:`<button id="improve">Improve resume</button><button class="secondary" id="feedback">Give feedback</button>`;
    app.innerHTML=`<section class="shell">${header()}${settings()}<section class="hero compact"><p class="eyebrow">${preview?"RESUME PREVIEW":"EVALUATOR REVIEW"}</p><h1>${escapeHtml(evaluation.overall_score||0)}/100 fit score</h1><p>${escapeHtml(preview?"Review the optimized resume below, then download it when ready.":(evaluation.executive_assessment||"Review the evaluator findings below."))}</p></section><section class="card"><h2>Key improvement points</h2>${issues}${session.feedback_error?message(session.feedback_error):""}${session.layout_error?message(session.layout_error):""}<div class="actions">${actions}</div>${message(status)}</section>${resume}</section>`;
    wireHeader();
    const continueSession=async data=>{const key=read(KEYS.gemini);if(!key)throw new Error("Add your Gemini API key in Settings before continuing.");const updated=await (await api(`/sessions/${session.session_id}/decision`,{method:"POST",headers:{"Content-Type":"application/json","X-Gemini-API-Key":key},body:JSON.stringify(data)})).json();renderSession(updated);};
    document.getElementById("improve")?.addEventListener("click",async()=>{try{disableButtons(true);await continueSession({action:"improve",approved_improvement_ids:[...document.querySelectorAll(".issue input:checked")].map(input=>input.value)});}catch(err){renderReview(session,err.message);showErrorDialog(err.message);}finally{disableButtons(false);}});
    document.getElementById("feedback")?.addEventListener("click",async()=>{const feedback=window.prompt("Enter feedback about the resume or job description:");if(!feedback?.trim())return;try{disableButtons(true);await continueSession({action:"feedback",feedback});}catch(err){renderReview(session,err.message);showErrorDialog(err.message);}finally{disableButtons(false);}});
    document.getElementById("download")?.addEventListener("click",async()=>{try{disableButtons(true);const response=await api(`/sessions/${session.session_id}/download`);const blob=await response.blob(),link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download="optimized-resume.pdf";link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);sessionStorage.removeItem(KEYS.active);draft={file:draft.file,jd:""};renderUpload("Optimized resume downloaded. The job description was cleared; your uploaded resume is retained for the next session.");}catch(err){renderReview(session,err.message);showErrorDialog(err.message);}finally{disableButtons(false);}});
  }

  token()?(cachedSession()?renderReview(cachedSession()):renderUpload()):renderAuth();
})();
