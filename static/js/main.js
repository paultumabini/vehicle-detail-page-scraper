'use strict';

/*
  main.js — VDP Scraper shared frontend logic

  - VdpClientTable (vdp_client_table.js) for #dealers-list-table on targetsites
  - Alpine (base.html) handles sidebar, profile dropdown, delete modal
  - Dashboard counters use requestAnimationFrame
  - Scrape detail page uses VdpClientTable in datascraped.js
*/

/** Default Status filter on Target Sites — synced with targetsites.html <option selected>. */
const TARGET_SITES_DEFAULT_STATUS = 'Active';

document.addEventListener('DOMContentLoaded', function () {
  initDealersListTable();
  initDashboardCounter();
  wireDeleteButtons();
});

function initDealersListTable() {
  const el = document.querySelector('#dealers-list-table');
  if (!el || typeof VdpClientTable === 'undefined') return;

  // Defer table chrome + first draw so the page shell paints before sorting/filtering.
  requestAnimationFrame(function () {
    const table = new VdpClientTable(el, {
      stateSaveKey: 'dealers-list-table',
      pageLength: 10,
      lengthMenu: [5, 10, 20, 50, 100],
      nonSortableColumns: [8],
      exactColumnFilters: [4],
      initialColumnFilters: { 4: TARGET_SITES_DEFAULT_STATUS },
    });

    const statusFilter = document.getElementById('scrape-status');
    if (statusFilter) {
      if (!statusFilter.value && TARGET_SITES_DEFAULT_STATUS) {
        statusFilter.value = TARGET_SITES_DEFAULT_STATUS;
      }
      statusFilter.addEventListener('change', function () {
        table.column(4).search(this.value).draw();
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
