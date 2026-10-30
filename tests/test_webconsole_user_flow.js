'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../webconsole/webconsole_ui.html'), 'utf8');
const start = html.indexOf('function userAct(');
const end = html.indexOf('async function loadDiag(', start);
assert.ok(start >= 0 && end > start);
const source = html.slice(start, end);

function browser(accepted = true, prepareOK = true) {
  const calls = [];
  const fields = {newUserName: {value: 'operator'}, newUserPass: {value: 'Fake@123'}};
  const context = vm.createContext({
    decodeURIComponent, confirm: () => accepted, prompt: () => 'Fake@123',
    $: name => fields[name], toast: () => {}, setTimeout: () => {}, loadUsers: () => {},
    act: async body => {
      calls.push(JSON.parse(JSON.stringify(body)));
      if (body.action === 'prepare') return prepareOK ? {ok: true, nonce: 'test-nonce'} : {error: 'denied'};
      return {ok: true};
    }
  });
  vm.runInContext(source, context);
  context.requestPassword=async()=>accepted?'Fake@123':null;
  return {context, calls, fields};
}

test('authenticated startup initializes the selected route exactly once', () => {
  for(const route of ['users','settings','tools','docs','rdpsec','setup','backup','bandwidth','live']){
    const calls=[];const selected={dataset:{t:route}};
    const context=vm.createContext({started:false,appTimers:[],setInterval:()=>1,
      $:()=>({style:{}}),poll:()=>{},pollSetupJobs:()=>{},loadDay:()=>{},
      document:{querySelector:()=>selected},activateTab:tab=>calls.push(tab.dataset.t)});
    vm.runInContext(html.slice(html.indexOf('function startApp(){'),html.indexOf('async function authRequest(')),context);
    context.startApp();context.startApp();assert.deepEqual(calls,[route]);
  }
});

test('security watch flags distinguish enabled disabled and unknown',()=>{
  const context=vm.createContext({});
  vm.runInContext(html.slice(html.indexOf('function watchStatus('),html.indexOf('async function loadSec(')),context);
  assert.equal(context.watchStatus(true),'Enabled');assert.equal(context.watchStatus(false),'Disabled');
  for(const value of [undefined,null,'false',0])assert.equal(context.watchStatus(value),'Unknown');
  assert.match(html,/watchStatus\(c\.rdp_watch\)\+" \/ "\+watchStatus\(c\.net_watch\)/);
});

test('password dialog masks secrets and clears on submit or cancellation',async()=>{
  const fields={passwordDialog:{open:false,showModal(){this.open=true},close(){this.open=false;this.onclose()}},
    resetPassword:{value:'',type:'password',focus(){}},revealResetPassword:{checked:false},passwordForm:{},passwordAccount:{}};
  const context=vm.createContext({$:id=>fields[id],Promise});
  vm.runInContext(html.slice(html.indexOf('function requestPassword('),html.indexOf('async function userPass(')),context);
  const pending=context.requestPassword('<account>');assert.equal(fields.passwordAccount.textContent,'Windows local account: <account>');
  assert.equal(fields.resetPassword.type,'password');
  assert.equal(await context.requestPassword('other'),null);
  fields.resetPassword.value='secret';fields.revealResetPassword.checked=true;fields.revealResetPassword.onchange();
  assert.equal(fields.resetPassword.type,'text');fields.passwordForm.onsubmit({preventDefault(){}});
  assert.equal(await pending,'secret');assert.equal(fields.resetPassword.value,'');assert.equal(fields.resetPassword.type,'password');
  const cancelled=context.requestPassword('account');fields.resetPassword.value='discard';fields.passwordDialog.close();
  assert.equal(await cancelled,null);assert.equal(fields.resetPassword.value,'');
  assert.match(html,/<input id="resetPassword" type="password" required/);
});

test('panel reads distinguish transport auth HTTP malformed and incomplete responses',async()=>{
  let expired=0;
  const context=vm.createContext({Error,fetch:async()=>{},showLogin:()=>expired++});
  vm.runInContext(html.slice(html.indexOf('async function readPanelData('),html.indexOf('function watchStatus(')),context);
  for(const [fetcher,message] of [
    [async()=>{throw Error('offline')},/Cannot reach/],
    [async()=>({status:401}),/Sign in again/],
    [async()=>({ok:false,status:403,json:async()=>({error:'Forbidden'})}),/Forbidden/],
    [async()=>({ok:false,status:500,json:async()=>({})}),/HTTP 500/],
    [async()=>({ok:true,json:async()=>{throw Error('HTML')}}),/Invalid server response/],
    [async()=>({ok:true,json:async()=>({})}),/Incomplete/]
  ]){context.fetch=fetcher;await assert.rejects(context.readPanelData('/test',d=>Array.isArray(d.items)),message)}
  assert.equal(expired,1);
  context.fetch=async()=>({ok:true,json:async()=>({items:[]})});
  assert.equal((await context.readPanelData('/test',d=>Array.isArray(d.items))).items.length,0);
});

test('failed panel reads retain displayed data and provide inline retry',async()=>{
  for(const [name,end,status] of [
    ['loadBackup','function backupNow','backupLoadStatus'],['loadServices','function doSvcNamed','servicesLoadStatus'],
    ['loadNetstat','async function loadSysinfo','netstatLoadStatus'],['loadSysinfo','async function readPanelData','sysinfoLoadStatus'],
    ['loadSec','function showLogin','securityLoadStatus']
  ]){
    const notifications=[];
    const context=vm.createContext({readPanelData:async()=>{throw Error('Unavailable')},
      readPanelStatus:(...args)=>notifications.push(args),$:()=>{throw Error('Must not overwrite data')}});
    vm.runInContext(html.slice(html.indexOf('async function '+name+'('),html.indexOf(end,html.indexOf('async function '+name+'('))),context);
    await context[name]();assert.equal(notifications[0][0],status);assert.equal(typeof notifications[0][2],'function');
  }
  const status={textContent:'',append(button){this.button=button}};let retries=0;
  const context=vm.createContext({$:()=>status,document:{createElement:()=>({})},Date});
  vm.runInContext(html.slice(html.indexOf('function readPanelStatus('),html.indexOf('function watchStatus(')),context);
  context.readPanelStatus('status',Error('Offline'),()=>retries++);
  assert.match(status.textContent,/stale/);status.button.onclick();assert.equal(retries,1);
  context.readPanelStatus('status');assert.match(status.textContent,/Updated/);
});

test('panic confirmations accurately distinguish blocking from recovery',()=>{
  const messages=[],calls=[];let accepted=true;
  const context=vm.createContext({confirm:message=>{messages.push(message);return accepted},rdpAct:(op,args)=>calls.push([op,args.mode])});
  vm.runInContext(html.slice(html.indexOf('function rdpPanic('),html.indexOf('function blockSubnet(')),context);
  context.rdpPanic('on');context.rdpPanic('off');
  assert.match(messages[0],/blocks RDP for everyone/);assert.match(messages[0],/persists after reboot/);
  assert.match(messages[1],/removes the emergency RDP block/);assert.match(messages[1],/restrictions still apply/);
  assert.deepEqual(calls,[['panic','on'],['panic','off']]);
  accepted=false;context.rdpPanic('on');context.rdpPanic('off');context.rdpPanic('invalid');
  assert.equal(calls.length,2);assert.equal(messages.length,4);
});

test('all inline JavaScript parses', () => {
  const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)];
  assert.ok(scripts.length > 0);
  for (const script of scripts) new vm.Script(script[1]);
});

test('high-DPI canvas refreshes keep logical height stable and reset the transform',()=>{
  const code=html.slice(html.indexOf('function drawLine('),html.indexOf('function gridOver('));
  for(const dpr of [1,2,2.75,3,4]){
    let backingHeight=150,backingWidth=300;const transforms=[];
    const drawing=new Proxy({}, {get:(_target,name)=>name==='setTransform'?(...args)=>transforms.push(args):()=>{}});
    const canvas={dataset:{},style:{},clientWidth:300,getAttribute:()=>String(backingHeight),
      getContext:()=>drawing,getBoundingClientRect:()=>({left:0}),
      get height(){return backingHeight},set height(value){backingHeight=value},
      get width(){return backingWidth},set width(value){backingWidth=value}};
    const context=vm.createContext({window:{devicePixelRatio:dpr},Math,Number,String,parseInt});
    vm.runInContext(code,context);
    for(let i=0;i<200;i++)context.drawLine(canvas,[{c:'#8bcfff',data:[10,20,30]}],'%',100);
    const scale=Math.min(dpr,3);
    assert.equal(canvas.height,Math.round(150*scale));
    assert.equal(canvas.style.height,'150px');
    assert.equal(transforms.length,200);
    assert.deepEqual(transforms[199],[scale,0,0,scale,0,0]);
    canvas.clientWidth=390;context.drawLine(canvas,[{c:'#8bcfff',data:[15]}],'%',100);
    assert.equal(canvas.height,Math.round(150*scale));
    assert.equal(canvas.width,Math.round(390*scale));
  }
});

function authBrowser(fetchImpl, startFailure=false){
  const fields=Object.fromEntries(['app','loginBg','loginErr','loginBtn','loginToken','sessionIdentity','logoutBtn'].map(id=>[id,{style:{},value:id==='loginToken'?'test-token':'',textContent:'',disabled:false}]));
  const timers=[];const notifications=[];
  const context=vm.createContext({CSRF:'',started:false,loginBusy:false,appTimers:[1,2],$:id=>fields[id],
    fetch:fetchImpl,Error,Math,clearInterval:id=>timers.push(id),setInterval:()=>3,
    poll:()=>{},loadSec:()=>{},loadDay:()=>{},loadBackup:()=>{},toast:m=>notifications.push(m),location:{reload:()=>{}},
    document:{},notifications});
  const begin=html.indexOf('function showLogin('),end=html.indexOf('$("loginBtn").onclick',begin);
  vm.runInContext(html.slice(begin,end),context);
  if(startFailure)context.startApp=()=>{throw new Error('UI failed')};
  else context.startApp=()=>{context.started=true};
  return {context,fields,timers};
}

test('login distinguishes transport failure, invalid response, rejected token and UI startup',async()=>{
  for(const [fetchImpl,startFailure,expected] of [
    [async()=>{throw new Error('offline')},false,/Cannot reach/],
    [async()=>({json:async()=>{throw new Error('HTML')}}),false,/invalid response/],
    [async()=>({ok:false,status:401,json:async()=>({error:'invalid token'})}),false,/invalid token/],
    [async()=>({ok:true,json:async()=>({csrf:'test'})}),true,/Sign-in succeeded/]
  ]){
    const {context,fields}=authBrowser(fetchImpl,startFailure);await context.doLogin();
    assert.match(fields.loginErr.textContent,expected);
    assert.equal(fields.loginBtn.disabled,false);
  }
});

test('duplicate login submits once and sign-out stops polling',async()=>{
  let complete,calls=0;
  const {context,fields,timers}=authBrowser(()=>{calls++;return new Promise(resolve=>complete=resolve)});
  const pending=context.doLogin();await context.doLogin();assert.equal(calls,1);
  complete({ok:true,json:async()=>({csrf:'test',actor:'owner'})});await pending;
  assert.equal(fields.sessionIdentity.textContent,'owner');assert.equal(fields.loginToken.value,'');
  context.fetch=async()=>({ok:true,json:async()=>({ok:true})});
  await context.doLogout();assert.deepEqual(timers,[1,2]);assert.equal(context.CSRF,'');
});

test('hour history uses timestamps and persisted samples rather than 180 live samples',()=>{
  const now=Date.now();const context=vm.createContext({Date,Math});
  vm.runInContext(html.slice(html.indexOf('function gridOver('),html.indexOf('function drawAll(')),context);
  const points=[{t:(now-3500000)/1000,c:42},{t:(now-10000)/1000,c:17},{t:(now-3700000)/1000,c:99}];
  const buckets=context.gridOver(points,'c',3600000,60);
  assert.equal(buckets.length,60);assert.ok(buckets.includes(42));assert.ok(buckets.includes(17));assert.ok(!buckets.includes(99));
  assert.ok(buckets.includes(null));assert.match(html,/recent=\[\.\.\.dayHist,\.\.\.liveHist\]/);
});

test('missing adapter history stays a gap while a measured zero stays zero',()=>{
  const context=vm.createContext({Date,Math,Number});
  vm.runInContext(html.slice(html.indexOf('function gridOver('),html.indexOf('function drawAll(')),context);
  const now=Date.now();
  const missing=context.gridOver([{t:(now-1000)/1000,down:null}],'down',3600000,60);
  const zero=context.gridOver([{t:(now-1000)/1000,down:0}],'down',3600000,60);
  assert.equal(missing[59],null);assert.equal(zero[59],0);
});

test('failed user refresh keeps previous accounts and exposes retry', async () => {
  const tbody={innerHTML:'previous accounts'};
  const fields={usersStatus:{textContent:'',innerHTML:''},userTbl:{querySelector:()=>tbody}};
  const context=vm.createContext({$:id=>fields[id],Date,Error,Array,eh:String,
    fetch:async()=>({ok:false,json:async()=>({error:'Windows query failed'})})});
  vm.runInContext(html.slice(html.indexOf('async function loadUsers(){'),html.indexOf('function userAct(')),context);
  await context.loadUsers();
  assert.equal(tbody.innerHTML,'previous accounts');
  assert.match(fields.usersStatus.innerHTML,/Retry/);
  assert.match(fields.usersStatus.innerHTML,/Windows query failed/);
});

test('automation errors retain each previous list rather than render None', async () => {
  const fields={};
  for(const name of ['watch','keepalive','svcwatch']){
    fields['auto-'+name]={innerHTML:'saved entry'};
    fields['auto-'+name+'-status']={textContent:'',innerHTML:''};
  }
  const context=vm.createContext({$:id=>fields[id],Promise,Date,Error,Array,eh:String,
    fetch:async()=>({ok:false,json:async()=>({error:'Monitor unavailable'})})});
  vm.runInContext(html.slice(html.indexOf('async function loadAutomation(){'),html.indexOf('function autoAdd(')),context);
  await context.loadAutomation();
  for(const name of ['watch','keepalive','svcwatch']){
    assert.equal(fields['auto-'+name].innerHTML,'saved entry');
    assert.match(fields['auto-'+name+'-status'].innerHTML,/Retry/);
  }
});

test('user helper sends exact payload through the common confirmation dispatcher', async () => {
  const {context, calls} = browser();
  await context.confirmedUserAct({op: 'password', name: 'operator', value: 'Fake@123'});
  assert.deepEqual(calls, [
    {action: 'user', op: 'password', name: 'operator', value: 'Fake@123'}
  ]);
});

test('all user controls use the server confirmation flow', async () => {
  for (const [invoke, op] of [
    [c => c.userAct('disable', 'operator'), 'disable'],
    [c => c.userAct('delete', 'operator'), 'delete'],
    [c => c.userAct('enable', 'operator'), 'enable'],
    [c => c.userPass('operator'), 'password'],
    [c => c.userRename('operator'), 'rename'],
    [c => c.userAdd(), 'add']
  ]) {
    const {context, calls} = browser();
    invoke(context);
    await new Promise(setImmediate);
    assert.equal(calls.length, 1, op);
    assert.equal(calls[0].action, 'user');
    assert.equal(calls[0].op, op);
  }
});

test('cancelled user controls send no request', async () => {
  const {context, calls} = browser(false);
  context.userAct('delete', 'operator');
  context.userPass('operator');
  context.userRename('operator');
  context.userAdd();
  await new Promise(setImmediate);
  assert.equal(calls.length, 0);
});

function actionBrowser(prepareOK = true, extras = {}) {
  const calls = [];
  const actionStart = html.indexOf('const CONFIRMED_ACTIONS=');
  const actionEnd = html.indexOf('function kill(', actionStart);
  const context = vm.createContext({
    CSRF: 'fake', toast: () => {}, showLogin: () => {},
    fetch: async (url, options) => {
      const body = JSON.parse(options.body);
      calls.push(body);
      const preparing = body.action === 'prepare';
      return {status: preparing && !prepareOK ? 400 : 200, ok: !preparing || prepareOK,
        json: async () => preparing ? (prepareOK ? {ok: true, nonce: 'generic-nonce'} : {error: 'denied'}) : {ok: true}};
    }, ...extras
  });
  vm.runInContext(html.slice(actionStart, actionEnd), context);
  return {context, calls};
}

test('generic destructive actions prepare matching arguments before dispatch', async () => {
  for (const body of [{action:'user',op:'password',name:'operator',value:'Fake@123'},
    {action:'kill',pids:[111]}, {action:'rdp',op:'panic',mode:'on'},
    {action:'run_command',cmd:'FAKE'}, {action:'settings_set',key:'exec',value:'on',confirm:true}]) {
    const {context, calls} = actionBrowser();
    await context.act(body);
    assert.equal(calls.length, 2);
    const {action, ...args} = body;
    assert.deepEqual(calls[0], {...args, action:'prepare', target:action});
    assert.deepEqual(calls[1], {...body, nonce:'generic-nonce'});
  }
});

test('duplicate clicks share one request and the button stays busy through preparation', async () => {
  let click, release;
  const requests = [];
  const button = {innerHTML:'Block IP',disabled:false,textContent:'Block IP',busy:null,
    getAttribute(){return this.busy}, setAttribute(k,v){this.busy=v}, removeAttribute(){this.busy=null}};
  const gate = new Promise(resolve => {release=resolve});
  const {context} = actionBrowser(true, {
    document:{addEventListener:(type,fn)=>{click=fn}}, queueMicrotask,
    fetch:async (url,options)=>{
      const body=JSON.parse(options.body);requests.push(body);
      if(body.action==='prepare')await gate;
      return {ok:true,status:200,json:async()=>body.action==='prepare'?{ok:true,nonce:'once'}:{ok:true}};
    }
  });
  click({target:{closest:()=>button}});
  const first=context.act({action:'block_ip',ip:'203.0.113.1'});
  const second=context.act({action:'block_ip',ip:'203.0.113.1'});
  assert.equal(first,second);
  assert.equal(button.disabled,true);
  assert.equal(button.busy,'true');
  assert.equal(button.textContent,'Working…');
  release();await first;
  assert.equal(requests.length,2);
  assert.equal(button.disabled,false);
  assert.equal(button.busy,null);
  assert.equal(button.innerHTML,'Block IP');
});

test('busy state is released after network failure, expired authentication and rejected preparation', async () => {
  for(const mode of ['network','auth','prepare']){
    let click;
    const button={innerHTML:'Run',disabled:false,busy:null,
      getAttribute(){return this.busy},setAttribute(k,v){this.busy=v},removeAttribute(){this.busy=null}};
    const {context}=actionBrowser(true,{
      document:{addEventListener:(type,fn)=>{click=fn}},queueMicrotask,
      fetch:async()=>{
        if(mode==='network')throw Error('offline');
        return {ok:false,status:mode==='auth'?401:400,json:async()=>({error:'denied'})};
      }
    });
    click({target:{closest:()=>button}});
    await context.act({action:'kill',pids:[123]});
    assert.equal(button.disabled,false,mode);
    assert.equal(button.busy,null,mode);
    assert.equal(button.innerHTML,'Run',mode);
  }
});

test('generic failed preparation sends no destructive request', async () => {
  const {context, calls} = actionBrowser(false);
  await context.act({action:'restore',name:'fake.zip'});
  assert.equal(calls.length, 1);
  assert.equal(calls[0].action, 'prepare');
});

test('read-only variants and preconfirmed requests do not prepare again', async () => {
  for (const body of [{action:'rdp',op:'rdp_status'}, {action:'service',mode:'status'},
    {action:'automation',op:'list'}, {action:'shutdown',nonce:'already-issued'}]) {
    const {context, calls} = actionBrowser();
    await context.act(body);
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0], body);
  }
});
const setupSource=fs.readFileSync(path.join(__dirname,'../webconsole/setup.js'),'utf8');

test('failed initial cloud discovery preserves the saved image target and blocks destination saves until recovery',async()=>{
 const element=()=>({value:'',dataset:{},textContent:'',firstChild:{},replaceChildren(){},append(){},querySelector(){return {textContent:''}}});
 const fields=new Proxy({}, {get:(obj,key)=>obj[key]??=element()});
 fields.setupProvider.value='drive';
 const data={cloud:{healthy:true,version:'fixture',remotes:[],error:'Unavailable',image_target:'gdrive:Images',backup_targets:['gdrive:'],folder:'Backups'},images:{enabled:false,files:[],phase:null},backup:{sources:['C:\\Data'],schedule:{enabled:true,mode:'daily',time:'03:00'},timezone:'UTC'},remote:{bind:'127.0.0.1',port:8399,allowed_ips:[]},jobs:[]};
 const calls=[],messages=[];
 const context=vm.createContext({$:id=>fields[id],eh:String,Date,document:{activeElement:{closest:()=>null},createElement:element},toast:m=>messages.push(m),fetch:async()=>({ok:true,json:async()=>data})});
 vm.runInContext(setupSource,context);context.renderSetupJobs=()=>{};context.setupDo=(op,args)=>calls.push({op,args});
 await context.loadSetup();
 assert.equal(fields.setupImageRemote.value,'gdrive:');assert.equal(fields.setupImageFolder.value,'Images');
 assert.match(fields.setupImageRemote.innerHTML,/unavailable/);
 context.setupTargets();assert.equal(calls.length,0);
 fields.setupImageRemote.value='';context.setupTargets();assert.equal(calls.length,0);assert.match(messages.at(-1),/discovery/);
 fields.setupImageRemote.value='gdrive:';fields.setupImageFolder.value='unsaved-folder';
 data.cloud.error='';data.cloud.remotes=['gdrive:'];await context.loadSetup();
 assert.equal(fields.setupImageFolder.value,'unsaved-folder');context.setupTargets();
 assert.equal(calls.length,1);assert.equal(calls[0].args.image,'gdrive:unsaved-folder');
});

test('password reveal uses its visible accessible label rather than an implementation identifier',()=>{
 assert.match(html,/<label for="revealResetPassword"><input id="revealResetPassword" type="checkbox"> Show password<\/label>/);
 assert.doesNotMatch(html,/id="revealResetPassword"[^>]*aria-label="revealResetPassword"/);
});
test('cloud choices refresh without overwriting drafts and flag removed selections',()=>{
 const fields={setupImageRemote:{value:'draft:',dataset:{}},setupClientRemote:{value:'old',dataset:{}},
   setupRemoteChoices:{},setupImageFolder:{value:'unsaved-folder'},setupBackupTargets:{value:'draft:path'}};
 const messages=[];let submitted=0;
 const context=vm.createContext({$:id=>fields[id],eh:String,toast:m=>messages.push(m)});
 vm.runInContext(setupSource,context);vm.runInContext('setupLoaded=true;setupCloudReady=true',context);context.setupDo=()=>submitted++;
 context.syncSetupRemoteChoices(['draft:','new:']);
 assert.equal(fields.setupImageRemote.value,'draft:');assert.equal(fields.setupImageRemote.dataset.unavailable,'false');
 assert.match(fields.setupImageRemote.innerHTML,/new:/);assert.match(fields.setupClientRemote.innerHTML,/unavailable/);
 assert.equal(fields.setupClientRemote.dataset.unavailable,'true');
 context.syncSetupRemoteChoices(['new:']);assert.equal(fields.setupImageRemote.dataset.unavailable,'true');
 context.setupTargets();assert.equal(submitted,0);assert.match(messages[0],/unavailable/);
 assert.equal(fields.setupImageFolder.value,'unsaved-folder');assert.equal(fields.setupBackupTargets.value,'draft:path');
 context.syncSetupRemoteChoices(['new:'],'');assert.equal(fields.setupImageRemote.value,'');assert.equal(fields.setupImageRemote.dataset.unavailable,'false');
 context.syncSetupRemoteChoices(['new:'],'missing:');assert.equal(fields.setupImageRemote.value,'missing:');
 assert.match(fields.setupImageRemote.innerHTML,/disabled value="missing:"/);
});

test('setup script parses and form secrets clear only after accepted submission',async()=>{
 const fields={setupOptions:{value:'{}'},setupRemoteName:{value:'test'},setupProvider:{value:'s3'},setupOAuthToken:{value:''}};
 const secret={value:'fake-secret',dataset:{option:'secret_access_key'}};const calls=[];
 const context=vm.createContext({$:id=>fields[id],document:{querySelectorAll:()=>[secret]},JSON,toast:()=>{}});
 vm.runInContext(setupSource,context);
 context.setupDo=async(op,args)=>{calls.push({op,args});return {ok:false}};
 await context.setupCreate(false);assert.equal(secret.value,'fake-secret');
 context.setupDo=async(op,args)=>{calls.push({op,args});return {ok:true}};
 await context.setupCreate(false);assert.equal(secret.value,'');assert.equal(calls[1].args.options.secret_access_key,'fake-secret');
});
test('setup cancellation sends nothing and adding a browsed source preserves existing paths',async()=>{
 const field={value:'C:\\Data'};let called=false;
 const context=vm.createContext({$:()=>field,confirm:()=>false,act:()=>{called=true},toast:()=>{}});
 vm.runInContext(setupSource,context);await context.setupDo('remote',{},'Change?');assert.equal(called,false);
 context.setupAddSource('D:\\Files');context.setupAddSource('D:\\Files');assert.equal(field.value,'C:\\Data\nD:\\Files');
});
test('active imaging refreshes progress even after the launch job has completed',async()=>{
 const context=vm.createContext({$:()=>({style:{display:''}}),document:{activeElement:{closest:()=>null}},fetch:async()=>({ok:true,json:async()=>({jobs:[]})}),Date});
 vm.runInContext(setupSource,context);let refreshed=0;context.renderSetupJobs=()=>{};context.loadSetup=()=>{refreshed++};
 vm.runInContext('setupImagesActive=true;setupLastRefresh=Date.now()-11000',context);
 await context.pollSetupJobs();assert.equal(refreshed,1);
 vm.runInContext('setupImagesActive=false',context);await context.pollSetupJobs();assert.equal(refreshed,1);
});
