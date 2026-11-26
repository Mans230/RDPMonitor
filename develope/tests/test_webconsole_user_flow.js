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

test('user helper prepares exact payload before confirmed dispatch', async () => {
  const {context, calls} = browser();
  await context.confirmedUserAct({op: 'password', name: 'operator', value: 'Fake@123'});
  assert.deepEqual(calls, [
    {action: 'prepare', target: 'user', op: 'password', name: 'operator', value: 'Fake@123'},
    {action: 'user', op: 'password', name: 'operator', value: 'Fake@123', nonce: 'test-nonce'}
  ]);
});

test('failed preparation never dispatches user mutation', async () => {
  const {context, calls} = browser(true, false);
  await context.confirmedUserAct({op: 'delete', name: 'operator'});
  assert.equal(calls.length, 1);
  assert.equal(calls[0].action, 'prepare');
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
    assert.equal(calls.length, 2, op);
    assert.equal(calls[0].action, 'prepare');
    assert.equal(calls[1].nonce, 'test-nonce');
    assert.equal(calls[1].op, op);
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

function actionBrowser(prepareOK = true) {
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
    }
  });
  vm.runInContext(html.slice(actionStart, actionEnd), context);
  return {context, calls};
}

test('generic destructive actions prepare matching arguments before dispatch', async () => {
  for (const body of [{action:'kill',pids:[111]}, {action:'rdp',op:'panic',mode:'on'},
    {action:'run_command',cmd:'FAKE'}, {action:'settings_set',key:'exec',value:'on',confirm:true}]) {
    const {context, calls} = actionBrowser();
    await context.act(body);
    assert.equal(calls.length, 2);
    const {action, ...args} = body;
    assert.deepEqual(calls[0], {...args, action:'prepare', target:action});
    assert.deepEqual(calls[1], {...body, nonce:'generic-nonce'});
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
