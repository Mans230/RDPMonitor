'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../webconsole/passkeys.js'),'utf8');

function fixture(mode='passkey'){
  const fields={},calls=[],sessions=[];
  const el=id=>fields[id]||(fields[id]={hidden:false,value:'My laptop'});
  const options={publicKey:{challenge:'AQID',rp:{id:'localhost'},user:{id:'BAUG'},excludeCredentials:[{id:'BwgJ'}]}};
  const credential={id:'AQID',rawId:Uint8Array.from([1,2,3]).buffer,type:'public-key',
    response:{clientDataJSON:Uint8Array.from([4,5,6]).buffer,
      attestationObject:Uint8Array.from([7,8,9]).buffer,getTransports:()=>['internal']},
    getClientExtensionResults:()=>({})};
  const context=vm.createContext({Uint8Array,atob,btoa,Error,
    document:{getElementById:el},window:{isSecureContext:true,PublicKeyCredential:function(){}},
    navigator:{credentials:{create:async()=>credential,get:async()=>credential}}});
  vm.runInContext(source,context);
  const authRequest=async(path,request)=>{
    calls.push({path,request});
    const data=path.endsWith('config')?{mode}:path.endsWith('begin')?structuredClone(options):
      path.includes('register')?{pending_id:'012345abcdef',approved:false}:{csrf:'session-csrf',actor:'owner'};
    return {response:{ok:true},data};
  };
  return {context,fields,el,calls,sessions,credential,configure:()=>context.configurePasskeys({authRequest,enterSession:d=>sessions.push(d)})};
}

test('registration shows local approval request and does not enter a session',async()=>{
  const f=fixture();await f.configure();
  assert.equal(f.el('tokenLogin').hidden,true);
  assert.equal(f.el('passkeyLogin').hidden,false);
  await f.el('registerPasskeyBtn').onclick();
  assert.deepEqual(f.calls.map(x=>x.path),['/api/auth/config','/api/auth/register/begin','/api/auth/register/complete']);
  assert.equal(f.sessions.length,0);
  assert.match(f.el('passkeyStatus').textContent,/012345abcdef.*local administrator approval/);
  const body=JSON.parse(f.calls[2].request.body);
  assert.equal(body.credential.response.attestationObject,'BwgJ');
  assert.equal(body.label,'My laptop');
  assert.equal(f.el('passkeyBtn').disabled,false);
});

test('login enters session only after server verifies the credential',async()=>{
  const f=fixture();await f.configure();
  delete f.credential.response.attestationObject;
  f.credential.response.authenticatorData=Uint8Array.from([1,2]).buffer;
  f.credential.response.signature=Uint8Array.from([3,4]).buffer;
  f.credential.response.userHandle=Uint8Array.from([5,6]).buffer;
  await f.el('passkeyBtn').onclick();
  assert.equal(f.sessions[0].csrf,'session-csrf');
  const response=JSON.parse(f.calls[2].request.body).credential.response;
  assert.equal(response.authenticatorData,'AQI');
  assert.equal(response.signature,'AwQ');
  assert.equal(response.userHandle,'BQY');
});

test('unsupported browser and cancellation offer retry without a session',async()=>{
  const f=fixture();await f.configure();f.context.window.isSecureContext=false;
  await f.el('passkeyBtn').onclick();
  assert.match(f.el('loginErr').textContent,/HTTPS/);assert.equal(f.calls.length,1);
  f.context.window.isSecureContext=true;
  f.context.navigator.credentials.get=async()=>{const e=new Error();e.name='NotAllowedError';throw e};
  await f.el('passkeyBtn').onclick();
  assert.match(f.el('loginErr').textContent,/cancelled or timed out/);
  assert.equal(f.sessions.length,0);assert.equal(f.el('passkeyBtn').disabled,false);
});

test('existing token mode remains available only when configured',async()=>{
  const f=fixture('token');await f.configure();
  assert.equal(f.el('tokenLogin').hidden,false);
  assert.equal(f.el('passkeyBtn').onclick,undefined);
});
