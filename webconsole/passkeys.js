/* WebAuthn browser codec. Private keys never leave the authenticator. */
function passkeyDecode(value){
  return Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
}
function passkeyEncode(value){
  return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/=/g,'').replace(/\+/g,'-').replace(/\//g,'_');
}
function passkeyOptions(options,register){
  const p=options.publicKey;
  p.challenge=passkeyDecode(p.challenge);
  if(register)p.user.id=passkeyDecode(p.user.id);
  for(const key of ['allowCredentials','excludeCredentials']){
    if(p[key])p[key]=p[key].map(c=>({...c,id:passkeyDecode(c.id)}));
  }
  return options;
}
function passkeyCredential(credential){
  const r=credential.response;
  const response={clientDataJSON:passkeyEncode(r.clientDataJSON)};
  if(r.attestationObject){
    response.attestationObject=passkeyEncode(r.attestationObject);
    response.transports=r.getTransports?r.getTransports():[];
  }else{
    response.authenticatorData=passkeyEncode(r.authenticatorData);
    response.signature=passkeyEncode(r.signature);
    response.userHandle=r.userHandle?passkeyEncode(r.userHandle):null;
  }
  return {id:credential.id,rawId:passkeyEncode(credential.rawId),type:credential.type,
    response,clientExtensionResults:credential.getClientExtensionResults()};
}
function passkeyErrorMessage(error,register){
  if(error.name==='NotAllowedError')return 'Passkey request cancelled or timed out. You can retry.';
  if(register&&error.name==='InvalidStateError')return 'This passkey provider already has a passkey for this panel. Select Sign in with passkey. To add a separate passkey, choose another passkey provider or a security key.';
  if(error.name==='UnknownError'||error.name==='NotReadableError'){
    const action=register?'registration':'sign-in';
    const next=register?'If you already saved a passkey, select Sign in with passkey. To add another, choose a different provider or security key. Otherwise unlock your device and retry.':'Unlock your device and retry, or choose another saved passkey.';
    return 'Your browser or passkey provider could not complete '+action+' ('+error.name+'). '+next;
  }
  return error.message||'Passkey request failed. Retry.';
}
async function configurePasskeys({authRequest,enterSession}){
  const {response,data}=await authRequest('/api/auth/config');
  if(!response.ok)throw new Error('Could not check sign-in settings. Reload to retry.');
  if(data.mode!=='passkey')throw new Error('Private access is not configured. Ask the server administrator to configure Tailscale Serve and Passkey.');
  const el=id=>document.getElementById(id);
  el('passkeyLogin').hidden=false;
  el('loginDescription').textContent='Use your fingerprint, face or device lock to sign in.';
  let busy=false,pendingRequest='';
  const pendingMessage=()=>pendingRequest?'Passkey created. Request '+pendingRequest+' is waiting for approval in the Telegram bot (10 minutes). Approve the matching device request there. Do not create another passkey. After approval, select Sign in with passkey.':'';
  async function perform(register){
    if(busy)return;
    busy=true;
    let focusSignIn=false;
    el('passkeyBtn').disabled=el('registerPasskeyBtn').disabled=true;
    el('loginErr').textContent='';
    try{
      if(!window.isSecureContext||!window.PublicKeyCredential)throw new Error('Passkeys require HTTPS and a supported browser. For local TEST use the localhost address.');
      const kind=register?'register':'login';
      const post=async(phase,body)=>{
        const {response,data}=await authRequest('/api/auth/'+kind+'/'+phase,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        if(!response.ok)throw new Error(data.error||'Passkey request failed. Retry.');
        return data;
      };
      el('passkeyStatus').textContent=register?'Confirm on your device to create a passkey.':'Confirm on your device to sign in.';
      const options=passkeyOptions(await post('begin',{}),register);
      const credential=register?await navigator.credentials.create(options):await navigator.credentials.get(options);
      const result=await post('complete',{credential:passkeyCredential(credential),label:el('passkeyLabel').value.trim()||'My device'});
      if(register){pendingRequest=result.pending_id;el('passkeyStatus').textContent=pendingMessage()}
      else{pendingRequest='';el('passkeyStatus').textContent='';enterSession(result)}
    }catch(error){
      el('passkeyStatus').textContent=pendingMessage();
      el('loginErr').textContent=passkeyErrorMessage(error,register);
      focusSignIn=register&&error.name==='InvalidStateError';
    }finally{busy=false;el('passkeyBtn').disabled=el('registerPasskeyBtn').disabled=false;if(focusSignIn)el('passkeyBtn').focus?.()}
  }
  el('passkeyBtn').onclick=()=>perform(false);
  el('registerPasskeyBtn').onclick=()=>perform(true);
}
