/* Owner setup forms. Secrets are sent only in confirmed POST bodies. */
let setupLoaded=false,setupBusy=false,setupJobsBusy=false,setupJobSignature='',setupTokenTimer,setupImagesActive=false,setupLastRefresh=0,setupCloudReady=false;
const setupFields={drive:[['client_id','OAuth client ID (optional)'],['client_secret','OAuth client secret (optional)','password']],onedrive:[['client_id','OAuth client ID (optional)'],['client_secret','OAuth client secret (optional)','password']],dropbox:[],s3:[['provider','S3 provider (AWS / Wasabi / Minio / Other)'],['access_key_id','Access key ID'],['secret_access_key','Secret access key','password'],['endpoint','Endpoint URL (optional)'],['region','Region (optional)']],b2:[['account','Application key ID'],['key','Application key','password']],sftp:[['host','Server hostname'],['user','Username'],['pass','Password','password'],['port','Port (optional)']],ftp:[['host','Server hostname'],['user','Username'],['pass','Password','password']],webdav:[['url','WebDAV URL'],['vendor','Vendor (other / nextcloud / owncloud)'],['user','Username'],['pass','Password','password']]};
function setupLines(id){return $(id).value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean)}
function setupJump(index){document.querySelectorAll('#tab-setup section')[index].scrollIntoView({behavior:'smooth',block:'start'})}
let suiteUpdateLoaded=false,suiteUpdateBusy=false;
async function loadSuiteUpdate(){
  if(suiteUpdateBusy)return;suiteUpdateBusy=true;
  try{
    const response=await fetch('/api/suite-update'),data=await response.json();
    if(!response.ok)throw new Error(data.error||'Update status unavailable');
    $('suiteUpdateVersion').textContent='Installed: '+(data.current||'unknown').slice(0,12)+(data.state.available?' · Available: '+data.state.available.slice(0,12):'');
    $('suiteUpdateCredentialStatus').textContent=data.credential_saved?'A GitHub credential is saved.':'No GitHub credential saved. Public repositories do not need one.';
    $('suiteUpdateStatus').textContent=(data.installed?'':'Updater task is not installed. Run the suite installer. ')+(data.state.phase||'not checked')+' · '+(data.state.message||'No check yet.')+(data.state.checked_at?' · Last check: '+new Date(data.state.checked_at*1000).toLocaleString():'');
    if(!suiteUpdateLoaded){$('suiteUpdateEnabled').value=String(data.settings.enabled);$('suiteUpdateHours').value=data.settings.interval_hours;suiteUpdateLoaded=true}
  }catch(error){$('suiteUpdateStatus').textContent=error.message+' · Refresh status to retry.'}
  finally{suiteUpdateBusy=false}
}
async function suiteUpdateAction(op,args={}){
  if(!confirm(op==='apply'?'Install the latest validated release? The bot and panel restart. Failed health checks trigger rollback.':'Apply this update operation? Automatic installation can restart the bot and panel when a release is available.'))return;
  const result=await act({action:'suite_update',op,...args},true);
  if(result?.ok){toast(result.out);loadSuiteUpdate()}
}
function saveSuiteUpdates(){
  const hours=Number($('suiteUpdateHours').value);
  if(!Number.isInteger(hours)||hours<1||hours>168){toast('Choose an interval from 1 to 168 hours.',true);return}
  return suiteUpdateAction('configure',{enabled:$('suiteUpdateEnabled').value==='true',hours});
}
async function saveSuiteUpdateCredential(remove=false){
  const input=$('suiteUpdateCredential');
  if(!remove&&!input.value.trim()){toast('Enter a GitHub read credential.',true);return}
  if(!confirm(remove?'Remove the updater GitHub credential? Private release checks will stop working.':'Save this GitHub credential using Windows encryption?'))return;
  const result=await act({action:'suite_update',op:'credential',value:remove?'':input.value.trim()},true);
  if(result?.ok){input.value='';toast(result.out);loadSuiteUpdate()}
}
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
  $('setupOAuth').querySelector('code').textContent='rclone authorize "'+type+'"';
  $('setupOAuthToken').value='';
}
function setupScheduleHint(){
  const mode=$('setupScheduleMode').value;
  $('setupScheduleLabel').firstChild.textContent=mode==='interval'?'Interval · hours':mode==='times'?'Times · HH:MM,HH:MM':'Time · HH:MM';
  $('setupScheduleValue').placeholder=mode==='interval'?'6':mode==='times'?'03:00,15:00':'03:00';
}
function syncSetupRemoteChoices(remotes,imageSelection=null){
  for(const [id,values,empty] of [
    ['setupImageRemote',remotes,true],['setupClientRemote',remotes.map(r=>r.slice(0,-1)),false]
  ]){
    const select=$(id),selected=id==='setupImageRemote'&&imageSelection!==null?imageSelection:select.value;
    const missing=Boolean(selected&&!values.includes(selected));
    select.innerHTML=(empty?'<option value="">No cloud upload</option>':'')+
      values.map(value=>'<option value="'+eh(value)+'">'+eh(value)+'</option>').join('')+
      (missing?'<option disabled value="'+eh(selected)+'">'+eh(selected)+' (unavailable — choose another remote)</option>':'');
    if(selected||empty)select.value=selected;
    select.dataset.unavailable=String(missing);
    select.dataset.unavailableValue=missing?selected:'';
  }
  $('setupRemoteChoices').innerHTML=remotes.map(r=>'<option value="'+eh(r)+'">').join('');
}
async function loadSetup(reset=false){
  if(setupBusy)return;setupBusy=true;
  try{
    const r=await fetch('/api/setup'),d=await r.json();
    if(!r.ok)throw new Error(d.error||'Setup unavailable');
    setupCloudReady=!d.cloud.error;
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
    setupImagesActive=active;setupLastRefresh=Date.now();
    $('setupImageStatus').textContent=(images.phase||'Idle')+' · '+(images.enabled?'Imaging enabled':'Imaging disabled')+(images.percent!=null&&images.phase==='uploading'?' · '+images.percent+'%':'')+' '+(images.detail||'');
    $('setupImageStart').disabled=active||!images.enabled;
    $('setupImageFiles').replaceChildren();
    for(const f of images.files){const row=document.createElement('div');row.className='setup-image';const label=document.createElement('div');label.textContent=f.path+' · '+hb(f.size)+' · '+new Date(f.modified*1000).toLocaleString();row.append(label);for(const [text,op] of [['Upload','image_upload'],['Share link','image_link']]){const button=document.createElement('button');button.className='btn';button.textContent=text;button.disabled=active;button.onclick=()=>setupDo(op,{path:f.path},op==='image_link'?'Create a public share link for this uploaded image?':'Upload '+f.path+' to the saved image destination?');row.append(button)}$('setupImageFiles').append(row)}
    if(!images.files.length)$('setupImageFiles').textContent='No FULLSYSTEM VHDX images found on the server.';
    const remote=d.remote;
    $('setupRemoteStatus').textContent='Current: '+remote.bind+':'+remote.port+' · '+(remote.https?'HTTPS':'HTTP')+' · '+(remote.allowed_ips.join(', ')||'local only');
    $('setupTimezone').textContent='Times use the server timezone: '+d.backup.timezone+'. Existing retry settings are preserved.';
    if(!d.cloud.error)syncSetupRemoteChoices(d.cloud.remotes);
    if(!setupLoaded||reset){
      if(!setupLoaded)setupProviderFields();
      if(d.cloud.error&&setupLoaded)throw new Error('Remote list failed; your current form values were retained. Retry refresh.');
      const split=d.cloud.image_target.indexOf(':');const savedImageRemote=split>=0?d.cloud.image_target.slice(0,split+1):'';$('setupImageFolder').value=split>=0?d.cloud.image_target.slice(split+1):'';
      $('setupBackupTargets').value=d.cloud.backup_targets.join('\n');$('setupBackupFolder').value=d.cloud.folder;
      $('setupSourcePaths').value=d.backup.sources.join('\n');
      const s=d.backup.schedule;$('setupScheduleEnabled').value=String(s.enabled!==false);$('setupScheduleMode').value=s.mode||'daily';$('setupScheduleValue').value=s.mode==='interval'?s.interval_hours:s.mode==='times'?(s.times||[]).join(','):s.time||'03:00';setupScheduleHint();
      $('setupAccessMode').value=['127.0.0.1','localhost','::1'].includes(remote.bind)?'local':remote.allowed_ips.includes('0.0.0.0/0')?'public':'restricted';$('setupAllowedIps').value=remote.allowed_ips.join('\n');
      // Initial discovery may fail even though a destination is already saved.
      // Keep it visibly unavailable rather than silently selecting no upload.
      syncSetupRemoteChoices(d.cloud.error?[]:d.cloud.remotes,savedImageRemote);
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
  try{const r=await fetch('/api/setup/jobs'),d=await r.json();if(!r.ok)throw new Error(d.error||'Operation status unavailable');renderSetupJobs(d.jobs);const signature=d.jobs.map(j=>j.id+j.state).join();if(signature!==setupJobSignature||(setupImagesActive&&Date.now()-setupLastRefresh>=10000)){setupJobSignature=signature;loadSetup()}}
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
  if(!$('setupClientRemote').value||$('setupClientRemote').value===$('setupClientRemote').dataset.unavailableValue){toast('Choose an available cloud remote first.',true);return}
  const j=await setupDo('client',{name:$('setupClientRemote').value,client_id:$('setupClientId').value,client_secret:$('setupClientSecret').value},'Update the OAuth client for this remote?');
  if(j?.ok)$('setupClientSecret').value='';
}
function setupTargets(){
  if(!setupLoaded||!setupCloudReady){toast('Cloud discovery is unavailable. Refresh saved settings before changing destinations.',true);return}
  const remote=$('setupImageRemote').value;
  if(remote&&remote===$('setupImageRemote').dataset.unavailableValue){toast('The selected image remote is unavailable. Choose another remote or explicitly select No cloud upload.',true);return}
  return setupDo('targets',{image:remote?remote+$('setupImageFolder').value.trim():'',backups:setupLines('setupBackupTargets'),folder:$('setupBackupFolder').value},'Replace cloud destinations? Empty destinations disable cloud copies; existing cloud files remain.');
}
function setupSchedule(){return setupDo('schedule',{enabled:$('setupScheduleEnabled').value==='true',mode:$('setupScheduleMode').value,value:$('setupScheduleValue').value},'Save this automatic backup schedule in the server timezone?')}
function setupRemote(){return setupDo('remote',{mode:$('setupAccessMode').value,ips:setupLines('setupAllowedIps')},'Apply panel access settings? The panel will restart and sign you out. Restricted IPs can prevent this device from reconnecting. Keep RDP access available.')}
async function setupRevealToken(){
  if(!confirm('Reveal the owner login token on this screen for one minute?'))return;
  const j=await act({action:'setup_token'},true);
  if(j?.ok){$('setupLoginToken').textContent=j.out.token;clearTimeout(setupTokenTimer);setupTokenTimer=setTimeout(()=>$('setupLoginToken').textContent='',60000)}
}
