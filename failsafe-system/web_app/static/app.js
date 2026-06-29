const statusBadge = document.getElementById("status-badge");
const statusLabel = statusBadge.querySelector(".status-label");
const liveStream = document.getElementById("live-stream");
const framePlaceholder = document.getElementById("frame-placeholder");
const snapshotAura = document.getElementById("snapshot-aura");
const analyzingBadge = document.getElementById("analyzing-badge");
const resetBtn = document.getElementById("reset-btn");
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

let lastSnapshotAt = null;
let resetInFlight = false;

const STATUS_LABELS = {
  "RUNNING SAFELY": "Running safely",
  "EMERGENCY HALT": "Emergency halt",
  INITIALIZING: "Initializing",
};

function formatSeconds(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return "—";
  }
  return `${Number(value).toFixed(2)}s`;
}

function formatNumber(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return "—";
  }
  return Number(value).toFixed(1);
}

function formatTimestamp(iso) {
  if (!iso) {
    return "—";
  }
  try {
    const date = new Date(iso);
    return date.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

function setStatusBadge(status) {
  const label = STATUS_LABELS[status] || status;
  statusLabel.textContent = label;

  statusBadge.classList.remove("status-pill--safe", "status-pill--halt", "status-pill--init");
  document.body.classList.remove("is-safe", "is-halt", "is-init");

  if (status === "EMERGENCY HALT") {
    statusBadge.classList.add("status-pill--halt");
    document.body.classList.add("is-halt");
    resetBtn.classList.remove("hidden");
    resetBtn.disabled = resetInFlight;
    return;
  }

  resetBtn.classList.add("hidden");
  resetBtn.disabled = true;

  if (status === "RUNNING SAFELY") {
    statusBadge.classList.add("status-pill--safe");
    document.body.classList.add("is-safe");
    return;
  }

  statusBadge.classList.add("status-pill--init");
  document.body.classList.add("is-init");
}

function setPrintStatusChip(status) {
  printStatus.textContent = status || "nominal";
  printStatus.classList.remove("chip--danger", "chip--ok", "chip--neutral");

  if (status === "critical_failure") {
    printStatus.classList.add("chip--danger");
    return;
  }

  if (status === "nominal") {
    printStatus.classList.add("chip--ok");
    return;
  }

  printStatus.classList.add("chip--neutral");
}

function triggerSnapshotAura() {
  snapshotAura.classList.remove("active");
  void snapshotAura.offsetWidth;
  snapshotAura.classList.add("active");
}

function parseLogEntry(entry) {
  const match = entry.match(/^\[(.+?)\]\s*(.+)$/);
  if (!match) {
    return { time: "", message: entry };
  }
  return { time: formatTimestamp(match[1]), message: match[2] };
}

function renderLogs(logs) {
  aiLog.innerHTML = "";
  aiLog.classList.toggle("log-empty", !logs || logs.length === 0);

  if (!logs || logs.length === 0) {
    return;
  }

  logs.slice().reverse().forEach((entry) => {
    const { time, message } = parseLogEntry(entry);
    const row = document.createElement("div");
    row.className = "log-entry";
    if (/CRITICAL|FAILURE|halt|pause failed/i.test(message)) {
      row.classList.add("log-entry--alert");
    }

    const timeEl = document.createElement("span");
    timeEl.className = "log-time";
    timeEl.textContent = time || "—";

    const msgEl = document.createElement("p");
    msgEl.className = "log-msg";
    msgEl.textContent = message;

    row.appendChild(timeEl);
    row.appendChild(msgEl);
    aiLog.appendChild(row);
  });
}

function applyState(state) {
  setStatusBadge(state.system_status || "INITIALIZING");
  updatedAt.textContent = state.updated_at
    ? `Updated ${formatTimestamp(state.updated_at)}`
    : "—";

  const analysis = state.analysis || "";
  analysisText.textContent = analysis || "No assessment yet.";

  const progress = Number(state.print_progress || 0);
  progressValue.textContent = `${Math.round(progress)}%`;
  progressBar.style.width = `${Math.max(0, Math.min(100, progress))}%`;
  setPrintStatusChip(state.print_status);

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

  analyzingBadge.classList.toggle("hidden", !state.analyzing);

  if (state.snapshot_at && state.snapshot_at !== lastSnapshotAt) {
    lastSnapshotAt = state.snapshot_at;
    triggerSnapshotAura();
  }
}

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws`);

  socket.addEventListener("message", (event) => {
    try {
      applyState(JSON.parse(event.data));
    } catch (error) {
      console.error("Invalid dashboard payload", error);
    }
  });

  socket.addEventListener("close", () => {
    setTimeout(connectWebSocket, 1500);
  });
}

async function resetMonitoring() {
  if (resetInFlight) {
    return;
  }

  resetInFlight = true;
  resetBtn.disabled = true;
  resetBtn.textContent = "Resuming…";

  try {
    const response = await fetch("/api/reset", { method: "POST" });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "Reset failed");
    }
    lastSnapshotAt = null;
  } catch (error) {
    console.error("Reset failed", error);
    alert("Could not resume monitoring. Try again in a moment.");
  } finally {
    resetInFlight = false;
    resetBtn.textContent = "Resume monitoring";
    resetBtn.disabled = false;
  }
}

function setupLiveStream() {
  liveStream.addEventListener("load", () => {
    framePlaceholder.style.display = "none";
  });

  liveStream.addEventListener("error", () => {
    framePlaceholder.style.display = "flex";
    framePlaceholder.querySelector("span").textContent = "Camera unavailable";
    setTimeout(() => {
      liveStream.src = `/stream.mjpg?t=${Date.now()}`;
    }, 2000);
  });
}

async function bootstrap() {
  setupLiveStream();

  try {
    const response = await fetch("/api/state");
    if (response.ok) {
      applyState(await response.json());
    }
  } catch (error) {
    console.warn("Unable to fetch initial dashboard state", error);
  }

  resetBtn.addEventListener("click", resetMonitoring);
  connectWebSocket();
}

bootstrap();
