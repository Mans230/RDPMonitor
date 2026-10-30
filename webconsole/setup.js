/* Owner setup forms. Secrets are sent only in confirmed POST bodies. */
let setupLoaded=false,setupBusy=false,setupJobsBusy=false,setupJobSignature='',setupTokenTimer;
const setupFields={drive:[['client_id','OAuth client ID (optional)'],['client_secret','OAuth client secret (optional)','password']],onedrive:[['client_id','OAuth client ID (optional)'],['client_secret','OAuth client secret (optional)','password']],dropbox:[],s3:[['provider','S3 provider (AWS / Wasabi / Minio / Other)'],['access_key_id','Access key ID'],['secret_access_key','Secret access key','password'],['endpoint','Endpoint URL (optional)'],['region','Region (optional)']],b2:[['account','Application key ID'],['key','Application key','password']],sftp:[['host','Server hostname'],['user','Username'],['pass','Password','password'],['port','Port (optional)']],ftp:[['host','Server hostname'],['user','Username'],['pass','Password','password']],webdav:[['url','WebDAV URL'],['vendor','Vendor (other / nextcloud / owncloud)'],['user','Username'],['pass','Password','password']]};
function setupLines(id){return $(id).value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean)}
function setupJump(index){document.querySelectorAll('#tab-setup section')[index].scrollIntoView({behavior:'smooth',block:'start'})}
function setupAddSource(path){const paths=setupLines('setupSourcePaths');if(!paths.includes(path))paths.push(path);$('setupSourcePaths').value=paths.join('\n');toast('Added to the form. Save source paths to apply.')}
async function loadSetupBrowse(path='',offset=0){
  const root=$('setupBrowser');
  try{
    const r=await fetch('/api/setup/browse?path='+encodeURIComponent(path)+'&offset='+offset),d=await r.json();if(!r.ok)throw new Error(d.error||'Folder unavailable');
    root.replaceChildren();const title=document.createElement('p');title.textContent=d.path||'Server drives';root.append(title);
    const add=(label,fn)=>{const b=document.createElement('button');b.type='button';b.className='btn';b.textContent=label;b.onclick=fn;return b};
    if(d.path){root.append(add('Parent folder',()=>loadSetupBrowse(d.parent)),add('Add this folder',()=>setupAddSource(d.path)))}
    for(const item of d.items){const row=document.createElement('div');row.className='setup-remote';row.append(add(item.name+(item.directory?' /':''),()=>item.directory?loadSetupBrowse(item.path):setupAddSource(item.path)),add('Add',()=>setupAddSource(item.path)));root.append(row)}
    if(d.next!==null)root.append(add('Next 100',()=>loadSetupBrowse(d.path,d.next)));
    if(offset)root.append(add('Previous 100',()=>loadSetupBrowse(d.path,Math.max(0,offset-100))));
  }catch(e){root.textContent=e.message+'. Reopen Browse server files to retry.'}
}
function setupProviderFields(){
  const type=$('setupProvider').value;
  $('setupProviderFields').innerHTML=setupFields[type].map(([key,label,kind])=>'<label>'+eh(label)+'<input data-option="'+key+'" type="'+(kind||'text')+'" autocomplete="'+(kind==='password'?'new-password':'off')+'"></label>').join('');
  $('setupOAuth').hidden=!['drive','onedrive','dropbox'].includes(type);
  $('setupOAuthToken').value='';
}
function setupScheduleHint(){
  const mode=$('setupScheduleMode').value;
  $('setupScheduleLabel').firstChild.textContent=mode==='interval'?'Interval · hours':mode==='times'?'Times · HH:MM,HH:MM':'Time · HH:MM';
  $('setupScheduleValue').placeholder=mode==='interval'?'6':mode==='times'?'03:00,15:00':'03:00';
}
async function loadSetup(reset=false){
  if(setupBusy)return;setupBusy=true;
  try{
    const r=await fetch('/api/setup'),d=await r.json();
    if(!r.ok)throw new Error(d.error||'Setup unavailable');
    $('setupError').textContent='';
    $('setupCloudStatus').textContent=(d.cloud.healthy?d.cloud.version:'rclone unavailable: '+d.cloud.version)+(d.cloud.error?' · '+d.cloud.error:'');
    $('setupRemotes').replaceChildren();
    for(const remote of d.cloud.remotes){
      const row=document.createElement('div');row.className='setup-remote';
      const label=document.createElement('span');label.textContent=remote;row.append(label);
      for(const [text,op] of [['Test','test'],['Remove','delete']]){const b=document.createElement('button');b.className='btn';b.textContent=text;b.onclick=()=>setupDo(op,op==='test'?{target:remote}:{name:remote.slice(0,-1)},text+' '+remote+'? Removing a remote does not delete cloud files.');row.append(b)}
      const use=document.createElement('button');use.className='btn';use.textContent='Use for backups';use.onclick=()=>{const targets=setupLines('setupBackupTargets');if(!targets.includes(remote))targets.push(remote);$('setupBackupTargets').value=targets.join('\n');setupJump(1);toast('Destination added to the form. Save destinations to apply.')};row.append(use);
      $('setupRemotes').append(row);
    }
    if(!d.cloud.remotes.length)$('setupRemotes').textContent=d.cloud.error?'Remote list unavailable. Retry refresh.':'No cloud accounts yet. Add one below.';
    const images=d.images,active=['imaging','uploading'].includes(images.phase);
    $('setupImageStatus').textContent=(images.phase||'Idle')+' · '+(images.enabled?'Imaging enabled':'Imaging disabled')+(images.percent!=null&&images.phase==='uploading'?' · '+images.percent+'%':'')+' '+(images.detail||'');
    $('setupImageStart').disabled=active||!images.enabled;
    $('setupImageFiles').replaceChildren();
    for(const f of images.files){const row=document.createElement('div');row.className='setup-image';const label=document.createElement('div');label.textContent=f.path+' · '+hb(f.size)+' · '+new Date(f.modified*1000).toLocaleString();row.append(label);for(const [text,op] of [['Upload','image_upload'],['Share link','image_link']]){const button=document.createElement('button');button.className='btn';button.textContent=text;button.disabled=active;button.onclick=()=>setupDo(op,{path:f.path},op==='image_link'?'Create a public share link for this uploaded image?':'Upload '+f.path+' to the saved image destination?');row.append(button)}$('setupImageFiles').append(row)}
    if(!images.files.length)$('setupImageFiles').textContent='No FULLSYSTEM VHDX images found on the server.';
    const remote=d.remote;
    $('setupRemoteStatus').textContent='Current: '+remote.bind+':'+remote.port+' · '+(remote.https?'HTTPS':'HTTP')+' · '+(remote.allowed_ips.join(', ')||'local only');
    $('setupTimezone').textContent='Times use the server timezone: '+d.backup.timezone+'. Existing retry settings are preserved.';
    if(!setupLoaded||reset){
      if(d.cloud.error&&setupLoaded)throw new Error('Remote list failed; your current form values were retained. Retry refresh.');
      $('setupImageRemote').innerHTML='<option value="">No cloud upload</option>'+d.cloud.remotes.map(r=>'<option value="'+eh(r)+'">'+eh(r)+'</option>').join('');
      $('setupClientRemote').innerHTML=d.cloud.remotes.map(r=>'<option value="'+eh(r.slice(0,-1))+'">'+eh(r)+'</option>').join('');
      $('setupRemoteChoices').innerHTML=d.cloud.remotes.map(r=>'<option value="'+eh(r)+'">').join('');
      const split=d.cloud.image_target.indexOf(':');$('setupImageRemote').value=split>=0?d.cloud.image_target.slice(0,split+1):'';$('setupImageFolder').value=split>=0?d.cloud.image_target.slice(split+1):'';
      $('setupBackupTargets').value=d.cloud.backup_targets.join('\n');$('setupBackupFolder').value=d.cloud.folder;
      $('setupSourcePaths').value=d.backup.sources.join('\n');
      const s=d.backup.schedule;$('setupScheduleEnabled').value=String(s.enabled!==false);$('setupScheduleMode').value=s.mode||'daily';$('setupScheduleValue').value=s.mode==='interval'?s.interval_hours:s.mode==='times'?(s.times||[]).join(','):s.time||'03:00';setupScheduleHint();
      $('setupAccessMode').value=['127.0.0.1','localhost','::1'].includes(remote.bind)?'local':remote.allowed_ips.includes('0.0.0.0/0')?'public':'restricted';$('setupAllowedIps').value=remote.allowed_ips.join('\n');
      setupLoaded=true;
    }
    if(!document.activeElement.closest('#setupJobs form'))renderSetupJobs(d.jobs);
  }catch(e){$('setupError').textContent=e.message+' · Use Refresh saved settings to retry.'}
  finally{setupBusy=false}
}
function renderSetupJobs(jobs){
  const root=$('setupJobs');root.replaceChildren();
  for(const j of [...jobs].reverse()){
    const row=document.createElement('div');row.className='setup-job';
    const status=document.createElement('p');status.textContent=j.op+' · '+j.state+' · '+j.message;row.append(status);
    if(j.auth_url){const p=document.createElement('p');p.textContent='On the server only: '+j.auth_url;row.append(p)}
    if(j.state==='running'&&(j.auth_url||j.question)){const button=document.createElement('button');button.className='btn';button.textContent='Cancel sign-in / setup';button.onclick=()=>setupDo('cancel',{job:j.id},'Cancel this sign-in or provider question?');row.append(button)}
    if(j.question){
      const q=j.question,form=document.createElement('form'),label=document.createElement('label');label.textContent=q.name;
      const input=document.createElement('input');input.type=q.secret?'password':'text';input.autocomplete='off';input.required=q.required;input.value=q.default;label.append(input);form.append(label);
      if(q.choices.length){const select=document.createElement('select');select.innerHTML='<option value="">Choose a value</option>'+q.choices.map(c=>'<option value="'+eh(c.value)+'">'+eh(c.label||c.value)+'</option>').join('');select.onchange=()=>{input.value=select.value};form.append(select)}
      const button=document.createElement('button');button.className='btn';button.textContent='Continue setup';form.append(button);form.onsubmit=e=>{e.preventDefault();setupDo('answer',{job:j.id,question:q.id,value:input.value},'Send this answer to the cloud provider setup?');input.value=''};row.append(form);
    }
    root.append(row);
  }
  if(!jobs.length)root.textContent='No setup operations since the monitor started.';
}
async function pollSetupJobs(){
  if(setupJobsBusy||$('tab-setup').style.display||document.activeElement.closest('#setupJobs form'))return;
  setupJobsBusy=true;
  try{const r=await fetch('/api/setup/jobs'),d=await r.json();if(!r.ok)throw new Error(d.error||'Operation status unavailable');renderSetupJobs(d.jobs);const signature=d.jobs.map(j=>j.id+j.state).join();if(signature!==setupJobSignature){setupJobSignature=signature;loadSetup()}}
  catch(e){$('setupError').textContent=e.message+'. Reopen the panel if access settings changed.'}
  finally{setupJobsBusy=false}
}
async function setupDo(op,args,message){
  if(!confirm(message))return;
  const j=await act({action:'setup',op,...args},true);
  if(j?.ok){toast('Operation submitted. Follow its status in Setup.');await pollSetupJobs()}
  return j;
}
async function setupCreate(authorize){
  try{
    const options=JSON.parse($('setupOptions').value||'{}');
    for(const input of document.querySelectorAll('#setupProviderFields input'))if(input.value)options[input.dataset.option]=input.value;
    const args={name:$('setupRemoteName').value.trim(),provider:$('setupProvider').value,options,token:$('setupOAuthToken').value};
    const result=await setupDo(authorize?'authorize':'create',args,authorize?'Start sign-in on this Windows server? Complete it through RDP.':'Create this cloud remote with the supplied credentials?');
    if(result?.ok){$('setupOAuthToken').value='';$('setupOptions').value='';document.querySelectorAll('#setupProviderFields input').forEach(i=>i.value='')}
  }catch(e){toast('Check provider options: '+e.message,true)}
}
async function setupClient(){
  const j=await setupDo('client',{name:$('setupClientRemote').value,client_id:$('setupClientId').value,client_secret:$('setupClientSecret').value},'Update the OAuth client for this remote?');
  if(j?.ok)$('setupClientSecret').value='';
}
function setupTargets(){const remote=$('setupImageRemote').value;return setupDo('targets',{image:remote?remote+$('setupImageFolder').value.trim():'',backups:setupLines('setupBackupTargets'),folder:$('setupBackupFolder').value},'Replace cloud destinations? Empty destinations disable cloud copies; existing cloud files remain.')}
function setupSchedule(){return setupDo('schedule',{enabled:$('setupScheduleEnabled').value==='true',mode:$('setupScheduleMode').value,value:$('setupScheduleValue').value},'Save this automatic backup schedule in the server timezone?')}
function setupRemote(){return setupDo('remote',{mode:$('setupAccessMode').value,ips:setupLines('setupAllowedIps')},'Apply panel access settings? The panel will restart and sign you out. Restricted IPs can prevent this device from reconnecting. Keep RDP access available.')}
async function setupRevealToken(){
  if(!confirm('Reveal the owner login token on this screen for one minute?'))return;
  const j=await act({action:'setup_token'},true);
  if(j?.ok){$('setupLoginToken').textContent=j.out.token;clearTimeout(setupTokenTimer);setupTokenTimer=setTimeout(()=>$('setupLoginToken').textContent='',60000)}
}
