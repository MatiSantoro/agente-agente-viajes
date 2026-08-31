const config = window.TRAVEL_UI_CONFIG;
document.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.target.id === 'prompt') {
    event.preventDefault();
    document.querySelector('#composer').requestSubmit();
  }
});
const store = window.sessionStorage;
const loginView = document.querySelector('#login-view');
const appView = document.querySelector('#app-view');
const messages = document.querySelector('#messages');
const form = document.querySelector('#composer');
const promptInput = document.querySelector('#prompt');
const modelInput = document.querySelector('#model');
const temperatureInput = document.querySelector('#temperature');
const temperatureValue = document.querySelector('#temperature-value');
const modelNote = document.querySelector('#model-note');

function sessionId() { let id = store.getItem('travel-session-id'); if (!id) { id = crypto.randomUUID(); store.setItem('travel-session-id', id); } return id; }
function token() { return store.getItem('access-token'); }
function normalizeMarkdown(content) { return content.replace(/([.!?])\s*(?=[🔍🔄])/gu, '$1\n\n').replace(/([🔍🔄])(?=[A-ZÁÉÍÓÚÑ])/gu, '$1\n\n'); }
function addMessage(kind, content, markdown = false) { const el = document.createElement('article'); el.className = `message ${kind}`; if (markdown && window.marked && window.DOMPurify) el.innerHTML = DOMPurify.sanitize(marked.parse(normalizeMarkdown(content))); else el.textContent = content; messages.append(el); messages.scrollTop = messages.scrollHeight; return el; }
const modelNotes = {
  claude: 'Balanced creativity with reliable tool calls.',
  nova: 'Nova uses temperature 0 for reliable AgentCore tool invocation.',
  qwen: 'Experimental: limited to 0.3 for grounded tool calls.',
  kimi: 'Experimental: limited to 0.3 for grounded tool calls.',
  deepseek: 'Experimental: limited to 0.3 for grounded tool calls.',
};
function setModelState(reset = false) { const experimental = ['qwen', 'kimi', 'deepseek'].includes(modelInput.value); const nova = modelInput.value === 'nova'; temperatureInput.disabled = nova; temperatureInput.max = experimental ? '0.3' : '1'; if (nova || (experimental && (reset || Number(temperatureInput.value) > 0.3))) temperatureInput.value = '0'; else if (reset) temperatureInput.value = '0.2'; temperatureValue.value = temperatureInput.value; modelNote.textContent = modelNotes[modelInput.value]; }
function autoSize() { promptInput.style.height = 'auto'; promptInput.style.height = `${Math.min(promptInput.scrollHeight, 160)}px`; }
async function submit(event) { event.preventDefault(); const text = promptInput.value.trim(); if (!text) return; addMessage('user', text); promptInput.value = ''; autoSize(); const submitButton = form.querySelector('button'); submitButton.disabled = true; const pending = addMessage('agent', '<div class="thinking"><i></i><i></i><i></i> Planning your trip</div>', true); try { const response = await fetch(config.apiUrl, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: token() }, body: JSON.stringify({ message: text, sessionId: sessionId(), model: modelInput.value, temperature: Number(temperatureInput.value) }) }); const data = await response.json(); if (!response.ok) throw new Error(data.message || 'The agent could not complete that request.'); pending.remove(); addMessage('agent', data.markdown, true); } catch (error) { pending.remove(); addMessage('agent', `I couldn’t complete that: ${error.message}`); } finally { submitButton.disabled = false; promptInput.focus(); } }
function openApp() { loginView.hidden = true; appView.hidden = false; sessionId(); promptInput.focus(); }
if (token()) openApp();
window.travelUi = { openApp, store };
document.querySelector('#sign-out').addEventListener('click', () => { store.clear(); location.reload(); }); form.addEventListener('submit', submit); promptInput.addEventListener('input', autoSize); modelInput.addEventListener('change', () => setModelState(true)); temperatureInput.addEventListener('input', () => setModelState()); setModelState();
