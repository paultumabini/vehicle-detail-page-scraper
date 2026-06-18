'use strict';

/*
  main.js — VDP Scraper shared frontend logic

  - VdpClientTable (vdp_client_table.js) for #dealers-list-table on targetsites
  - Alpine (base.html) handles sidebar, profile dropdown, delete modal
  - Dashboard counters use requestAnimationFrame
  - Scrape detail page uses VdpClientTable in datascraped.js

  Target Sites table notes (targetsites.html):
    Server renders every row; VdpClientTable paginates/filters client-side.
    Stale localStorage search/pageLength once hid all but one row — see init options below.
*/

/** Default Status filter on Target Sites — synced with targetsites.html <option selected>. */
const TARGET_SITES_DEFAULT_STATUS = 'Active';

/** Rows rendered server-side (excludes the empty-state placeholder). */
function getTargetSiteTableRows(tableEl) {
  return Array.from(tableEl.querySelectorAll('tbody tr')).filter(function (tr) {
    return !tr.querySelector('.vdp-empty-row') && tr.cells.length > 1;
  });
}

/** Count rows whose hidden Status .dt-val matches (powers exact column filter). */
function countTargetSiteStatusRows(rows, status) {
  return rows.filter(function (row) {
    const dtVal = row.cells[1] && row.cells[1].querySelector('.dt-val');
    return dtVal && dtVal.textContent.trim() === status;
  }).length;
}

/**
 * Pick the initial Status filter. Default is Active, but fall back to All when every
 * row is Inactive/Pending/etc. — otherwise VdpClientTable hides the flash of server HTML.
 */
function resolveTargetSitesDefaultStatus(tableEl) {
  const rows = getTargetSiteTableRows(tableEl);
  const preferred = TARGET_SITES_DEFAULT_STATUS;
  if (!preferred || rows.length === 0) {
    return '';
  }
  if (countTargetSiteStatusRows(rows, preferred) > 0) {
    return preferred;
  }
  return '';
}

document.addEventListener('DOMContentLoaded', function () {
  initDealersListTable();
  initDashboardCounter();
  wireDeleteButtons();
});

// Back/forward cache can restore a tbody with only the last paginated page in the DOM.
// Redraw from in-memory allRows (still holds the full server render) and clear search.
window.addEventListener('pageshow', function (event) {
  if (!event.persisted) return;
  const table = document.querySelector('#dealers-list-table')?._vdpTable;
  if (!table) return;
  table.globalSearch = '';
  if (table.searchInput) {
    table.searchInput.value = '';
  }
  table.pageIndex = 0;
  table.draw();
});

function initDealersListTable() {
  const el = document.querySelector('#dealers-list-table');
  if (!el || typeof VdpClientTable === 'undefined') return;

  // Drop legacy table state (v2 stored a search term that matched only one row).
  try {
    localStorage.removeItem('vdp-table:dealers-list-table-v2');
  } catch (_err) {
    /* ignore */
  }

  // Target Sites column map (0-based) — keep in sync with targetsites.html / target_site_row.html:
  //   0 Entry | 1 Status | 2 Site Name | 3 Provider
  //   4 Items Scraped | 5 Last Run | 6 Exported | 7 Actions
  // Defer table chrome + first draw so the page shell paints before sorting/filtering.
  requestAnimationFrame(function () {
    const defaultStatus = resolveTargetSitesDefaultStatus(el);
    const initialColumnFilters = {};
    if (defaultStatus) {
      initialColumnFilters[1] = defaultStatus;
    }

    const table = new VdpClientTable(el, {
      // Bump key when table behaviour changes — avoids inheriting bad localStorage state.
      stateSaveKey: 'dealers-list-table-v3',
      pageLength: 10,
      lengthMenu: [5, 10, 20, 50, 100],
      nonSortableColumns: [7], // Actions
      exactColumnFilters: [1], // Status dot column (hidden .dt-val text)
      initialColumnFilters: initialColumnFilters,
      // Do not restore toolbar search — a leftover term (e.g. items-scraped "120") matched one row.
      persistSearch: false,
      // Always open on page 1; saved pageIndex + pageLength=1 looked like a single-row table.
      resetPageIndexOnLoad: true,
      minPageLength: 5,
    });

    // Status dropdown drives column 1; value synced after resolveTargetSitesDefaultStatus().
    const statusFilter = document.getElementById('scrape-status');
    if (statusFilter) {
      statusFilter.value = defaultStatus;
      statusFilter.addEventListener('change', function () {
        table.column(1).search(this.value).draw();
      });
    }

    const providerFilter = document.getElementById('site-provider');
    if (providerFilter) {
      providerFilter.addEventListener('change', function () {
        table.column(3).search(this.value).draw();
      });
    }
  });
}

function initDashboardCounter() {
  document.querySelectorAll('.value[data-target]').forEach(function (el) {
    const target =
      parseInt(el.getAttribute('data-target').replace(/\D/g, ''), 10) || 0;
    const duration = 3000;
    const start = performance.now();

    function step(now) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 0.5 - Math.cos(progress * Math.PI) / 2;
      el.textContent = Math.ceil(target * eased).toLocaleString();
      if (progress < 1) {
        requestAnimationFrame(step);
      }
    }

    requestAnimationFrame(step);
  });
}

function wireDeleteButtons() {
  if (typeof deleteItemModal !== 'function') return;

  // Event delegation — VdpClientTable re-renders tbody on pagination/filter.
  deleteItemModal(function (project, site) {
    document.addEventListener('click', function (e) {
      const btn = e.target.closest('.openDeleteModal');
      if (!btn) return;
      window.dispatchEvent(
        new CustomEvent('open-delete-modal', {
          detail: {
            project,
            site,
            siteId: btn.dataset.siteId,
            siteName: btn.dataset.siteName,
          },
        }),
      );
    });
  });
}
