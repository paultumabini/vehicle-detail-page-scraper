'use strict';

/*
  chart.js — Dashboard charts (home.html only).

  Two data sources:
    1. SSR  — #dashboard-setup-data from views._dashboard_stats (setup KPIs + status chart)
    2. AJAX — /spider-log-json/ for YTD template volume + 15-day activity (charts A/B/C)

  Chart.js 4.x — uses scales.x / scales.y (not legacy yAxes). Palette matches brand tokens.
 */

/* ── Brand-aligned palette (matches Tailwind brand + status badges) ── */
const VDP = {
  font: "'Inter', system-ui, -apple-system, sans-serif",
  grid: 'rgba(148, 163, 184, 0.18)',
  text: '#64748b',
  textDark: '#334155',
  brand: '#7c3aed',
  brandSoft: 'rgba(124, 58, 237, 0.12)',
  sky: '#0ea5e9',
  skySoft: 'rgba(14, 165, 233, 0.15)',
  emerald: '#10b981',
  emeraldSoft: 'rgba(16, 185, 129, 0.15)',
  amber: '#f59e0b',
  amberSoft: 'rgba(245, 158, 11, 0.18)',
  teal: '#14b8a6',
  tealSoft: 'rgba(20, 184, 166, 0.18)',
  rose: '#f43f5e',
  slate: '#94a3b8',
  series: [
    '#7c3aed',
    '#0ea5e9',
    '#10b981',
    '#f59e0b',
    '#f43f5e',
    '#8b5cf6',
    '#06b6d4',
    '#84cc16',
    '#ec4899',
  ],
  statusColors: {
    Active: '#10b981',
    Pending: '#f59e0b',
    Inactive: '#94a3b8',
    Failed: '#f43f5e',
    Paused: '#0ea5e9',
  },
};

Chart.defaults.font.family = VDP.font;
Chart.defaults.color = VDP.text;
Chart.defaults.plugins.legend.labels.usePointStyle = true;
Chart.defaults.plugins.legend.labels.boxWidth = 8;
Chart.defaults.plugins.legend.labels.padding = 16;
Chart.defaults.plugins.tooltip.backgroundColor = '#1e293b';
Chart.defaults.plugins.tooltip.titleFont = { weight: '600', size: 12 };
Chart.defaults.plugins.tooltip.bodyFont = { size: 12 };
Chart.defaults.plugins.tooltip.padding = 12;
Chart.defaults.plugins.tooltip.cornerRadius = 8;
Chart.defaults.plugins.tooltip.displayColors = true;

const baseScales = (xLabel = '', yLabel = '', { horizontal = false } = {}) => {
  // Chart.js 4 scale config — shared by bar/line charts on the dashboard.
  const category = {
    grid: { display: false },
    border: { display: false },
    ticks: {
      color: VDP.text,
      font: { size: 11, weight: '500' },
      maxRotation: horizontal ? 0 : 45,
      minRotation: 0,
    },
  };
  const value = {
    beginAtZero: true,
    grid: { color: VDP.grid, drawBorder: false },
    border: { display: false },
    ticks: {
      color: VDP.text,
      font: { size: 11 },
      precision: 0,
    },
    title: {
      display: Boolean(yLabel),
      text: yLabel,
      color: VDP.textDark,
      font: { size: 11, weight: '600' },
    },
  };

  return horizontal
    ? { x: value, y: { ...category, title: { display: Boolean(xLabel), text: xLabel, color: VDP.textDark, font: { size: 11, weight: '600' } } } }
    : { x: { ...category, title: { display: Boolean(xLabel), text: xLabel, color: VDP.textDark, font: { size: 11, weight: '600' } } }, y: value };
};

const removeSpinner = containerSelector => {
  document.querySelectorAll(`${containerSelector} .spinner-pulse`).forEach(el => el.remove());
};

const showChartError = containerSelector => {
  removeSpinner(containerSelector);
  const container = document.querySelector(containerSelector);
  if (!container) return;
  container.insertAdjacentHTML(
    'beforeend',
    '<p class="vdp-chart-error">Failed to load chart data</p>',
  );
};

const renderDatasets = (scrapes, barThickness = 10, radius = 6) => [
  {
    label: `Scrapes (total: ${scrapes.reduce((acc, val) => acc + val.totalScrapes, 0).toLocaleString()})`,
    data: scrapes.map(s => s.totalScrapes),
    type: 'bar',
    backgroundColor: scrapes.map((_, i) => VDP.series[i % VDP.series.length] + 'cc'),
    borderColor: scrapes.map((_, i) => VDP.series[i % VDP.series.length]),
    borderWidth: 0,
    barThickness,
    borderRadius: radius,
    borderSkipped: false,
  },
];

const elapsedTooltip = {
  callbacks: {
    label(context) {
      const minutes = context.raw;
      const totalSec = Math.round(minutes * 60);
      const h = String(Math.floor(totalSec / 3600)).padStart(2, '0');
      const m = String(Math.floor((totalSec % 3600) / 60)).padStart(2, '0');
      const s = String(totalSec % 60).padStart(2, '0');
      return `Elapsed: ${h}:${m}:${s}`;
    },
    afterBody(context) {
      const prevIdx = context[0].dataIndex - 1;
      if (prevIdx < 0) return ['—', 'Diff: n/a', '% Change: n/a'];
      const prev = context[0].dataset.data[prevIdx];
      const diff = context[0].raw - prev;
      const pct = prev ? ((diff / prev) * 100).toFixed(1) + '%' : 'n/a';
      return ['—', `Diff: ${diff >= 0 ? '+' : ''}${diff.toFixed(1)} min`, `% Change: ${pct}`];
    },
  },
};

const scrapeVolumeTooltip = {
  callbacks: {
    afterBody(context) {
      const prevIdx = context[0].dataIndex - 1;
      if (prevIdx < 0) return ['—', 'Diff: n/a', '% Change: n/a'];
      const prev = context[0].dataset.data[prevIdx];
      const diff = context[0].raw - prev;
      const pct = prev ? ((diff / prev) * 100).toFixed(1) + '%' : 'n/a';
      return ['—', `Diff: ${diff >= 0 ? '+' : ''}${diff.toLocaleString()}`, `% Change: ${pct}`];
    },
  },
};

/* ── Setup coverage (SSR data from home.html json_script) ─────── */

/*
  Account setup charts (dashboard):
    chartSetupCoverage   — donut: VDP covered vs need setup (display-only)
    chartSetupComparison — bars: active | configured | direct feed | need setup (clickable)
  Counts from views._dashboard_stats(); bar links use setup.accounts_links.
*/

const readSetupData = () => {
  // Populated by {{ dashboard|json_script:"dashboard-setup-data" }} in home.html.
  const el = document.getElementById('dashboard-setup-data');
  if (!el) return null;
  try {
    return JSON.parse(el.textContent);
  } catch {
    return null;
  }
};

const SETUP_BAR_LINK_KEYS = ['active', 'configured', 'direct_feed', 'need_setup'];

const setupChartNavigation = (setup, linkKeys) => ({
  onHover(event, elements) {
    const target = event.native?.target;
    if (target) {
      target.style.cursor = elements.length ? 'pointer' : 'default';
    }
  },
  onClick(_event, elements) {
    if (!elements.length) return;
    const url = setup.accounts_links?.[linkKeys[elements[0].index]];
    if (url) {
      window.location.href = url;
    }
  },
});

const chartSetupCoverage = setup => {
  // Donut: VDP covered (scrape configured + direct feed) vs need setup among ACTIVE accounts.
  const canvas = document.getElementById('chartSetup__canvas');
  if (!canvas) return;

  const covered = setup.covered_count || 0;
  const needSetup = setup.need_setup_count || 0;
  const total = setup.active_account_count || covered + needSetup;
  const coveredPct = total ? Math.round((covered / total) * 100) : 0;

  new Chart(canvas, {
    type: 'doughnut',
    data: {
      labels: ['VDP covered', 'Need setup'],
      datasets: [
        {
          data: [covered, needSetup],
          backgroundColor: [VDP.emerald, VDP.amber],
          borderColor: '#fff',
          borderWidth: 3,
          hoverOffset: 6,
        },
      ],
    },
    options: {
      cutout: '68%',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            label(ctx) {
              const pct = total ? ((ctx.raw / total) * 100).toFixed(1) : 0;
              return `${ctx.label}: ${ctx.raw.toLocaleString()} (${pct}%)`;
            },
          },
        },
      },
    },
    plugins: [
      {
        // Donut hole — active total + % VDP covered (display only; no segment links).
        id: 'centerText',
        beforeDraw(chart) {
          const { ctx, chartArea } = chart;
          if (!chartArea) return;
          const cx = (chartArea.left + chartArea.right) / 2;
          const cy = (chartArea.top + chartArea.bottom) / 2;
          ctx.save();
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillStyle = VDP.textDark;
          ctx.font = '600 1.65rem Inter, system-ui, sans-serif';
          ctx.fillText(total.toLocaleString(), cx, cy - 10);
          ctx.font = '500 0.7rem Inter, system-ui, sans-serif';
          ctx.fillStyle = VDP.text;
          ctx.fillText('active accounts', cx, cy + 10);
          ctx.fillStyle = VDP.emerald;
          ctx.font = '600 0.8rem Inter, system-ui, sans-serif';
          ctx.fillText(`${coveredPct}% covered`, cx, cy + 28);
          ctx.restore();
        },
      },
    ],
  });
};

const chartSetupComparison = setup => {
  // Bar chart: Active | Configured | Direct feed | Need setup (mirrors KPI cards + legend links).
  const canvas = document.getElementById('chartCompare__canvas');
  if (!canvas) return;

  new Chart(canvas, {
    type: 'bar',
    data: {
      labels: ['Active accounts', 'Configured', 'Direct feed', 'Need setup'],
      datasets: [
        {
          label: 'Count',
          data: [
            setup.active_account_count || 0,
            setup.configured_count || 0,
            setup.direct_feed_count || 0,
            setup.need_setup_count || 0,
          ],
          backgroundColor: [VDP.skySoft, VDP.emeraldSoft, VDP.tealSoft, VDP.amberSoft],
          borderColor: [VDP.sky, VDP.emerald, VDP.teal, VDP.amber],
          borderWidth: 2,
          borderRadius: 8,
          barThickness: 40,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      ...setupChartNavigation(setup, SETUP_BAR_LINK_KEYS),
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(ctx) {
              return `${ctx.label}: ${ctx.raw.toLocaleString()}`;
            },
          },
        },
      },
      scales: baseScales('', 'Count'),
    },
  });
};

const chartSiteStatus = setup => {
  // Horizontal bar; colors align with .status-badge pills in main.css.
  const canvas = document.getElementById('chartStatus__canvas');
  if (!canvas) return;

  const statusOrder = ['Active', 'Pending', 'Paused', 'Inactive', 'Failed'];
  const statusMap = setup.site_status || {};
  const labels = statusOrder.filter(s => statusMap[s]);
  const values = labels.map(s => statusMap[s]);
  const colors = labels.map(s => VDP.statusColors[s] || VDP.slate);

  new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Target sites',
          data: values,
          backgroundColor: colors.map(c => c + '33'),
          borderColor: colors,
          borderWidth: 2,
          borderRadius: 6,
          barThickness: 28,
        },
      ],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: baseScales('Status', 'Sites', { horizontal: true }),
    },
  });
};

const renderSetupCharts = () => {
  const setup = readSetupData();
  if (!setup) return;
  chartSetupCoverage(setup);
  chartSetupComparison(setup);
  chartSiteStatus(setup);
};

/* ── Spider log charts (AJAX from /spider-log-json/) ───────────── */

const chartA = scrapeData => {
  // YTD items scraped grouped by spider template (unchanged data shape from legacy chart.js).
  const canvas = document.getElementById('chartA__canvas');
  if (!canvas) return;

  new Chart(canvas, {
    type: 'bar',
    data: {
      labels: scrapeData.map(
        s => `${s.spider_name} (${[...new Set(s.sites)].length} sites)`,
      ),
      datasets: renderDatasets(scrapeData, 8, 6),
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom' } },
      scales: baseScales('Template', 'Items scraped', { horizontal: true }),
    },
  });

  removeSpinner('.chart-A');
};

const chartB = scrapeData => {
  const canvas = document.getElementById('chartB__canvas');
  if (!canvas) return;

  const sortedData = [...scrapeData].sort((a, b) =>
    a.dateCreated > b.dateCreated ? 1 : -1,
  );
  const recent = sortedData.slice(-15);

  new Chart(canvas, {
    type: 'bar',
    data: {
      labels: recent.map(s => `${s.dateCreated} (${s.sites.length})`),
      datasets: renderDatasets(recent, 12, 6),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom' },
        tooltip: scrapeVolumeTooltip,
      },
      scales: baseScales('Date', 'Items scraped'),
    },
  });

  removeSpinner('.chart-B-C');
};

const chartC = scrapeData => {
  const canvas = document.getElementById('chartC__canvas');
  if (!canvas) return;

  const sortedData = [...scrapeData].sort((a, b) =>
    a.dateCreated > b.dateCreated ? 1 : -1,
  );
  const recent = sortedData.slice(-15);
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, 280);
  gradient.addColorStop(0, 'rgba(124, 58, 237, 0.25)');
  gradient.addColorStop(1, 'rgba(124, 58, 237, 0)');

  new Chart(canvas, {
    type: 'line',
    data: {
      labels: recent.map(s => s.dateCreated),
      datasets: [
        {
          label: 'Elapsed time (minutes)',
          data: recent.map(s => s.totalElapsed),
          borderColor: VDP.brand,
          backgroundColor: gradient,
          pointBackgroundColor: '#fff',
          pointBorderColor: VDP.brand,
          pointBorderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
          tension: 0.35,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom' },
        tooltip: elapsedTooltip,
      },
      scales: baseScales('Date', 'Minutes'),
    },
  });
};

const renderCharting = logs => {
  const output = Object.values(
    logs.reduce(
      (acc, { spider_name, items_scraped, elapsed_time_seconds, allowed_domain }) => (
        (acc[spider_name] ??= {
          spider_name,
          count: 0,
          totalScrapes: 0,
          totalElapsed: 0,
          sites: [],
        }),
        acc[spider_name].count++,
        (acc[spider_name].totalScrapes += +items_scraped),
        (acc[spider_name].totalElapsed += +elapsed_time_seconds),
        acc[spider_name].sites.push(allowed_domain),
        acc
      ),
      {},
    ),
  );

  chartA(output);
  filterScrapeDays(logs);
};

const filterScrapeDays = data => {
  const daysCreated = [...data]
    .sort((a, b) => (a.date_created > b.date_created ? 1 : -1))
    .map(obj => {
      const [m, d, y] = new Date(obj.date_created)
        .toLocaleString('en-US')
        .split(',')[0]
        .split('/');
      return {
        dateCreated: `${y}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`,
        provider: obj.spider_name,
        site: obj.target_site_id,
        scrapes: +obj.items_scraped,
        elaspedTimSec1: +obj.elapsed_time_seconds,
      };
    });

  const output = Object.values(
    daysCreated.reduce(
      (acc, { dateCreated, provider, site, scrapes, elaspedTimSec1 }) => (
        (acc[dateCreated] ??= {
          dateCreated,
          providers: [],
          sites: [],
          count: 0,
          totalScrapes: 0,
          totalElapsed: 0,
        }),
        acc[dateCreated].count++,
        (acc[dateCreated].totalScrapes += +scrapes),
        (acc[dateCreated].totalElapsed += +elaspedTimSec1 / 60),
        acc[dateCreated].providers.push(provider),
        acc[dateCreated].sites.push(site),
        acc
      ),
      {},
    ),
  );

  chartB(output);
  chartC(output);
};

const getSpiderLogs = () => {
  // Legacy endpoint — full SpiderLog dump; client aggregates for charts A/B/C.
  const spinners = {
    'chart-A': '.chart-A',
    chartBC: '.chart-B-C',
  };

  Object.entries(spinners).forEach(([, selector]) => {
    const container = document.querySelector(selector);
    if (!container) return;
    container.insertAdjacentHTML(
      'beforeend',
      `<div class="spinner-pulse text-brand-600 grid place-items-center py-16">
         <i class="fa fa-spinner fa-pulse fa-2x fa-fw"></i>
       </div>`,
    );
  });

  fetch('/spider-log-json/', {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  })
    .then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(data => {
      renderCharting(data);
    })
    .catch(error => {
      console.error('Dashboard chart load failed:', error);
      showChartError('.chart-A');
      showChartError('.chart-B-C');
    });
};

document.addEventListener('DOMContentLoaded', function () {
  // Setup charts render immediately from SSR; spider charts wait on fetch.
  renderSetupCharts();
  if (document.getElementById('chartA__canvas')) {
    getSpiderLogs();
  }
});
