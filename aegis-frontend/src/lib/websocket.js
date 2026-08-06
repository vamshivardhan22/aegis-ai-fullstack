export class WebSocketManager {
  constructor() {
    this.socket = null;
    this.reconnectAttempts = 0;
    this.maxReconnects = 5;
    this.closedByUser = false;
  }

  connect(url, onMessage, onStatus = () => {}) {
    this.closedByUser = false;
    this.url = url;
    this.onMessage = onMessage;
    this.onStatus = onStatus;
    this.socket = new WebSocket(url);
    this.socket.onopen = () => { this.reconnectAttempts = 0; onStatus("connected"); };
    this.socket.onmessage = (event) => {
      try { onMessage(JSON.parse(event.data)); } catch { onMessage(event.data); }
    };
    this.socket.onclose = () => { onStatus("disconnected"); if (!this.closedByUser) this.reconnect(); };
    this.socket.onerror = () => onStatus("error");
  }

  reconnect() {
    if (this.reconnectAttempts >= this.maxReconnects) return;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 12000);
    this.reconnectAttempts += 1;
    setTimeout(() => this.connect(this.url, this.onMessage, this.onStatus), delay);
  }

  send(payload) {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(payload));
  }

  disconnect() {
    this.closedByUser = true;
    this.socket?.close();
  }
}

export const pipelineSocket = new WebSocketManager();
