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
  return {context, calls, fields};
}

test('all inline JavaScript parses', () => {
  const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)];
  assert.ok(scripts.length > 0);
  for (const script of scripts) new vm.Script(script[1]);
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
