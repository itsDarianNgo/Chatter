const WS_URL = `ws://${window.location.hostname}:8080/ws`;
const MAX_MESSAGES = 1000;
const FLUSH_INTERVAL_MS = 75;

const statusEl = document.getElementById("status");
const messagesEl = document.getElementById("messages");
const buffer = [];
let ws;
let reconnectAttempts = 0;
let flushTimer;

function setStatus(state) {
  statusEl.textContent = state;
  statusEl.className = "status status-" + state.toLowerCase();
}

function connect() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => {
    setStatus("Connected");
    reconnectAttempts = 0;
    ws.send(JSON.stringify({ type: "subscribe", room_id: "room:demo" }));
  };
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      buffer.push(msg);
    } catch (err) {
      console.error("Failed to parse message", err);
    }
  };
  ws.onclose = () => {
    setStatus("Reconnecting");
    scheduleReconnect();
  };
  ws.onerror = () => {
    ws.close();
  };
}

function scheduleReconnect() {
  const delay = Math.min(1000 * 2 ** reconnectAttempts, 10000);
  reconnectAttempts += 1;
  setTimeout(connect, delay);
}

function renderMessage(msg) {
  const container = document.createElement("div");
  container.className = "message";

  const name = document.createElement("span");
  name.className = "display-name";
  name.textContent = msg.display_name || msg.user_id;
  if (msg.style && msg.style.name_color) {
    name.style.color = msg.style.name_color;
  }

  const badges = document.createElement("span");
  badges.className = "badges";
  (msg.badges || []).forEach((b) => {
    const tag = document.createElement("span");
    tag.className = "badge";
    tag.textContent = b;
    badges.appendChild(tag);
  });

  const content = document.createElement("span");
  content.className = "content";
  content.textContent = msg.content;

  container.appendChild(badges);
  container.appendChild(name);
  container.appendChild(content);
  return container;
}

function flushBuffer() {
  if (buffer.length === 0) return;
  const fragment = document.createDocumentFragment();
  while (buffer.length > 0) {
    const msg = buffer.shift();
    fragment.appendChild(renderMessage(msg));
  }
  messagesEl.appendChild(fragment);
  while (messagesEl.children.length > MAX_MESSAGES) {
    messagesEl.removeChild(messagesEl.firstChild);
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function startFlushLoop() {
  flushTimer = setInterval(flushBuffer, FLUSH_INTERVAL_MS);
}

window.addEventListener("load", () => {
  connect();
  startFlushLoop();
});
