window.AIShieldState = {
  latestResult: null,
  latestReport: null,
};

window.AIShieldAudioRecorder = {
  blob: null,
  fileName: "",
  previewUrl: "",
  mediaStream: null,
  audioContext: null,
  sourceNode: null,
  processorNode: null,
  silenceNode: null,
  buffers: [],
  totalLength: 0,
  isRecording: false,
};

const componentTargets = Array.from(document.querySelectorAll("[data-component]"));

const loadComponent = async (element) => {
  const componentPath = element.dataset.component;
  const response = await fetch(componentPath);
  if (!response.ok) {
    throw new Error(`Failed to load component: ${componentPath}`);
  }
  element.innerHTML = await response.text();
};

const loadComponents = async () => {
  await Promise.all(componentTargets.map(loadComponent));
  window.dispatchEvent(new CustomEvent("aishield:components-ready"));
};

const percentage = (value) => `${Math.round(Number(value) * 100)}%`;
const hasDisplayValue = (value) => value !== undefined && value !== null && value !== "";
const percentageOrLabel = (value, fallback = "N/A") => (hasDisplayValue(value) ? percentage(value) : fallback);
const textOrLabel = (value, fallback = "N/A") => (hasDisplayValue(value) ? String(value) : fallback);

const metadataMarkup = (metadata) => {
  const keys = Object.keys(metadata || {}).slice(0, 4);
  if (!keys.length) {
    return "";
  }

  return `
    <div class="meta-list">
      ${keys
        .map((key) => `<span class="status-pill neutral">${key.replaceAll("_", " ")}: ${metadata[key]}</span>`)
        .join("")}
    </div>
  `;
};

const titleize = (value) =>
  String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());

const compactMetric = (label, value) => `
  <div class="metric-tile">
    <span>${label}</span>
    <strong>${value}</strong>
  </div>
`;

const breakdownListMarkup = (items) => {
  if (!Array.isArray(items) || !items.length) {
    return "<p>No additional details available.</p>";
  }

  return `<ul class="explanation-list">${items.map((item) => `<li>${item}</li>`).join("")}</ul>`;
};

const headlinesMarkup = (headlines) => {
  if (!Array.isArray(headlines) || !headlines.length) {
    return "<p>No recent supporting headlines were available.</p>";
  }

  return `
    <div class="news-headline-list">
      ${headlines
        .map(
          (item) => `
            <article class="news-mini-card">
              <strong>${item.title || "Recent coverage"}</strong>
              <small>${item.source || "Source unavailable"}</small>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
};

const renderResultCard = (host, payload, report) => {
  if (!host || !payload) {
    return;
  }

  const badgeClass = payload.status === "Fake" ? "fake" : "real";
  const reportLinks = window.AIShieldReports?.linksMarkup(report) || "";

  host.innerHTML = `
    <article class="result-card">
      <div class="result-topline">
        <span class="status-pill ${badgeClass}">${payload.prediction || payload.status}</span>
        <span class="status-pill neutral">${titleize(payload.analysis_type)}</span>
      </div>
      <div class="metric-grid">
        <div class="metric-tile">
          <span>Fake Probability</span>
          <strong>${percentage(payload.fake_probability)}</strong>
        </div>
        <div class="metric-tile">
          <span>Real Probability</span>
          <strong>${percentage(payload.real_probability)}</strong>
        </div>
        <div class="metric-tile">
          <span>Confidence</span>
          <strong>${percentage(payload.confidence)}</strong>
        </div>
      </div>
      ${reportLinks}
    </article>
  `;
};

const suspiciousSegmentsMarkup = (segments) => {
  if (!Array.isArray(segments) || !segments.length) {
    return "<p>No high-risk sampled segments were highlighted in this run.</p>";
  }

  return `
    <div class="news-headline-list">
      ${segments
        .map(
          (segment) => `
            <article class="news-mini-card">
              <strong>${segment.frame_label || (segment.estimated_second != null ? `Around ${segment.estimated_second}s` : `Sample ${segment.window_index}`)}</strong>
              <small>Risk ${percentage(segment.anomaly_score || 0)}</small>
              <p>${segment.reason || "Suspicious temporal inconsistency detected."}</p>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
};

const suspiciousRegionsMarkup = (regions) => {
  if (!Array.isArray(regions) || !regions.length) {
    return "<p>No high-risk voice regions were highlighted in this run.</p>";
  }

  return `
    <div class="news-headline-list">
      ${regions
        .map(
          (region) => `
            <article class="news-mini-card">
              <strong>${region.segment_label || (region.estimated_second != null ? `Around ${region.estimated_second}s` : "Voice region")}</strong>
              <small>Risk ${percentage(region.anomaly_score || 0)}</small>
              <p>${region.reason || "Suspicious voice pattern detected."}</p>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
};

const breathingSegmentsMarkup = (segments) => {
  if (!Array.isArray(segments) || !segments.length) {
    return "<p>No breathing-sized gaps were confidently highlighted in this run.</p>";
  }

  return `
    <div class="breathing-segment-list">
      ${segments
        .map(
          (segment) => `
            <article class="news-mini-card">
              <strong>${segment.start_second}s - ${segment.end_second}s</strong>
              <small>Pause ${segment.duration_seconds}s</small>
              <p>${segment.reason || "Breathing-style gap detected."}</p>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
};

const renderNewsIntelligenceCard = renderResultCard;
const renderVideoIntelligenceCard = renderResultCard;
const renderAudioIntelligenceCard = renderResultCard;

const showFormError = (host, message) => {
  if (!host) {
    return;
  }
  host.innerHTML = `
    <article class="result-card">
      <span class="status-pill fake">Error</span>
      <h3>Request failed</h3>
      <p>${message}</p>
    </article>
  `;
};

const showProcessingCard = (host, title, message) => {
  if (!host) {
    return;
  }

  host.innerHTML = `
    <article class="result-card">
      <span class="status-pill neutral">Processing</span>
      <h3>${title}</h3>
      <p>${message}</p>
    </article>
  `;
};

const finalizeAnalysis = (resultHost, payload, renderer) => {
  window.AIShieldState.latestResult = payload.result;
  window.AIShieldState.latestReport = payload.report;
  renderer(resultHost, payload.result, payload.report);
  window.AIShieldReports?.loadRecentReports();
  window.dispatchEvent(
    new CustomEvent("aishield:analysis-complete", {
      detail: { result: payload.result, report: payload.report },
    }),
  );
};

const getAudioRecorderElements = () => ({
  startButton: document.getElementById("audioRecordStart"),
  stopButton: document.getElementById("audioRecordStop"),
  clearButton: document.getElementById("audioRecordClear"),
  status: document.getElementById("audioRecorderStatus"),
  preview: document.getElementById("audioRecorderPreview"),
  input: document.querySelector("#audioForm input[name='audio']"),
});

const setAudioRecorderStatus = (message) => {
  const { status } = getAudioRecorderElements();
  if (status) {
    status.textContent = message;
  }
};

const updateAudioPreview = (blob, fileName) => {
  const { preview, clearButton } = getAudioRecorderElements();
  const recorder = window.AIShieldAudioRecorder;

  if (recorder.previewUrl) {
    URL.revokeObjectURL(recorder.previewUrl);
    recorder.previewUrl = "";
  }

  if (!preview || !blob) {
    return;
  }

  recorder.previewUrl = URL.createObjectURL(blob);
  preview.src = recorder.previewUrl;
  preview.hidden = false;
  preview.dataset.fileName = fileName || "";
  if (clearButton) {
    clearButton.disabled = false;
  }
};

const clearRecordedAudio = () => {
  const { preview, clearButton } = getAudioRecorderElements();
  const recorder = window.AIShieldAudioRecorder;
  recorder.blob = null;
  recorder.fileName = "";
  recorder.buffers = [];
  recorder.totalLength = 0;

  if (recorder.previewUrl) {
    URL.revokeObjectURL(recorder.previewUrl);
    recorder.previewUrl = "";
  }

  if (preview) {
    preview.pause();
    preview.removeAttribute("src");
    preview.load();
    preview.hidden = true;
  }
  if (clearButton) {
    clearButton.disabled = true;
  }
};

const mergeFloatBuffers = (buffers, totalLength) => {
  const merged = new Float32Array(totalLength);
  let offset = 0;
  buffers.forEach((buffer) => {
    merged.set(buffer, offset);
    offset += buffer.length;
  });
  return merged;
};

const encodeWavBlob = (samples, sampleRate) => {
  const bytesPerSample = 2;
  const blockAlign = bytesPerSample;
  const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample);
  const view = new DataView(buffer);

  const writeString = (offset, value) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * bytesPerSample, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, samples.length * bytesPerSample, true);

  let offset = 44;
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    offset += 2;
  }

  return new Blob([buffer], { type: "audio/wav" });
};

const stopAudioCapture = async () => {
  const recorder = window.AIShieldAudioRecorder;

  if (recorder.processorNode) {
    recorder.processorNode.disconnect();
    recorder.processorNode.onaudioprocess = null;
  }
  if (recorder.sourceNode) {
    recorder.sourceNode.disconnect();
  }
  if (recorder.silenceNode) {
    recorder.silenceNode.disconnect();
  }
  if (recorder.mediaStream) {
    recorder.mediaStream.getTracks().forEach((track) => track.stop());
  }
  if (recorder.audioContext && recorder.audioContext.state !== "closed") {
    await recorder.audioContext.close();
  }

  recorder.mediaStream = null;
  recorder.audioContext = null;
  recorder.sourceNode = null;
  recorder.processorNode = null;
  recorder.silenceNode = null;
  recorder.isRecording = false;
};

const bindAudioRecorder = () => {
  const { startButton, stopButton, clearButton, input } = getAudioRecorderElements();
  if (!startButton || !stopButton || !clearButton) {
    return;
  }

  if (input) {
    input.addEventListener("change", () => {
      if (input.files?.length) {
        clearRecordedAudio();
        setAudioRecorderStatus(`Using uploaded file: ${input.files[0].name}`);
      }
    });
  }

  startButton.addEventListener("click", async () => {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!navigator.mediaDevices?.getUserMedia || !AudioContextClass) {
      setAudioRecorderStatus("Microphone recording is not supported in this browser.");
      return;
    }

    try {
      clearRecordedAudio();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const audioContext = new AudioContextClass();
      const sourceNode = audioContext.createMediaStreamSource(stream);
      const processorNode = audioContext.createScriptProcessor(4096, 1, 1);
      const silenceNode = audioContext.createGain();
      silenceNode.gain.value = 0;

      const recorder = window.AIShieldAudioRecorder;
      recorder.mediaStream = stream;
      recorder.audioContext = audioContext;
      recorder.sourceNode = sourceNode;
      recorder.processorNode = processorNode;
      recorder.silenceNode = silenceNode;
      recorder.buffers = [];
      recorder.totalLength = 0;
      recorder.isRecording = true;

      processorNode.onaudioprocess = (event) => {
        if (!window.AIShieldAudioRecorder.isRecording) {
          return;
        }
        const channelData = event.inputBuffer.getChannelData(0);
        const cloned = new Float32Array(channelData.length);
        cloned.set(channelData);
        window.AIShieldAudioRecorder.buffers.push(cloned);
        window.AIShieldAudioRecorder.totalLength += cloned.length;
      };

      sourceNode.connect(processorNode);
      processorNode.connect(silenceNode);
      silenceNode.connect(audioContext.destination);

      startButton.disabled = true;
      stopButton.disabled = false;
      clearButton.disabled = true;
      setAudioRecorderStatus("Recording... speak naturally for 2 to 10 seconds, then press Stop.");
    } catch (error) {
      setAudioRecorderStatus(error.message || "Unable to access the microphone.");
    }
  });

  stopButton.addEventListener("click", async () => {
    const recorder = window.AIShieldAudioRecorder;
    if (!recorder.isRecording || !recorder.audioContext) {
      return;
    }

    const sampleRate = recorder.audioContext.sampleRate || 44100;
    const samples = mergeFloatBuffers(recorder.buffers, recorder.totalLength);
    await stopAudioCapture();

    startButton.disabled = false;
    stopButton.disabled = true;

    if (!samples.length) {
      setAudioRecorderStatus("No microphone audio was captured. Try again.");
      return;
    }

    const wavBlob = encodeWavBlob(samples, sampleRate);
    recorder.blob = wavBlob;
    recorder.fileName = `ai_shield_recording_${Date.now()}.wav`;
    updateAudioPreview(wavBlob, recorder.fileName);
    setAudioRecorderStatus("Recording ready. You can analyze this clip now or upload another file.");
  });

  clearButton.addEventListener("click", async () => {
    if (window.AIShieldAudioRecorder.isRecording) {
      await stopAudioCapture();
      if (startButton) {
        startButton.disabled = false;
      }
      if (stopButton) {
        stopButton.disabled = true;
      }
    }
    clearRecordedAudio();
    setAudioRecorderStatus("Record a short 2 to 10 second clip or upload an audio file for analysis.");
  });
};

const bindUploadForm = (formId, resultId, endpoint) => {
  const form = document.getElementById(formId);
  const resultHost = document.getElementById(resultId);
  if (!form || !resultHost) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    resultHost.innerHTML = `
      <article class="result-card">
        <span class="status-pill neutral">Processing</span>
        <h3>Analyzing content...</h3>
        <p>The backend is generating scores and reports.</p>
      </article>
    `;

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        body: new FormData(form),
      });
      const payload = await response.json();

      if (!response.ok) {
        throw new Error(payload.error || "Analysis failed.");
      }

      finalizeAnalysis(resultHost, payload, renderResultCard);
    } catch (error) {
      showFormError(resultHost, error.message);
    }
  });
};

const bindVideoUploadForm = () => {
  const form = document.getElementById("videoForm");
  const resultHost = document.getElementById("videoResult");
  if (!form || !resultHost) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    showProcessingCard(resultHost, "Scanning video stream...", "Sampling clip structure, temporal consistency, and generation markers.");

    try {
      const response = await fetch("/api/video/analyze", {
        method: "POST",
        body: new FormData(form),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Video analysis failed.");
      }

      finalizeAnalysis(resultHost, payload, renderVideoIntelligenceCard);
    } catch (error) {
      showFormError(resultHost, error.message);
    }
  });
};

const bindVideoUrlForm = () => {
  const form = document.getElementById("videoUrlForm");
  const resultHost = document.getElementById("videoResult");
  if (!form || !resultHost) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const url = String(formData.get("url") || "").trim();

    if (!url) {
      showFormError(resultHost, "Enter a video URL to scan.");
      return;
    }

    showProcessingCard(resultHost, "Inspecting video URL...", "Resolving the clip, checking source credibility, and sampling the video for deepfake signals.");

    try {
      const response = await fetch("/api/video/analyze-url", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ url }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Video URL analysis failed.");
      }

      finalizeAnalysis(resultHost, payload, renderVideoIntelligenceCard);
    } catch (error) {
      showFormError(resultHost, error.message);
    }
  });
};

const bindAudioUploadForm = () => {
  const form = document.getElementById("audioForm");
  const resultHost = document.getElementById("audioResult");
  const input = form?.querySelector("input[name='audio']");
  if (!form || !resultHost || !input) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const formData = new FormData();
    const uploadedFile = input.files?.[0];
    const recordedBlob = window.AIShieldAudioRecorder.blob;
    const recordedName = window.AIShieldAudioRecorder.fileName || "ai_shield_recording.wav";

    if (uploadedFile) {
      formData.append("audio", uploadedFile, uploadedFile.name);
    } else if (recordedBlob) {
      formData.append("audio", recordedBlob, recordedName);
    } else {
      showFormError(resultHost, "Upload an audio file or record a voice sample first.");
      return;
    }

    showProcessingCard(
      resultHost,
      "Scanning voice authenticity...",
      "Extracting pause, pitch, waveform, and spectrogram-style voice signals for AI voice detection.",
    );

    try {
      const response = await fetch("/api/voice/analyze", {
        method: "POST",
        body: formData,
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Audio analysis failed.");
      }

      finalizeAnalysis(resultHost, payload, renderAudioIntelligenceCard);
    } catch (error) {
      showFormError(resultHost, error.message);
    }
  });
};

const bindAudioUrlForm = () => {
  const form = document.getElementById("audioUrlForm");
  const resultHost = document.getElementById("audioResult");
  if (!form || !resultHost) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const url = String(form.elements.url.value || "").trim();
    if (!url) {
      showFormError(resultHost, "Paste a voice URL to analyze.");
      return;
    }

    showProcessingCard(
      resultHost,
      "Resolving voice URL...",
      "Fetching the audio source, extracting voice signals, and generating explainable authenticity results.",
    );

    try {
      const response = await fetch("/api/voice/analyze-url", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ url }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Voice URL analysis failed.");
      }

      finalizeAnalysis(resultHost, payload, renderAudioIntelligenceCard);
    } catch (error) {
      showFormError(resultHost, error.message);
    }
  });
};

const bindTextForm = () => {
  const form = document.getElementById("textForm");
  const resultHost = document.getElementById("textResult");
  if (!form || !resultHost) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    resultHost.innerHTML = `
      <article class="result-card">
        <span class="status-pill neutral">Processing</span>
        <h3>Analyzing text...</h3>
        <p>The backend is scoring misinformation indicators.</p>
      </article>
    `;

    try {
      const payload = { text: form.elements.text.value.trim() };
      const response = await fetch("/api/news/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Text analysis failed.");
      }

      window.AIShieldState.latestResult = data.result;
      window.AIShieldState.latestReport = data.report;
      renderResultCard(resultHost, data.result, data.report);
      window.AIShieldReports?.loadRecentReports();
      window.dispatchEvent(
        new CustomEvent("aishield:analysis-complete", {
          detail: { result: data.result, report: data.report },
        }),
      );
    } catch (error) {
      showFormError(resultHost, error.message);
    }
  });
};

const bindNewsTextForm = () => {
  const form = document.getElementById("newsTextForm");
  const resultHost = document.getElementById("newsResult");
  if (!form || !resultHost) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    showProcessingCard(
      resultHost,
      "Analyzing news text...",
      "AI Shield is combining NLP scoring, clickbait detection, and live verification signals.",
    );

    try {
      const payload = {
        headline: "",
        body: form.elements.body.value.trim(),
      };
      const response = await fetch("/api/news/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "News text analysis failed.");
      }

      window.AIShieldState.latestResult = data.result;
      window.AIShieldState.latestReport = data.report;
      renderNewsIntelligenceCard(resultHost, data.result, data.report);
      window.AIShieldReports?.loadRecentReports();
      window.dispatchEvent(
        new CustomEvent("aishield:analysis-complete", {
          detail: { result: data.result, report: data.report },
        }),
      );
    } catch (error) {
      showFormError(resultHost, error.message);
    }
  });
};

const bindNewsUrlForm = () => {
  const form = document.getElementById("newsUrlForm");
  const resultHost = document.getElementById("newsResult");
  if (!form || !resultHost) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    showProcessingCard(
      resultHost,
      "Scanning source URL...",
      "AI Shield is extracting article text, checking source credibility, and cross-verifying recent coverage.",
    );

    try {
      const response = await fetch("/api/news/analyze-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: form.elements.url.value.trim() }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "URL analysis failed.");
      }

      window.AIShieldState.latestResult = data.result;
      window.AIShieldState.latestReport = data.report;
      renderNewsIntelligenceCard(resultHost, data.result, data.report);
      window.AIShieldReports?.loadRecentReports();
      window.dispatchEvent(
        new CustomEvent("aishield:analysis-complete", {
          detail: { result: data.result, report: data.report },
        }),
      );
    } catch (error) {
      showFormError(resultHost, error.message);
    }
  });
};

const bindNewsImageForm = () => {
  const form = document.getElementById("newsImageForm");
  const resultHost = document.getElementById("newsImageResult");
  if (!form || !resultHost) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    showProcessingCard(
      resultHost,
      "Reviewing image evidence...",
      "AI Shield is checking image metadata, caption language, and fake-news signals attached to the upload.",
    );

    try {
      const response = await fetch("/api/news/analyze-image", {
        method: "POST",
        body: new FormData(form),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Image verification failed.");
      }

      window.AIShieldState.latestResult = data.result;
      window.AIShieldState.latestReport = data.report;
      renderNewsIntelligenceCard(resultHost, data.result, data.report);
      window.AIShieldReports?.loadRecentReports();
      window.dispatchEvent(
        new CustomEvent("aishield:analysis-complete", {
          detail: { result: data.result, report: data.report },
        }),
      );
    } catch (error) {
      showFormError(resultHost, error.message);
    }
  });
};

const renderDashboardSummary = async () => {
  const summaryGrid = document.getElementById("summaryGrid");
  const recentAnalyses = document.getElementById("recentAnalyses");
  if (!summaryGrid || !recentAnalyses) {
    return;
  }

  try {
    const response = await fetch("/api/dashboard/summary");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Unable to load dashboard summary.");
    }

    const { stats, recent } = payload;
    summaryGrid.innerHTML = `
      <article class="stat-card">
        <span class="stat-label">Total Analyses</span>
        <strong>${stats.total_analyses}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">Flagged Fake</span>
        <strong>${stats.fake_count}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">Flagged Real</span>
        <strong>${stats.real_count}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">Reports Generated</span>
        <strong>${stats.report_count || 0}</strong>
      </article>
    `;

    recentAnalyses.innerHTML = recent.length
      ? recent
          .map(
            (item) => `
              <article class="list-item">
                <div class="list-item-header">
                  <strong>${item.input_name}</strong>
                  <span class="status-pill ${item.status === "Fake" ? "fake" : "real"}">${item.status}</span>
                </div>
                <p>${item.summary}</p>
                <small>${item.analysis_type} · confidence ${percentage(item.confidence)}</small>
              </article>
            `,
          )
          .join("")
      : `<article class="list-item"><strong>No analyses yet</strong><p>Run a video, audio, or text check to populate dashboard activity.</p></article>`;
  } catch (error) {
    summaryGrid.innerHTML = `<article class="stat-card"><strong>Dashboard unavailable</strong><p>${error.message}</p></article>`;
    recentAnalyses.innerHTML = "";
  }
};

document.addEventListener("DOMContentLoaded", async () => {
  try {
    await loadComponents();
  } catch (error) {
    console.error(error);
  }

  bindVideoUploadForm();
  bindVideoUrlForm();
  bindAudioRecorder();
  bindAudioUploadForm();
  bindAudioUrlForm();
  bindTextForm();
  bindNewsTextForm();
  bindNewsUrlForm();
  renderDashboardSummary();
  window.AIShieldReports?.loadRecentReports();
});
