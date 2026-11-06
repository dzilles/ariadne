'use strict';
const $ = (id) => document.getElementById(id);
const state = { session: null, stream: null, connected: false, run: null, busy: false, syncing: false, pending: [], drafts: new Map(), known: new Set(), completed: new Set(), ticket: 0 };
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Ariadne-Client': 'ui' }, body: JSON.stringify(body) });
  const result = await response.json();
  if (!result.ok) throw new Error(result.error.message);
  return result.result;
}
function notice(text) { $('notice').textContent = text || ''; $('notice').hidden = !text; }
function connection(ready) { state.connected = ready; $('connection').classList.toggle('ready', ready); $('connection').querySelector('span').textContent = ready ? 'Connected' : 'Reconnecting'; controls(); }
function controls() { $('send').disabled = !state.connected || state.busy || state.syncing || !$('message').value.trim(); $('stop').hidden = !state.busy; $('stop').disabled = !state.run; }
function scroll() { const chat = document.querySelector('.chat'); chat.scrollTop = chat.scrollHeight; }
function addMessage(id, role, content) {
  if (state.known.has(id)) return state.drafts.get(id);
  state.known.add(id);
  const row = document.createElement('article'); row.className = `message ${role}`;
  const avatar = document.createElement('div'); avatar.className = 'avatar'; avatar.textContent = role === 'user' ? 'YOU' : 'a';
  const body = document.createElement('div'); body.className = 'message-body';
  const label = document.createElement('div'); label.className = 'message-label'; label.textContent = role === 'user' ? 'You' : 'Ariadne';
  const text = document.createElement('div'); text.className = 'message-text'; text.textContent = content || '';
  body.append(label, text); row.append(avatar, body); $('messages').append(row); state.drafts.set(id, text); $('welcome').hidden = true;
  return text;
}
function renderConversation(conversation) {
  $('messages').replaceChildren(); state.drafts.clear(); state.known.clear(); state.completed.clear(); $('welcome').hidden = true;
  $('conversation-title').textContent = conversation.title; state.run = conversation.active_run_id; state.busy = conversation.state === 'running';
  $('model').textContent = `${conversation.provider_id} / ${conversation.model}`;
  for (const message of conversation.messages) {
    if (message.role === 'tool') {
      const details = document.createElement('details'); details.className = 'tool-history';
      const summary = document.createElement('summary'); summary.textContent = 'Task tool result';
      const text = document.createElement('pre');
      try { text.textContent = JSON.stringify(JSON.parse(message.content), null, 2); } catch { text.textContent = message.content; }
      details.append(summary, text); $('messages').append(details);
    } else { if (message.role === 'assistant') state.completed.add(message.id); if (message.content) addMessage(message.id, message.role, message.content); }
  }
  $('welcome').hidden = conversation.messages.some((message) => message.role === 'user');
  if (conversation.last_error) notice(conversation.last_error.message);
  controls(); scroll();
}
async function refreshSessions() {
  const sessions = await api('/api/conversations'); $('sessions').replaceChildren();
  for (const session of sessions) { const button = document.createElement('button'); button.textContent = session.title; button.title = session.title; button.classList.toggle('selected', session.id === state.session); button.addEventListener('click', () => select(session.id).catch((error) => notice(error.message))); $('sessions').append(button); }
  return sessions;
}
async function refreshTasks() {
  const tasks = await api('/api/tasks'); $('task-count').textContent = tasks.length; $('tasks').replaceChildren();
  if (!tasks.length) { const empty = document.createElement('div'); empty.className = 'tasks-empty'; const symbol = document.createElement('span'); symbol.textContent = '◇'; empty.append(symbol, document.createTextNode('A little space for your next idea.')); $('tasks').append(empty); }
  for (const task of tasks) { const card = document.createElement('article'); card.className = 'task'; const status = document.createElement('div'); status.className = `task-status ${task.status}`; status.textContent = task.status.replaceAll('_', ' '); const description = document.createElement('p'); description.textContent = task.description; const tags = document.createElement('small'); tags.textContent = task.tags.join(' · '); card.append(status, description, tags); $('tasks').append(card); }
}
async function select(id) {
  const ticket = ++state.ticket; if (state.stream) state.stream.close(); state.session = id; state.connected = false; state.run = null; state.busy = false; state.syncing = true; state.pending = []; $('activity').textContent = ''; notice(''); connection(false); $('sidebar').classList.remove('open');
  localStorage.setItem('ariadne-session', id);
  const initial = await api(`/api/conversations/${encodeURIComponent(id)}`); if (ticket !== state.ticket) return; renderConversation(initial);
  await refreshSessions(); if (ticket !== state.ticket) return;
  const stream = new EventSource(`/api/events/${encodeURIComponent(id)}`); state.stream = stream;
  let retryScheduled = false;
  function retry() { if (retryScheduled) return; retryScheduled = true; stream.close(); setTimeout(() => { if (ticket === state.ticket) select(id).catch((error) => notice(error.message)); }, 1000); }
  stream.onopen = async () => { if (ticket !== state.ticket) return; state.syncing = true; state.pending = []; connection(false); try { const conversation = await api(`/api/conversations/${encodeURIComponent(id)}`); if (ticket !== state.ticket) return; renderConversation(conversation); state.syncing = false; connection(true); const pending = state.pending; state.pending = []; for (const event of pending) await handle(event); } catch (error) { if (ticket === state.ticket) { notice(error.message); retry(); } } };
  stream.onerror = () => { if (ticket === state.ticket) { state.syncing = true; connection(false); if (stream.readyState === EventSource.CLOSED) retry(); } };
  async function handle(event) {
    if (ticket !== state.ticket) return;
    const payload = event.payload;
    switch (payload.type) {
      case 'message_started': if (!state.completed.has(payload.message_id)) { state.busy = true; state.run = event.context.run_id; controls(); } break;
      case 'message_delta': { if (state.completed.has(payload.message_id)) break; const text = state.drafts.get(payload.message_id) || addMessage(payload.message_id, 'assistant', ''); text.textContent += payload.text; scroll(); break; }
      case 'message_finished': state.completed.add(payload.message_id); if (payload.text) { const text = state.drafts.get(payload.message_id) || addMessage(payload.message_id, 'assistant', ''); text.textContent = payload.text; scroll(); } break;
      case 'activity_updated': $('activity').textContent = `${payload.label.replaceAll('_', ' ')} · ${payload.state}`; break;
      case 'error': notice(payload.error.message); break;
      case 'run_finished': if (state.run && event.context.run_id !== state.run) break; state.busy = false; state.run = null; state.syncing = true; $('activity').textContent = ''; controls(); try { const conversation = await api(`/api/conversations/${encodeURIComponent(id)}`); if (ticket !== state.ticket) return; renderConversation(conversation); await Promise.all([refreshSessions(), refreshTasks()]); } catch (error) { notice(error.message); } finally { if (ticket === state.ticket) { state.syncing = false; controls(); } } break;
      case 'input_requested': notice(payload.prompt); break;
      default: break;
    }
  }
  stream.onmessage = (message) => { if (ticket !== state.ticket) return; try { const event = JSON.parse(message.data); if (state.syncing && !state.connected) state.pending.push(event); else handle(event).catch((error) => notice(error.message)); } catch (error) { notice(error.message); } };
}
async function newConversation() { const conversation = await api('/api/conversations', {}); await select(conversation.id); $('message').focus(); }
async function send(text) {
  if (!text.trim() || state.busy || state.syncing || !state.connected) return;
  const session = state.session; state.busy = true; notice(''); controls(); $('message').value = '';
  const optimisticId = `local-${Date.now()}`; addMessage(optimisticId, 'user', text); scroll();
  try { const result = await api('/api/commands', { session_id: session, payload: { type: 'send_message', text } }); if (session === state.session && state.busy) state.run = result.command_id; controls(); }
  catch (error) { if (session !== state.session) return; state.busy = false; notice(error.message); $('message').value = text; controls(); }
}
$('composer').addEventListener('submit', (event) => { event.preventDefault(); send($('message').value).catch((error) => notice(error.message)); });
$('message').addEventListener('input', controls);
$('message').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('composer').requestSubmit(); } });
$('new-chat').addEventListener('click', () => newConversation().catch((error) => notice(error.message)));
$('menu').addEventListener('click', () => $('sidebar').classList.toggle('open'));
$('stop').addEventListener('click', async () => { if (!state.run) return; try { await api('/api/commands', { session_id: state.session, payload: { type: 'cancel_run', run_id: state.run } }); $('activity').textContent = 'Stopping…'; } catch (error) { notice(error.message); } });
document.querySelectorAll('[data-prompt]').forEach((button) => button.addEventListener('click', () => { $('message').value = button.dataset.prompt; controls(); $('message').focus(); }));
(async () => {
  try { const status = await api('/api/status'); $('project').textContent = status.project_id; $('model').textContent = `${status.provider || 'API not configured'} / ${status.model || 'Choose a model'}`; const sessions = await refreshSessions(); await refreshTasks(); const saved = localStorage.getItem('ariadne-session'); if (sessions.length) await select(sessions.find((session) => session.id === saved)?.id || sessions[0].id); else await newConversation(); if (!status.credentials_ready) notice('Set the configured API key before starting Ariadne, then restart the app.'); }
  catch (error) { notice(error.message); }
})();
