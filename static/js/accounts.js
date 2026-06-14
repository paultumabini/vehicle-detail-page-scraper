'use strict';

/*
  accounts.js — server-side paginated Accounts table (no jQuery / DataTables).

  Rows come from /accounts/datatable/ as HTML cell fragments (account_row.html).
  Use main.css classes in that partial — not Tailwind utilities (CDN skips AJAX HTML).

  Mutations (htmx clear-new): rows need htmx.process() after AJAX inject; reload via window.accountsTable.reload().

  Deep link: dashboard Need Setup card → /accounts/?setup=not-configured
    SSR (accounts_view + accounts.html) pre-selects filter-setup; syncFiltersFromUI()
    copies dropdown values into model.columnFilters before each AJAX fetch (fixes
    dropdown showing "Not configured" while the table still loaded unfiltered rows).
*/

/** Default Account Status when opening Accounts (matches admin changelist). */
const ACCOUNTS_DEFAULT_STATUS = 'ACTIVE';

const ACCOUNTS_STATUS_LABELS = {
  '': 'Total',
  ACTIVE: 'Active',
  INACTIVE: 'Inactive',
  DELETED: 'Deleted',
};

/** Scraping Setup filter labels — override Account Status label in the header count card. */
const ACCOUNTS_SETUP_LABELS = {
  '': null,
  configured: 'Configured',
  'not-configured': 'Need setup',
};

/** Header count card — mirrors active filters and datatable recordsFiltered. */
function updateAccountsTotalCard(statusFilter, setupFilter, count) {
  const countEl = document.getElementById('accounts-total-count');
  const labelEl = document.getElementById('accounts-total-label');
  if (!countEl || !labelEl) return;

  const status = statusFilter || '';
  const setup = setupFilter || '';
  countEl.textContent = count != null ? count : 0;
  // Setup filter takes precedence over Account Status in the header label.
  labelEl.textContent =
    ACCOUNTS_SETUP_LABELS[setup] ||
    ACCOUNTS_STATUS_LABELS[status] ||
    'Total';
}

function initAccountsTable() {
  const table = document.getElementById('accounts-table');
  const panel = document.getElementById('accounts-panel');
  if (!table || !panel || table.dataset.initialized) return;

  const url = table.dataset.datatableUrl;
  if (!url) return;

  table.dataset.initialized = '1';

  const state = loadAccountsState();
  const ui = {
    length: document.getElementById('accounts-length'),
    search: document.getElementById('accounts-search'),
    info: document.getElementById('accounts-info'),
    paging: document.getElementById('accounts-paging'),
    pageInput: document.getElementById('accounts-page-input'),
    pageGo: document.getElementById('accounts-page-go'),
    processing: document.getElementById('accounts-processing'),
    account: document.getElementById('filter-account'),
    setup: document.getElementById('filter-setup'),
    isNew: document.getElementById('filter-new'),
  };

  const model = {
    draw: 1,
    pageLength: state.pageLength || 25,
    pageIndex: state.pageIndex || 0,
    orderCol: state.orderCol != null ? state.orderCol : 1,
    orderDir: state.orderDir || 'asc',
    globalSearch: '',
    columnFilters: { 1: '', 3: ACCOUNTS_DEFAULT_STATUS, 4: '' },
    recordsFiltered: 0,
    pages: 1,
  };

  ui.length.value = String(model.pageLength);
  if (ui.account) {
    ui.account.value = ACCOUNTS_DEFAULT_STATUS;
  }

  const urlParams = new URLSearchParams(window.location.search);
  const setupParam = urlParams.get('setup');
  // columns[4] → accounts_datatable_json setup_filter (configured | not-configured).
  if (setupParam && ACCOUNTS_SETUP_LABELS[setupParam] && ui.setup) {
    ui.setup.value = setupParam;
    model.columnFilters[4] = setupParam;
    model.pageIndex = 0;
  }

  /** Mirror filter dropdowns → model.columnFilters (source of truth for buildParams). */
  function syncFiltersFromUI() {
    if (ui.account) {
      model.columnFilters[3] = ui.account.value;
    }
    if (ui.setup) {
      model.columnFilters[4] = ui.setup.value;
    }
    if (ui.isNew) {
      model.columnFilters[1] = ui.isNew.value;
    }
  }

  // Called on init so SSR-selected filter-setup is sent on the first datatable fetch.
  syncFiltersFromUI();

  function setProcessing(on) {
    ui.processing.classList.toggle('hidden', !on);
  }

  function buildParams() {
    // Re-read dropdowns every fetch — change handlers update model too, but SSR deep link did not.
    syncFiltersFromUI();
    const params = new URLSearchParams();
    params.set('draw', String(model.draw++));
    params.set('start', String(model.pageIndex * model.pageLength));
    params.set('length', String(model.pageLength));
    params.set('search[value]', model.globalSearch);
    params.set('order[0][column]', String(model.orderCol));
    params.set('order[0][dir]', model.orderDir);
    Object.keys(model.columnFilters).forEach(function (col) {
      params.set(
        'columns[' + col + '][search][value]',
        model.columnFilters[col] || '',
      );
    });
    // Flat param — datatable view also reads ?setup= (reliable deep link from dashboard).
    if (model.columnFilters[4]) {
      params.set('setup', model.columnFilters[4]);
    }
    return params;
  }

  function renderRows(rows) {
    const tbody = table.querySelector('tbody');
    if (!rows.length) {
      tbody.innerHTML =
        '<tr><td colspan="10" class="text-center text-slate-400 py-10 text-sm">No accounts found.</td></tr>';
      return;
    }
    tbody.innerHTML = rows
      .map(function (cells) {
        return (
          '<tr>' +
          cells
            .map(function (html) {
              return '<td>' + html + '</td>';
            })
            .join('') +
          '</tr>'
        );
      })
      .join('');
    // Rows are injected via innerHTML — htmx must process them for hx-post / hx-confirm.
    if (typeof htmx !== 'undefined') {
      htmx.process(tbody);
    }
  }

  function renderPaging() {
    ui.paging.innerHTML = '';
    const current = model.pageIndex;
    const pages = model.pages;

    function addBtn(label, page, disabled, isCurrent) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'vdp-paging-btn';
      btn.textContent = label;
      btn.disabled = disabled;
      if (isCurrent) btn.classList.add('current');
      if (!disabled && !isCurrent) {
        btn.addEventListener('click', function () {
          model.pageIndex = page;
          fetchPage();
        });
      }
      ui.paging.appendChild(btn);
    }

    addBtn('‹', current - 1, current === 0, false);

    const windowSize = 5;
    let startPage = Math.max(current - Math.floor(windowSize / 2), 0);
    let endPage = Math.min(startPage + windowSize, pages);
    startPage = Math.max(endPage - windowSize, 0);

    for (let p = startPage; p < endPage; p += 1) {
      addBtn(String(p + 1), p, false, p === current);
    }

    addBtn('›', current + 1, current >= pages - 1, false);

    ui.pageInput.value = String(current + 1);
    ui.pageInput.max = String(pages || 1);
  }

  function updateInfo(start, shown, total, maxTotal) {
    if (!total) {
      ui.info.textContent = 'No accounts found';
      return;
    }
    let text =
      'Showing ' + (start + 1) + '–' + (start + shown) + ' of ' + total;
    if (total !== maxTotal) {
      text += ' (filtered from ' + maxTotal + ' total)';
    }
    ui.info.textContent = text;
  }

  function updateSortIndicators() {
    table.querySelectorAll('thead th').forEach(function (th, index) {
      th.classList.remove('vdp-sorted-asc', 'vdp-sorted-desc');
      if (index === model.orderCol) {
        th.classList.add(
          model.orderDir === 'asc' ? 'vdp-sorted-asc' : 'vdp-sorted-desc',
        );
      }
    });
  }

  function saveState() {
    localStorage.setItem(
      'vdp-accounts',
      JSON.stringify({
        pageLength: model.pageLength,
        pageIndex: model.pageIndex,
        orderCol: model.orderCol,
        orderDir: model.orderDir,
      }),
    );
  }

  function fetchPage() {
    setProcessing(true);
    fetch(url + '?' + buildParams().toString(), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      })
      .then(function (payload) {
        const start = model.pageIndex * model.pageLength;
        const shown = payload.data.length;
        model.recordsFiltered = payload.recordsFiltered;
        model.pages = Math.max(
          Math.ceil(payload.recordsFiltered / model.pageLength),
          1,
        );
        if (model.pageIndex >= model.pages) {
          model.pageIndex = Math.max(model.pages - 1, 0);
          if (start !== model.pageIndex * model.pageLength) {
            fetchPage();
            return;
          }
        }
        updateAccountsTotalCard(
          model.columnFilters[3],
          model.columnFilters[4],
          payload.recordsFiltered, // same total as table footer "Showing … of N"
        );
        renderRows(payload.data);
        updateInfo(start, shown, payload.recordsFiltered, payload.recordsTotal);
        renderPaging();
        updateSortIndicators();
        saveState();
      })
      .catch(function (err) {
        console.error('Accounts table load failed:', err);
        table.querySelector('tbody').innerHTML =
          '<tr><td colspan="10" class="text-center text-red-500 py-10 text-sm">Failed to load accounts.</td></tr>';
      })
      .finally(function () {
        setProcessing(false);
      });
  }

  ui.length.addEventListener('change', function () {
    model.pageLength = parseInt(this.value, 10) || 25;
    model.pageIndex = 0;
    fetchPage();
  });

  let searchTimer;
  ui.search.addEventListener('input', function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      model.globalSearch = ui.search.value.trim();
      model.pageIndex = 0;
      fetchPage();
    }, 300);
  });

  ui.account.addEventListener('change', function () {
    model.columnFilters[3] = this.value;
    model.pageIndex = 0;
    fetchPage();
  });
  ui.setup.addEventListener('change', function () {
    model.columnFilters[4] = this.value;
    model.pageIndex = 0;
    fetchPage();
  });
  ui.isNew.addEventListener('change', function () {
    model.columnFilters[1] = this.value;
    model.pageIndex = 0;
    fetchPage();
  });

  ui.pageGo.addEventListener('click', function () {
    const page = parseInt(ui.pageInput.value, 10);
    if (!page || page < 1 || page > model.pages) return;
    model.pageIndex = page - 1;
    fetchPage();
  });
  ui.pageInput.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') ui.pageGo.click();
  });

  table.querySelectorAll('thead th').forEach(function (th, index) {
    if (index === 9) return;
    th.classList.add('vdp-sortable');
    th.addEventListener('click', function () {
      if (model.orderCol === index) {
        model.orderDir = model.orderDir === 'asc' ? 'desc' : 'asc';
      } else {
        model.orderCol = index;
        model.orderDir = 'asc';
      }
      fetchPage();
    });
  });

  document.body.addEventListener('htmx:afterRequest', function (event) {
    if (
      event.detail.successful &&
      event.detail.elt &&
      event.detail.elt.closest('#accounts-table')
    ) {
      fetchPage();
    }
  });

  window.accountsTable = { reload: fetchPage };
  fetchPage();
}

function loadAccountsState() {
  try {
    const raw = localStorage.getItem('vdp-accounts');
    return raw ? JSON.parse(raw) : {};
  } catch (_err) {
    return {};
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAccountsTable);
} else {
  initAccountsTable();
}
