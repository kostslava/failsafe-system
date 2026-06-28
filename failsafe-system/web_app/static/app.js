const statusBadge = document.getElementById("status-badge");
const liveFrame = document.getElementById("live-frame");
const framePlaceholder = document.getElementById("frame-placeholder");
const updatedAt = document.getElementById("updated-at");
const analysisText = document.getElementById("analysis-text");
const progressValue = document.getElementById("progress-value");
const progressBar = document.getElementById("progress-bar");
const printStatus = document.getElementById("print-status");
const metricTtft = document.getElementById("metric-ttft");
const metricTps = document.getElementById("metric-tps");
const metricCompletion = document.getElementById("metric-completion");
const metricE2e = document.getElementById("metric-e2e");
const aiLog = document.getElementById("ai-log");

function formatSeconds(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return "—";
  }
  return `${Number(value).toFixed(3)}s`;
}

function formatNumber(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return "—";
  }
  return Number(value).toFixed(2);
}

function setStatusBadge(status) {
  statusBadge.textContent = status;
  statusBadge.classList.remove("status-safe", "status-halt", "status-init");

  if (status === "EMERGENCY HALT") {
    statusBadge.classList.add("status-halt");
    return;
  }

  if (status === "RUNNING SAFELY") {
    statusBadge.classList.add("status-safe");
    return;
  }

  statusBadge.classList.add("status-init");
}

function renderLogs(logs) {
  aiLog.innerHTML = "";
  if (!logs || logs.length === 0) {
    aiLog.textContent = "No inference events yet.";
    return;
  }

  logs.slice().reverse().forEach((entry) => {
    const line = document.createElement("p");
    line.textContent = entry;
    aiLog.appendChild(line);
  });
}

function applyState(state) {
  setStatusBadge(state.system_status || "INITIALIZING");
  updatedAt.textContent = state.updated_at ? `Updated ${state.updated_at}` : "—";
  analysisText.textContent = state.analysis || "";

  const progress = Number(state.print_progress || 0);
  progressValue.textContent = `${Math.round(progress)}%`;
  progressBar.style.width = `${Math.max(0, Math.min(100, progress))}%`;
  printStatus.textContent = state.print_status || "nominal";

  const timeInfo = state.time_info || {};
  metricTtft.textContent = formatSeconds(
    timeInfo.time_to_first_token ?? timeInfo.prompt_time
  );
  metricTps.textContent = formatNumber(timeInfo.tokens_per_second);
  metricCompletion.textContent = formatSeconds(timeInfo.completion_time);
  metricE2e.textContent = formatSeconds(
    timeInfo.end_to_end_latency ?? timeInfo.total_time
  );

  renderLogs(state.ai_logs);

  if (state.image_base64) {
    liveFrame.src = `data:image/jpeg;base64,${state.image_base64}`;
    liveFrame.classList.add("visible");
    framePlaceholder.style.display = "none";
  }
}

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws`);

  socket.addEventListener("message", (event) => {
    try {
      const state = JSON.parse(event.data);
      applyState(state);
    } catch (error) {
      console.error("Invalid dashboard payload", error);
    }
  });

  socket.addEventListener("close", () => {
    setTimeout(connectWebSocket, 1500);
  });
}

async function bootstrap() {
  try {
    const response = await fetch("/api/state");
    if (response.ok) {
      applyState(await response.json());
    }
  } catch (error) {
    console.warn("Unable to fetch initial dashboard state", error);
  }

  connectWebSocket();
}

bootstrap();
