/* Voca widget v1.0.0. Treat this path as immutable once registered with Webflow. */
(() => {
  'use strict';
  const script = document.currentScript;
  const site = script?.dataset.vocaSite;
  const api = script?.dataset.vocaApi || (script?.src ? new URL(script.src).origin : '');
  if (!site || !/^site_[a-f0-9]{32}$/.test(site) || document.querySelector('[data-voca-mounted]')) return;
  let apiURL;
  try { apiURL = new URL(api); } catch { return; }
  if (apiURL.protocol !== 'https:' && !['localhost', '127.0.0.1'].includes(apiURL.hostname)) return;
  const host = document.createElement('div');
  host.dataset.vocaMounted = 'true';
  const shadow = host.attachShadow({ mode: 'open' });
  const style = document.createElement('style');
  style.textContent = `
    :host{all:initial;position:fixed;right:22px;bottom:22px;z-index:2147483000;font:16px/1.5 system-ui,-apple-system,sans-serif;color:#16213b;color-scheme:light}
    *{box-sizing:border-box}button,input,select{font:inherit}button{cursor:pointer}button:focus-visible,input:focus-visible,select:focus-visible,a:focus-visible{outline:3px solid #92a2ff;outline-offset:3px}
    .launcher{border:0;display:flex;align-items:center;gap:10px;border-radius:999px;background:#3647e9;color:#fff;padding:14px 20px;box-shadow:0 6px 24px #1b2b6540;font-weight:650}
    svg{width:22px;height:22px;flex-shrink:0}.panel{display:none;width:370px;max-width:calc(100vw - 28px);height:560px;max-height:calc(100dvh - 100px);flex-direction:column;background:#fff;border:1px solid #dbe0ef;box-shadow:0 18px 70px #16213b30;border-radius:20px;overflow:hidden;margin-bottom:12px}.panel.open{display:flex}
    header{padding:19px 20px;background:#17213d;color:#fff;display:flex;gap:12px;align-items:center;justify-content:space-between}h2{font-size:17px;line-height:1.3;margin:0}header small{display:block;color:#c4cce0;font-size:12px;margin-top:4px}.icon{border:0;background:transparent;display:flex;align-items:center;justify-content:center;padding:8px;color:inherit;border-radius:8px}.settings{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-bottom:1px solid #e7eaf2;gap:8px;font-size:13px}.settings select{min-width:0;max-width:160px;padding:6px;border:1px solid #dfe3ed;border-radius:7px;font-size:13px;background:#fff;color:#16213b}.settings label{display:flex;align-items:center;gap:5px}
    .log{flex:1;min-height:0;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:13px}.bubble{padding:12px 14px;border-radius:12px;background:#f1f3f9;max-width:95%;white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:1.55}.user{background:#3647e9;color:#fff;align-self:flex-end}.error{border:1px solid #efbbbc;background:#fff3f3;color:#8f2730}.sources{display:flex;flex-direction:column;gap:6px;margin-top:10px}.sources a{display:block;color:#3448cf;font-size:13px;text-decoration:underline;text-underline-offset:3px}.status{min-height:20px;margin:0;padding:0 18px;font-size:12px;color:#64728a}
    form{padding:12px 14px;display:flex;gap:7px;border-top:1px solid #e7eaf2;align-items:center}input[type=text]{flex:1;min-width:0;border:1px solid #dce1ee;border-radius:9px;padding:11px;font-size:14px;background:#fff;color:#16213b}.send{border:0;border-radius:9px;padding:10px;background:#3647e9;color:#fff}.mic{color:#4552d1;background:#f0f2fc;border:0}.mic.listening{background:#fae1e5;color:#b72348}.send:disabled,.mic:disabled{opacity:.5;cursor:wait}.privacy{font-size:11px;color:#68758d;margin:0;padding:0 16px 13px;line-height:1.4}.voice-stop{border:0;color:#4552d1;background:none;font-size:12px;padding:4px 8px}.visually-hidden{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0)}
    @media(max-width:450px){:host{right:14px;bottom:14px}.panel{width:calc(100vw - 28px);height:calc(100dvh - 104px)}.launcher{margin-left:auto}}
    @media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
  `;
  const icons = {
    chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 0 1-8 8H5l-4 3V11a10 10 0 0 1 19 0Z"/><path d="M7 10h8M7 14h5"/></svg>',
    mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>',
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m3 3 18 9-18 9 4-9-4-9ZM7 12h14"/></svg>'
  };
  const shell = document.createElement('div');
  shell.innerHTML = `<section class="panel" role="dialog" aria-modal="false" aria-labelledby="voca-title"><header><div><h2 id="voca-title">Website guide</h2><small>Answers from this website</small></div><button class="icon close" aria-label="Close guide">✕</button></header><div class="settings"><select aria-label="Conversation language"></select><label><input type="checkbox" class="spoken"> <span>Read aloud</span></label><button class="voice-stop" aria-label="Stop speaking">Stop</button></div><div class="log" role="log" aria-live="polite" aria-relevant="additions"></div><p class="status" role="status"></p><form><label class="visually-hidden" for="voca-question">Your question</label><input id="voca-question" type="text" maxlength="2000" autocomplete="off" placeholder="Ask about this website…" required><button type="button" class="icon mic" aria-label="Start voice question">${icons.mic}</button><button class="send" aria-label="Send question">${icons.send}</button></form><p class="privacy">AI answers can be mistaken. Check linked pages for current details. Voice input uses your browser’s speech service.</p></section><button class="launcher" aria-expanded="false">${icons.chat}<span>Ask the guide</span></button>`;
  shadow.append(style, shell);
  const get = s => shadow.querySelector(s);
  const panel = get('.panel'), launcher = get('.launcher'), log = get('.log'), input = get('input[type=text]'), select = get('select');
  const languages = [['auto','Auto / خودکار'],['en-US','English'],['ur-PK','اردو'],['ar-SA','العربية'],['hi-IN','हिन्दी'],['es-ES','Español'],['fr-FR','Français'],['de-DE','Deutsch'],['pt-BR','Português'],['zh-CN','中文'],['ja-JP','日本語']];
  languages.forEach(([value,name]) => { const option = document.createElement('option'); option.value=value; option.textContent=name; select.append(option); });
  const copy = {
    en:['Ask the guide','Ask about this website…','How can I help you find your way around this website?','Thinking…','Listening… tap the microphone to stop.','Voice input is unavailable. Please type your question.','Microphone access was declined. You can type instead.','Could not hear your question. Please try again.','Something went wrong. Please try again.','Read aloud','Website guide','Answers from this website','Close guide','Start voice question','Send question','Stop'],
    ur:['رہنما سے پوچھیں','اس ویب سائٹ کے بارے میں پوچھیں…','میں اس ویب سائٹ پر معلومات تلاش کرنے میں آپ کی کیسے مدد کر سکتا ہوں؟','سوچ رہا ہوں…','سن رہا ہوں… روکنے کے لیے مائیک دبائیں۔','آواز کی سہولت دستیاب نہیں۔ اپنا سوال لکھیں۔','مائیک کی اجازت نہیں ملی۔ اپنا سوال لکھ سکتے ہیں۔','سوال سنائی نہیں دیا۔ دوبارہ کوشش کریں۔','دوبارہ کوشش کریں۔','جواب سنیں','ویب سائٹ رہنما','اس ویب سائٹ سے جوابات','رہنما بند کریں','آواز سے سوال پوچھیں','سوال بھیجیں','روکیں'],
    ar:['اسأل الدليل','اسأل عن هذا الموقع…','كيف أساعدك في العثور على المعلومات في هذا الموقع؟','أفكر…','أستمع… اضغط على الميكروفون للإيقاف.','الإدخال الصوتي غير متاح. اكتب سؤالك.','تم رفض الميكروفون. يمكنك الكتابة.','لم أسمع السؤال. حاول مجدداً.','حاول مجدداً.','اقرأ بصوت','دليل الموقع','إجابات من هذا الموقع','إغلاق','سؤال صوتي','إرسال','إيقاف'],
    hi:['गाइड से पूछें','इस वेबसाइट के बारे में पूछें…','इस वेबसाइट पर जानकारी ढूँढने में मैं कैसे मदद करूँ?','सोच रहा हूँ…','सुन रहा हूँ… रोकने के लिए माइक दबाएँ।','आवाज़ उपलब्ध नहीं है। सवाल लिखें।','माइक की अनुमति नहीं मिली। सवाल लिखें।','सवाल सुनाई नहीं दिया। दोबारा कोशिश करें।','दोबारा कोशिश करें।','जवाब सुनें','वेबसाइट गाइड','इस वेबसाइट से जवाब','बंद करें','आवाज़ से पूछें','भेजें','रोकें'],
    es:['Pregunta al guía','Pregunta sobre este sitio…','¿Qué te gustaría encontrar en este sitio?','Pensando…','Escuchando… toca el micrófono para parar.','La voz no está disponible. Escribe tu pregunta.','Micrófono rechazado. Puedes escribir.','No se oyó la pregunta. Inténtalo de nuevo.','Inténtalo de nuevo.','Leer en voz alta','Guía del sitio','Respuestas de este sitio','Cerrar','Pregunta por voz','Enviar','Parar'],
    fr:['Demandez au guide','Posez une question sur ce site…','Que souhaitez-vous trouver sur ce site ?','Réflexion…','Écoute… appuyez sur le micro pour arrêter.','La voix est indisponible. Écrivez votre question.','Microphone refusé. Vous pouvez écrire.','Question inaudible. Réessayez.','Réessayez.','Lire à voix haute','Guide du site','Réponses de ce site','Fermer','Question vocale','Envoyer','Arrêter']
  };
  const locale = () => (select.value === 'auto' ? navigator.language : select.value).split('-')[0];
  const t = () => copy[locale()] || copy.en;
  let busy=false, recognition=null, listening=false, configured=false, history=[];
  const status = value => { get('.status').textContent=value; };
  function translate() {
    launcher.querySelector('span').textContent=t()[0]; input.placeholder=t()[1]; get('.settings label span').textContent=t()[9];
    get('header small').textContent=t()[11]; get('.close').ariaLabel=t()[12]; get('.mic').ariaLabel=t()[13]; get('.send').ariaLabel=t()[14]; get('.voice-stop').textContent=t()[15];
  }
  function bubble(text, user=false, error=false, sources=[]) {
    const item=document.createElement('div'); item.className='bubble'+(user?' user':'')+(error?' error':''); item.dir='auto'; item.textContent=text;
    if (sources.length) {
      const links=document.createElement('div'); links.className='sources';
      for (const source of sources) {
        try { const u=new URL(source.url); if (u.protocol!=='https:' && !(u.protocol==='http:' && u.origin===location.origin)) continue; const link=document.createElement('a'); link.href=u.href; link.textContent=source.title; link.target='_blank'; link.rel='noopener noreferrer'; links.append(link); } catch {}
      }
      item.append(links);
    }
    log.append(item); log.scrollTop=log.scrollHeight;
    return item;
  }
  function stopVoice() {
    if (recognition) recognition.abort();
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    listening=false; get('.mic').classList.remove('listening');
  }
  function speak(text) {
    if (!get('.spoken').checked || !('speechSynthesis' in window)) return;
    speechSynthesis.cancel(); const speech=new SpeechSynthesisUtterance(text);
    let lang=select.value==='auto'?navigator.language:select.value;
    if(select.value==='auto') { if(/[\u0600-\u06ff]/.test(text)) lang=/[ٹڈڑںھہے]/.test(text)?'ur-PK':'ar-SA'; else if(/[\u0900-\u097f]/.test(text))lang='hi-IN'; else if(/[\u4e00-\u9fff]/.test(text))lang='zh-CN'; }
    speech.lang=lang; const voice=speechSynthesis.getVoices().find(v=>v.lang.toLowerCase().startsWith(lang.split('-')[0])); if(voice)speech.voice=voice; speechSynthesis.speak(speech);
  }
  async function request(path, body) {
    const response=await fetch(apiURL.origin+path+'?site='+encodeURIComponent(site), {method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,credentials:'omit',signal:AbortSignal.timeout(65000)});
    const result=await response.json(); if(!response.ok)throw new Error(result.error || t()[8]); return result;
  }
  async function configure() {
    if(configured)return;
    try { const config=await request('/api/widget/config'); get('h2').textContent=config.name; bubble(t()[2]); configured=true; if(!config.ai_configured)status('The website owner is finishing AI setup.'); }
    catch(error) { status(error.message || t()[8]); }
  }
  function toggle(open) {
    panel.classList.toggle('open',open); launcher.setAttribute('aria-expanded',String(open));
    if(open){configure();input.focus();} else {stopVoice();status('');launcher.focus();}
  }
  launcher.onclick=()=>toggle(!panel.classList.contains('open')); get('.close').onclick=()=>toggle(false);
  shadow.addEventListener('keydown',event=>{if(event.key==='Escape')toggle(false);});
  select.onchange=()=>{stopVoice();translate();status('');}; get('.voice-stop').onclick=()=>{stopVoice();status('');};
  async function send(message) {
    if(busy || !message.trim())return;
    stopVoice(); busy=true; get('.send').disabled=true; get('.mic').disabled=true; input.value=''; bubble(message,true); status(t()[3]);
    try { const result=await request('/api/widget/chat',{message,language:select.value,history:history.slice(-8)}); bubble(result.answer,false,false,result.sources || []); history.push({role:'user',content:message},{role:'assistant',content:result.answer.slice(0,4000)}); history=history.slice(-8); status('');speak(result.answer); }
    catch(error) { bubble(error.message || t()[8],false,true); status(''); }
    finally {busy=false;get('.send').disabled=false;get('.mic').disabled=false;input.focus();}
  }
  get('form').onsubmit=event=>{event.preventDefault();send(input.value.trim());};
  get('.mic').onclick=()=>{
    if(listening){recognition.stop();return;}
    const SpeechRecognition=window.SpeechRecognition || window.webkitSpeechRecognition;
    if(!SpeechRecognition){status(t()[5]);return;}
    stopVoice(); recognition=new SpeechRecognition(); recognition.lang=select.value==='auto'?navigator.language:select.value; recognition.interimResults=false;
    recognition.onstart=()=>{listening=true;get('.mic').classList.add('listening');status(t()[4]);};
    recognition.onresult=event=>{const text=event.results[0][0].transcript;send(text);};
    recognition.onerror=event=>{status(event.error==='not-allowed'?t()[6]:event.error==='aborted'?'':t()[7]);};
    recognition.onend=()=>{listening=false;get('.mic').classList.remove('listening');if(get('.status').textContent===t()[4])status('');};
    try{recognition.start();}catch{status(t()[7]);}
  };
  translate();
  if(document.body)document.body.append(host);else document.addEventListener('DOMContentLoaded',()=>document.body.append(host),{once:true});
})();
