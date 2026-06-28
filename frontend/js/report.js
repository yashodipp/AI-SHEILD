window.AIShieldReports = (() => {
  const formatReportTimestamp = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "Recently generated";
    }

    return date.toLocaleString([], {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const linksMarkup = (report) => {
    if (!report) {
      return "";
    }

    return `
      <div class="result-actions">
        <a class="button secondary" href="${report.pdf_url}" target="_blank" rel="noreferrer">Download PDF</a>
        <a class="button ghost" href="${report.csv_url}" target="_blank" rel="noreferrer">Download CSV</a>
      </div>
    `;
  };

  const recentReportsMarkup = (items) => {
    if (!items.length) {
      return `<article class="list-item"><strong>No reports yet</strong><p>Generated reports will appear here after the first analysis.</p></article>`;
    }

    return items
      .map(
        (item) => `
          <article class="list-item">
            <div class="list-item-header">
              <strong>${item.report_name}</strong>
              <span class="status-pill neutral">${item.analysis_type}</span>
            </div>
            <p>Analysis ID: ${item.analysis_id}</p>
            <small>${formatReportTimestamp(item.created_at)}</small>
            <div class="result-actions">
              <a class="button secondary" href="${item.pdf_url}" target="_blank" rel="noreferrer">PDF</a>
              <a class="button ghost" href="${item.csv_url}" target="_blank" rel="noreferrer">CSV</a>
            </div>
          </article>
        `,
      )
      .join("");
  };

  const loadRecentReports = async () => {
    const host = document.getElementById("recentReports");
    if (!host) {
      return;
    }

    try {
      const response = await fetch("/api/reports/recent?limit=12");
      const payload = await response.json();
      host.innerHTML = recentReportsMarkup(payload.items || []);
    } catch (error) {
      host.innerHTML = `<article class="list-item"><strong>Unable to load reports</strong><p>${error.message}</p></article>`;
    }
  };

  return {
    linksMarkup,
    loadRecentReports,
  };
})();
