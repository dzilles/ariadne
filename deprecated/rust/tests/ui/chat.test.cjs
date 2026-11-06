const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

// A small DOM boundary lets these tests exercise the shipped chat script and
// async event races without a browser, HTTP server, or external packages.
class Element {
  constructor() { this.children = []; this.value = ''; this.hidden = false; this.listeners = new Map(); this.classes = new Set(); this._text = ''; this.classList = { toggle: (name, force) => { const on = force ?? !this.classes.has(name); if (on) this.classes.add(name); else this.classes.delete(name); return on; }, remove: (name) => this.classes.delete(name) }; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((child) => child.textContent || '').join(''); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  addEventListener(name, listener) { this.listeners.set(name, listener); }
  querySelector() { return this.span ||= new Element(); }
  focus() {}
}
function conversation(id, messages = []) { return { id, title: id.toUpperCase(), model: 'example/model', provider_id: 'openrouter', state: 'idle', active_run_id: null, messages, last_error: null }; }
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
const tick = () => new Promise((resolve) => setImmediate(resolve));

async function boot(initial = conversation('a')) {
  const elements = new Map();
  const element = (id) => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const backend = { conversations: new Map([[initial.id, initial]]), overrides: new Map(), calls: [] };
  const sources = []; const timers = [];
  class EventSource {
    static CLOSED = 2;
    constructor(url) { this.url = url; sources.push(this); }
    close() { this.closed = true; }
    emit(type, payload = {}, run = 'command-1') { this.onmessage({ data: JSON.stringify({ context: { run_id: run }, payload: { type, ...payload } }) }); }
  }
  const context = {
    document: { getElementById: element, createElement: () => new Element(), createTextNode: (text) => ({ textContent: text }), querySelector: element, querySelectorAll: () => [] },
    localStorage: { getItem: () => null, setItem: () => {} }, EventSource, console, setTimeout: (callback) => timers.push(callback),
    fetch: async (url, options = {}) => {
      backend.calls.push({ url, options });
      const override = backend.overrides.get(url);
      let result;
      if (override) result = await override(options);
      else if (url === '/api/status') result = { project_id: 'project', provider: 'openrouter', model: 'example/model', credentials_ready: true };
      else if (url === '/api/tasks') result = [];
      else if (url === '/api/conversations') result = [...backend.conversations.values()].map(({ id, title }) => ({ id, title }));
      else if (url.startsWith('/api/conversations/')) result = structuredClone(backend.conversations.get(url.slice(19)));
      else if (url === '/api/commands') result = { command_id: 'command-1' };
      else throw new Error(`Unexpected request ${url}`);
      return { json: async () => ({ ok: true, result }) };
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../src/ui/app.js'), 'utf8') + '\nglobalThis.chat = { state, select, send };', context);
  await tick(); await tick();
  assert.equal(sources.length, 1);
  await sources[0].onopen();
  return { ...context.chat, backend, sources, timers, element };
}

test('sending uses the common command API and literal streamed text', async () => {
  const chat = await boot();
  await chat.send('Create a streaming task');
  const submitted = chat.backend.calls.find((call) => call.url === '/api/commands');
  assert.deepEqual(JSON.parse(submitted.options.body), { session_id: 'a', payload: { type: 'send_message', text: 'Create a streaming task' } });
  assert.equal(submitted.options.headers['X-Ariadne-Client'], 'ui');
  chat.sources[0].emit('message_started', { message_id: 'reply' });
  chat.sources[0].emit('message_delta', { message_id: 'reply', text: '<script>literal text</script>' });
  assert.equal(chat.state.drafts.get('reply').textContent, '<script>literal text</script>');
  assert.equal(chat.state.drafts.get('reply').children.length, 0);
  assert.equal(chat.state.run, 'command-1');
  assert.equal(chat.element('send').disabled, true);
});

test('reconnect does not duplicate text already in the saved conversation', async () => {
  const chat = await boot(conversation('a', [{ id: 'user', role: 'user', content: 'hello' }, { id: 'saved', role: 'assistant', content: 'Saved reply' }]));
  chat.sources[0].emit('message_delta', { message_id: 'saved', text: 'Saved reply' });
  chat.sources[0].emit('message_finished', { message_id: 'saved', text: 'Saved reply' });
  assert.equal(chat.state.drafts.get('saved').textContent, 'Saved reply');
});

test('events arriving during reconnect are buffered until history is loaded', async () => {
  const chat = await boot();
  const history = deferred(); chat.backend.overrides.set('/api/conversations/a', () => history.promise);
  const reconnect = chat.sources[0].onopen();
  await tick();
  chat.sources[0].emit('message_started', { message_id: 'in-flight' });
  chat.sources[0].emit('message_delta', { message_id: 'in-flight', text: 'Still streaming' });
  assert.equal(chat.state.pending.length, 2);
  history.resolve({ ...conversation('a'), state: 'running', active_run_id: 'command-1' });
  await reconnect;
  assert.equal(chat.state.drafts.get('in-flight').textContent, 'Still streaming');
  assert.equal(chat.state.busy, true);
});

test('a slow previous-session response cannot replace the selected conversation', async () => {
  const chat = await boot();
  chat.backend.conversations.set('b', conversation('b', [{ id: 'b-user', role: 'user', content: 'B only' }]));
  const old = deferred(); chat.backend.overrides.set('/api/conversations/a', () => old.promise);
  const selectingA = chat.select('a');
  await chat.select('b');
  old.resolve(conversation('a'));
  await selectingA;
  assert.equal(chat.state.session, 'b');
  assert.equal(chat.element('conversation-title').textContent, 'B');
  assert.equal(chat.sources.at(-1).url, '/api/events/b');
  assert.equal(chat.state.drafts.get('b-user').textContent, 'B only');
});

test('a failed send from another conversation cannot reset the current UI', async () => {
  const chat = await boot();
  const submitted = deferred(); chat.backend.overrides.set('/api/commands', () => submitted.promise);
  const sending = chat.send('message in A');
  chat.backend.conversations.set('b', conversation('b'));
  await chat.select('b'); await chat.sources.at(-1).onopen();
  submitted.reject(new Error('old connection failed'));
  await sending;
  assert.equal(chat.state.session, 'b');
  assert.equal(chat.element('message').value, '');
  assert.equal(chat.element('notice').textContent, '');
});

test('finishing a turn blocks another send until saved history is restored', async () => {
  const chat = await boot(); await chat.send('hello');
  const history = deferred(); chat.backend.overrides.set('/api/conversations/a', () => history.promise);
  chat.sources[0].emit('run_finished', { outcome: 'completed' });
  await tick();
  assert.equal(chat.state.syncing, true);
  await chat.send('must wait');
  assert.equal(chat.backend.calls.filter((call) => call.url === '/api/commands').length, 1);
  history.resolve(conversation('a', [{ id: 'user', role: 'user', content: 'hello' }, { id: 'reply', role: 'assistant', content: 'Hello back' }]));
  await tick(); await tick();
  assert.equal(chat.state.syncing, false);
  assert.equal(chat.state.drafts.get('reply').textContent, 'Hello back');
});

test('a refused replacement event stream is retried after the old subscriber closes', async () => {
  const chat = await boot(); const previous = chat.sources[0];
  previous.readyState = 2; previous.onerror();
  assert.equal(chat.state.connected, false); assert.equal(previous.closed, true);
  assert.equal(chat.timers.length, 1); chat.timers[0]();
  await tick(); await tick();
  assert.equal(chat.sources.length, 2); await chat.sources[1].onopen();
  assert.equal(chat.state.connected, true);
});
