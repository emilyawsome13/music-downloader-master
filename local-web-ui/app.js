const clientIdKey = "spotdl_dashboard_client_id";
const deviceDeliveryKey = "spotdl_dashboard_deliver_to_device";
const savedClientId = localStorage.getItem(clientIdKey);
const clientId = savedClientId || crypto.randomUUID();
localStorage.setItem(clientIdKey, clientId);

const state = {
    snapshot: null,
    socket: null,
    socketHeartbeat: null,
    optionsModel: null,
    autoDeviceDeliveryArmed: false,
    deliveredBundlePath: null,
};

const DEFAULT_OUTPUT_TEMPLATE = "{album-artist}/{album}/{title}.{output-ext}";
const LEGACY_OUTPUT_TEMPLATE = "{artists} - {title}.{output-ext}";
const AUDIO_PROVIDER_FALLBACKS = {
    "youtube-music": ["youtube-music", "youtube"],
    youtube: ["youtube", "youtube-music"],
    soundcloud: ["soundcloud", "youtube-music", "youtube"],
    bandcamp: ["bandcamp", "youtube-music", "youtube"],
    piped: ["piped", "youtube", "youtube-music"],
};

const elements = {
    clientIdLabel: document.getElementById("clientIdLabel"),
    connectionState: document.getElementById("connectionState"),
    jobState: document.getElementById("jobState"),
    serverAddress: document.getElementById("serverAddress"),
    queryInput: document.getElementById("queryInput"),
    formatSelect: document.getElementById("formatSelect"),
    bitrateSelect: document.getElementById("bitrateSelect"),
    audioProviderSelect: document.getElementById("audioProviderSelect"),
    overwriteSelect: document.getElementById("overwriteSelect"),
    outputInput: document.getElementById("outputInput"),
    deliverToDeviceCheckbox: document.getElementById("deliverToDeviceCheckbox"),
    downloadButton: document.getElementById("downloadButton"),
    refreshStateButton: document.getElementById("refreshStateButton"),
    statTotal: document.getElementById("statTotal"),
    statActive: document.getElementById("statActive"),
    statCompleted: document.getElementById("statCompleted"),
    statFailed: document.getElementById("statFailed"),
    statProgress: document.getElementById("statProgress"),
    statResolved: document.getElementById("statResolved"),
    globalProgressBar: document.getElementById("globalProgressBar"),
    queueList: document.getElementById("queueList"),
    downloadsList: document.getElementById("downloadsList"),
    bundlePanel: document.getElementById("bundlePanel"),
    downloadBundleLink: document.getElementById("downloadBundleLink"),
    bundleHint: document.getElementById("bundleHint"),
    eventsList: document.getElementById("eventsList"),
    debugOutput: document.getElementById("debugOutput"),
    actionHint: document.getElementById("actionHint"),
};

function setConnectionState(status, online) {
    elements.connectionState.textContent = status;
    elements.connectionState.classList.toggle("online", online);
    elements.connectionState.classList.toggle("offline", !online);
}

function request(path, options = {}) {
    return fetch(path, {
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {}),
        },
        ...options,
    }).then(async (response) => {
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            throw new Error(payload.detail || `Request failed: ${response.status}`);
        }
        return response.json();
    });
}

function fillSelect(select, choices, currentValue) {
    select.innerHTML = "";
    for (const choice of choices) {
        const option = document.createElement("option");
        option.value = choice;
        option.textContent = choice;
        option.selected = choice === currentValue;
        select.appendChild(option);
    }
}

function normalizeOutputTemplate(value) {
    const trimmedValue = (value || "").trim();

    if (!trimmedValue || trimmedValue === LEGACY_OUTPUT_TEMPLATE) {
        return DEFAULT_OUTPUT_TEMPLATE;
    }

    return trimmedValue;
}

function buildAudioProviderChain(primaryProvider) {
    const normalizedPrimary = (primaryProvider || "").trim();
    const providerChain = AUDIO_PROVIDER_FALLBACKS[normalizedPrimary] || [normalizedPrimary];

    return providerChain.filter((provider, index) => provider && providerChain.indexOf(provider) === index);
}

function shouldDeliverToDevice() {
    return elements.deliverToDeviceCheckbox.checked;
}

function persistDeviceDeliveryPreference() {
    localStorage.setItem(deviceDeliveryKey, shouldDeliverToDevice() ? "true" : "false");
}

function isFinishedJob(status) {
    return status === "complete" || status === "complete-with-errors";
}

function triggerBundleDownload(bundle) {
    const bundleHref = `/api/download/bundle?client_id=${encodeURIComponent(clientId)}`;
    const link = document.createElement("a");
    link.href = bundleHref;
    link.download = bundle.name || "spotdl-downloads.zip";
    link.rel = "noopener";
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    link.remove();
}

function maybeDeliverBundleToDevice(snapshot) {
    if (!state.autoDeviceDeliveryArmed || !shouldDeliverToDevice()) {
        return;
    }

    if (!snapshot || !isFinishedJob(snapshot.job?.status)) {
        return;
    }

    const bundle = snapshot.bundle;
    if (!bundle || !bundle.path) {
        return;
    }

    if (state.deliveredBundlePath === bundle.path) {
        return;
    }

    triggerBundleDownload(bundle);
    state.deliveredBundlePath = bundle.path;
    state.autoDeviceDeliveryArmed = false;
    elements.actionHint.textContent = "The finished ZIP is being sent to this device now.";
}

async function loadSettings() {
    const [settings, options] = await Promise.all([
        request(`/api/settings?client_id=${encodeURIComponent(clientId)}`),
        request("/api/options_model"),
    ]);

    state.optionsModel = options;

    const selectedFormat = settings.format || options.format.default || options.format.choices?.[0] || "mp3";
    const selectedBitrate = settings.bitrate || options.bitrate.default || options.bitrate.choices?.[0] || "192k";
    const selectedAudioProvider = settings.audio_providers?.[0]
        || options.audio_providers.default?.[0]
        || options.audio_providers.choices?.[0]
        || "youtube-music";
    const selectedOverwrite = settings.overwrite
        || options.overwrite.default
        || options.overwrite.choices?.[0]
        || "skip";
    const selectedOutput = normalizeOutputTemplate(
        settings.output || options.output.default || DEFAULT_OUTPUT_TEMPLATE,
    );

    fillSelect(elements.formatSelect, options.format.choices || [], selectedFormat);
    fillSelect(elements.bitrateSelect, options.bitrate.choices || [], selectedBitrate);
    fillSelect(
        elements.audioProviderSelect,
        options.audio_providers.choices || [],
        selectedAudioProvider,
    );
    fillSelect(elements.overwriteSelect, options.overwrite.choices || [], selectedOverwrite);
    elements.outputInput.value = selectedOutput;

    const savedDeviceDelivery = localStorage.getItem(deviceDeliveryKey);
    elements.deliverToDeviceCheckbox.checked = savedDeviceDelivery !== "false";
}

async function pushSettings() {
    const options = state.optionsModel || {};
    const selectedFormat = elements.formatSelect.value || options.format?.default || "mp3";
    const selectedBitrate = elements.bitrateSelect.value || options.bitrate?.default || "192k";
    const selectedAudioProvider = elements.audioProviderSelect.value
        || options.audio_providers?.default?.[0]
        || options.audio_providers?.choices?.[0]
        || "youtube-music";
    const selectedOverwrite = elements.overwriteSelect.value
        || options.overwrite?.default
        || options.overwrite?.choices?.[0]
        || "skip";
    const selectedOutput = normalizeOutputTemplate(
        elements.outputInput.value.trim() || options.output?.default || DEFAULT_OUTPUT_TEMPLATE,
    );

    return request(`/api/settings/update?client_id=${encodeURIComponent(clientId)}`, {
        method: "POST",
        body: JSON.stringify({
            format: selectedFormat,
            bitrate: selectedBitrate,
            audio_providers: buildAudioProviderChain(selectedAudioProvider),
            overwrite: selectedOverwrite,
            output: selectedOutput,
        }),
    });
}

function escapeHtml(value) {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
}

function renderQueue(songs) {
    if (!songs.length) {
        elements.queueList.className = "queue-list empty-state";
        elements.queueList.textContent = "No songs yet. Start a download to populate the queue.";
        return;
    }

    elements.queueList.className = "queue-list";
    elements.queueList.innerHTML = songs.map((song) => {
        const progress = Number(song.progress || 0);
        const songData = song.song || {};
        return `
            <article class="song-card">
                <div class="song-header">
                    <div>
                        <p class="song-title">${escapeHtml(song.display_name || "Unknown song")}</p>
                        <p class="song-meta">${escapeHtml(songData.album_name || "Unknown release")}</p>
                    </div>
                    <span class="status-chip ${escapeHtml(song.status || "queued")}">${escapeHtml(song.message || "Queued")}</span>
                </div>
                <div class="song-progress">
                    <div style="width:${progress}%"></div>
                </div>
                <div class="song-footer">
                    <span>${progress}%</span>
                    <span>${escapeHtml(song.updated_at || "-")}</span>
                </div>
            </article>
        `;
    }).join("");
}

function renderDownloads(downloads) {
    if (!downloads.length) {
        elements.downloadsList.className = "downloads-list empty-state";
        elements.downloadsList.textContent = "Finished files will appear here as each song completes.";
        return;
    }

    elements.downloadsList.className = "downloads-list";
    elements.downloadsList.innerHTML = downloads.map((download) => {
        const downloadHref = `/api/download/file?client_id=${encodeURIComponent(clientId)}&file=${encodeURIComponent(download.path)}`;
        return `
            <article class="download-card">
                <div class="download-header">
                    <div>
                        <p class="download-title">${escapeHtml(download.display_name)}</p>
                        <p class="download-path">${escapeHtml(download.path)}</p>
                    </div>
                </div>
                <a class="download-link" href="${downloadHref}" download>Save to this device</a>
            </article>
        `;
    }).join("");
}

function renderBundle(bundle, jobStatus = "idle") {
    if (!bundle || !bundle.path) {
        elements.bundlePanel.classList.add("is-hidden");
        elements.downloadBundleLink.setAttribute("href", "#");
        elements.downloadBundleLink.textContent = "Save Downloaded Songs";
        elements.bundleHint.textContent = "As songs finish, one ZIP with everything downloaded so far will appear here and can be saved to the phone or computer you are using.";
        return;
    }

    const bundleHref = `/api/download/bundle?client_id=${encodeURIComponent(clientId)}`;
    const isStillRunning = jobStatus === "running" || jobStatus === "starting";
    elements.bundlePanel.classList.remove("is-hidden");
    elements.downloadBundleLink.setAttribute("href", bundleHref);
    elements.downloadBundleLink.setAttribute("download", bundle.name || "spotdl-downloads.zip");
    elements.downloadBundleLink.textContent = isStillRunning ? "Save Downloaded So Far" : "Save All to This Device";
    elements.bundleHint.textContent = isStillRunning
        ? `${bundle.count || 0} finished file(s) are ready to save right now while the rest continue.`
        : `${bundle.count || 0} file(s) packed into ${bundle.name || "spotdl-downloads.zip"} for this device.`;
}

function renderEvents(events) {
    if (!events.length) {
        elements.eventsList.className = "events-list empty-state";
        elements.eventsList.textContent = "Waiting for diagnostics.";
        return;
    }

    elements.eventsList.className = "events-list";
    elements.eventsList.innerHTML = [...events].reverse().map((event) => {
        const details = event.details
            ? `<details><summary>Details</summary><pre class="debug-output">${escapeHtml(JSON.stringify(event.details, null, 2))}</pre></details>`
            : "";

        return `
            <article class="event-card ${escapeHtml(event.level || "info")}">
                <div class="event-header">
                    <div>
                        <p class="event-title">${escapeHtml(event.message)}</p>
                        <p class="event-meta">${escapeHtml(`${event.timestamp || ""} • ${event.kind || "event"} • ${event.level || "info"}`)}</p>
                    </div>
                </div>
                ${details}
            </article>
        `;
    }).join("");
}

function renderState(snapshot, websocketPayload = null) {
    state.snapshot = snapshot;

    const { job, stats, songs, downloads, bundle, events, latest_update: latestUpdate, server } = snapshot;
    elements.clientIdLabel.textContent = clientId;
    elements.jobState.textContent = job.status;
    elements.serverAddress.textContent = `${window.location.origin}`;
    elements.statTotal.textContent = stats.total;
    elements.statActive.textContent = stats.active;
    elements.statCompleted.textContent = stats.completed;
    elements.statFailed.textContent = stats.failed;
    elements.statProgress.textContent = `${stats.progress}%`;
    elements.statResolved.textContent = `${stats.resolved} resolved`;
    elements.globalProgressBar.style.width = `${stats.progress}%`;
    elements.actionHint.textContent = job.message || "Ready";

    renderQueue(songs || []);
    renderBundle(bundle || null, job?.status || "idle");
    renderDownloads(downloads || []);
    renderEvents(events || []);
    maybeDeliverBundleToDevice(snapshot);

    const debugPayload = websocketPayload || latestUpdate || snapshot;
    elements.debugOutput.textContent = JSON.stringify(debugPayload, null, 2);

    if (server && server.output_root) {
        elements.serverAddress.textContent = `${window.location.origin} • ${server.output_root}`;
    }
}

async function refreshState() {
    try {
        const snapshot = await request(`/api/session/state?client_id=${encodeURIComponent(clientId)}`);
        renderState(snapshot);
    } catch (error) {
        elements.debugOutput.textContent = error.stack || String(error);
    }
}

function connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${window.location.host}/api/ws?client_id=${encodeURIComponent(clientId)}`);

    socket.addEventListener("open", async () => {
        state.socket = socket;
        setConnectionState("Live", true);
        if (state.socketHeartbeat) {
            clearInterval(state.socketHeartbeat);
        }

        state.socketHeartbeat = setInterval(() => {
            if (socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: "ping", at: Date.now() }));
            }
        }, 15000);

        await Promise.all([loadSettings(), refreshState()]);
    });

    socket.addEventListener("message", (event) => {
        const payload = JSON.parse(event.data);
        if (payload.type === "state" && payload.state) {
            renderState(payload.state, payload);
        }
    });

    socket.addEventListener("close", () => {
        setConnectionState("Reconnecting", false);
        if (state.socketHeartbeat) {
            clearInterval(state.socketHeartbeat);
        }
        setTimeout(connectWebSocket, 1500);
    });

    socket.addEventListener("error", () => {
        setConnectionState("Socket Error", false);
    });
}

async function startDownload() {
    const query = elements.queryInput.value.trim();
    if (!query) {
        elements.actionHint.textContent = "Paste something to download first.";
        return;
    }

    try {
        elements.downloadButton.disabled = true;
        persistDeviceDeliveryPreference();
        state.autoDeviceDeliveryArmed = shouldDeliverToDevice();
        state.deliveredBundlePath = null;
        elements.actionHint.textContent = "Applying settings...";
        await pushSettings();

        elements.actionHint.textContent = "Starting background download...";
        const snapshot = await request(`/api/download/query?client_id=${encodeURIComponent(clientId)}`, {
            method: "POST",
            body: JSON.stringify({ query }),
        });

        renderState(snapshot);
    } catch (error) {
        elements.actionHint.textContent = error.message;
        elements.debugOutput.textContent = error.stack || String(error);
    } finally {
        elements.downloadButton.disabled = false;
    }
}

elements.downloadButton.addEventListener("click", startDownload);
elements.refreshStateButton.addEventListener("click", refreshState);
elements.deliverToDeviceCheckbox.addEventListener("change", persistDeviceDeliveryPreference);
elements.clientIdLabel.textContent = clientId;
connectWebSocket();
