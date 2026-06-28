const historyPercentage = (value) => `${Math.round(Number(value) * 100)}%`;

const historyTimestamp = (value) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Recent";
  }

  return date.toLocaleString([], {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const renderHistoryPage = async () => {
  const summaryGrid = document.getElementById("historySummaryGrid");
  const historyList = document.getElementById("historyList");
  if (!summaryGrid || !historyList) {
    return;
  }

  try {
    const response = await fetch("/api/dashboard/summary?limit=24");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Unable to load history.");
    }

    const { recent, stats } = payload;

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
        <span class="stat-label">Report Downloads</span>
        <strong>${stats.report_count || 0}</strong>
      </article>
    `;

    historyList.innerHTML = recent.length
      ? recent
          .map(
            (item) => `
              <article class="list-item">
                <div class="list-item-header">
                  <strong>${item.input_name}</strong>
                  <span class="status-pill ${item.status === "Fake" ? "fake" : "real"}">${item.status}</span>
                </div>
                <p>${item.summary}</p>
                <small>${item.analysis_type} · confidence ${historyPercentage(item.confidence)} · ${historyTimestamp(item.created_at)}</small>
              </article>
            `,
          )
          .join("")
      : `<article class="list-item"><strong>No history yet</strong><p>Run a video, audio, or text analysis and it will appear here.</p></article>`;
  } catch (error) {
    summaryGrid.innerHTML = `<article class="stat-card"><strong>History unavailable</strong><p>${error.message}</p></article>`;
    historyList.innerHTML = "";
  }
};

document.addEventListener("DOMContentLoaded", () => {
  renderHistoryPage();
  window.AIShieldReports?.loadRecentReports();
});
