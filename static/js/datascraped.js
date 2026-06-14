// Scrape detail page — load scraped data, modals, VdpClientTable (no jQuery)
//
// Used on targetsite_detail.html ("View scrapes" button).
// Page must define filterResult(site rows) and deleteItemModal (see inline {% block js %}).
'use strict';

let scrapeDataTable = null;
let imageUrlsTable = null;
let scrapeLoadStartedAt = 0;
// Rows passed to modal handlers — set when the scrape table renders (see renderTableStructure).
let scrapeModalData = null;

// Minimum overlay visibility — fast JSON responses still show feedback briefly.
const SCRAPE_LOADER_MIN_MS = 550;

// Fixed blur overlay (not in #scraped-data-panel) so reload never deletes #unitDetailModal.
const SCRAPE_LOADER_OVERLAY_HTML = `
  <div id="vdp-scrape-loader-overlay" class="vdp-scrape-loader-overlay" role="status" aria-live="polite" aria-busy="true">
    <div class="vdp-scrape-loader-overlay__card">
      <i class="fa fa-circle-notch fa-spin vdp-scrape-loader-overlay__icon" aria-hidden="true"></i>
      <span class="vdp-scrape-loader-overlay__label">Loading scraped data…</span>
    </div>
  </div>
`;

function showScrapeLoader() {
  scrapeLoadStartedAt = performance.now();
  if (!document.getElementById('vdp-scrape-loader-overlay')) {
    document.body.insertAdjacentHTML('beforeend', SCRAPE_LOADER_OVERLAY_HTML);
  }
  document.body.classList.add('vdp-scrape-loading');
}

function hideScrapeLoader(immediate = false, onHidden) {
  const remove = () => {
    document.getElementById('vdp-scrape-loader-overlay')?.remove();
    document.body.classList.remove('vdp-scrape-loading');
    scrapeLoadStartedAt = 0;
    onHidden?.();
  };

  if (immediate || !scrapeLoadStartedAt) {
    remove();
    return;
  }

  const elapsed = performance.now() - scrapeLoadStartedAt;
  setTimeout(remove, Math.max(0, SCRAPE_LOADER_MIN_MS - elapsed));
}

function scrollToScrapedData() {
  const target =
    document.querySelector('#scraped-data-panel .scraped__data') ||
    document.getElementById('scraped-data-panel');

  if (!target) return;

  // scrollIntoView works when the window scrolls (main has no fixed height on long pages).
  // scroll-margin-top on #scraped-data-panel / .scraped__data clears the sticky topbar.
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

function showUnitModal() {
  const modal = document.getElementById('unitDetailModal');
  if (!modal) return;
  modal.classList.add('is-open');
  modal.setAttribute('aria-hidden', 'false');
  document.body.classList.add('unit-modal-open');

  const dialog = modal.querySelector('.modal-dialog');
  if (dialog && !dialog.dataset.dragInit) {
    initModalDrag(dialog);
    dialog.dataset.dragInit = '1';
  }
}

function hideUnitModal() {
  const modal = document.getElementById('unitDetailModal');
  if (!modal) return;
  modal.classList.remove('is-open');
  modal.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('unit-modal-open');
}

function initUnitModalDismiss() {
  const modal = document.getElementById('unitDetailModal');
  if (!modal) return;

  modal.querySelectorAll('[data-dismiss="modal"], .close-btn').forEach(btn => {
    btn.addEventListener('click', hideUnitModal);
  });

  modal.addEventListener('click', e => {
    if (e.target === modal) hideUnitModal();
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && modal.classList.contains('is-open')) {
      hideUnitModal();
    }
  });
}

function initModalDrag(dialog) {
  const header = dialog.querySelector('.modal-header');
  if (!header) return;

  let dragging = false;
  let startX = 0;
  let startY = 0;
  let origLeft = 0;
  let origTop = 0;

  header.style.cursor = 'move';

  header.addEventListener('mousedown', e => {
    dragging = true;
    startX = e.clientX;
    startY = e.clientY;
    const rect = dialog.getBoundingClientRect();
    origLeft = rect.left;
    origTop = rect.top;
    dialog.style.position = 'fixed';
    dialog.style.margin = '0';
    dialog.style.left = `${origLeft}px`;
    dialog.style.top = `${origTop}px`;
    e.preventDefault();
  });

  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    dialog.style.left = `${origLeft + e.clientX - startX}px`;
    dialog.style.top = `${origTop + e.clientY - startY}px`;
  });

  document.addEventListener('mouseup', () => {
    dragging = false;
  });
}

// ── Scrape data table (project.Scrape) ───────────────────────────────────────
// Column config mirrors Scrape model fields from /scrape-data-json/ (views.scrape_data_json).
// id / target_site_id / spider / page omitted — not shown in the scrape table UI.
// type drives cell rendering; footerClass hooks initScrapeDataTable() image-count total.
const SCRAPE_TABLE_COLUMNS = [
  { key: 'category', label: 'Category' },
  { key: 'year', label: 'Year' },
  { key: 'make', label: 'Make' },
  { key: 'model', label: 'Model' },
  { key: 'trim', label: 'Trim' },
  { key: 'unit', label: 'As Unit' },
  { key: 'stock_number', label: 'Stock#', type: 'stock-link' },
  { key: 'vin', label: 'VIN' },
  { key: 'vehicle_url', label: 'Vehicle URL', type: 'url' },
  { key: 'msrp', label: 'MSRP' },
  { key: 'price', label: 'Price' },
  { key: 'selling_price', label: 'Selling Price' },
  { key: 'rebate', label: 'Rebate' },
  { key: 'discount', label: 'Discount' },
  { key: 'image_urls', label: 'Images', type: 'image-list' },
  { key: 'images_count', label: 'Image Count', type: 'count', footerClass: 'total-images' },
  { key: 'last_checked', label: 'Last Checked' },
];

// Stock# detail modal — keys align with SCRAPE_TABLE_COLUMNS (image_urls shown via gallery, not as text).
const VEHICLE_DETAIL_LABELS = {
  'Stock#:': 'stock_number',
  'VIN:': 'vin',
  'Vehicle URL:': 'vehicle_url',
  'Category:': 'category',
  'Year:': 'year',
  'Make:': 'make',
  'Model:': 'model',
  'Trim:': 'trim',
  'As a Unit:': 'unit',
  'Msrp:': 'msrp',
  'Price:': 'price',
  'Selling Price:': 'selling_price',
  'Rebate:': 'rebate',
  'Discount:': 'discount',
  'Last Checked:': 'last_checked',
  'Image Count:': 'images_count',
};

// Null-safe empty strings — JSON from Scrape.objects.values() may omit or null fields.
function normalizeScrapeRow(data) {
  SCRAPE_TABLE_COLUMNS.forEach(({ key }) => {
    if (data[key] == null || data[key] === undefined) data[key] = '';
  });
  return data;
}

// stock-link opens vehicle detail; image-list opens slideshow directly when URLs exist.
function parseImageUrls(raw) {
  if (!raw || typeof raw !== 'string') return [];
  return raw.split('|').map(url => url.trim()).filter(Boolean);
}

function getScrapeRowByStock(data, stockNumber) {
  return data.find(row => row.stock_number === stockNumber) || null;
}

function renderScrapeCell(column, data) {
  const value = data[column.key] ?? '';

  switch (column.type) {
    case 'stock-link':
      return `<td>
            <button
              type="button"
              class="load__modal--stock vdp-scrape-modal-link"
              data-stock-number="${data.stock_number}"
              title="${value}"
            >${value}</button>
          </td>`;
    case 'url':
      return `<td class="vdp-url-cell">
            <a
              href="${value || '#'}"
              target="_blank"
              rel="noopener noreferrer"
              title="${value || '#'}"
              class="vdp-table-link vdp-cell-url"
            >${value}</a>
          </td>`;
    case 'image-list': {
      const urls = parseImageUrls(value);
      const count = urls.length || parseInt(String(data.images_count).replace(/\D/g, ''), 10) || 0;
      if (!count) {
        return '<td class="text-center vdp-cell-muted">—</td>';
      }
      return `<td class="text-center">
            <button
              type="button"
              class="load__modal--images vdp-scrape-modal-link"
              title="View ${count} image${count === 1 ? '' : 's'}"
              data-stock-number="${data.stock_number}"
            ><i class="fa fa-images" aria-hidden="true"></i> ${count}</button>
          </td>`;
    }
    case 'count':
      return `<td class="text-center">${value || 0}</td>`;
    default:
      return `<td><span title="${value}">${value}</span></td>`;
  }
}

// thead/tfoot built from SCRAPE_TABLE_COLUMNS so header, body, and footer stay aligned.
function buildScrapeTableHead() {
  const headers = ['<th scope="col" style="width:3%">No</th>'];
  SCRAPE_TABLE_COLUMNS.forEach(col => {
    headers.push(`<th>${col.label}</th>`);
  });
  return `<tr>${headers.join('')}</tr>`;
}

function buildScrapeTableFoot() {
  const cells = ['<th></th>'];
  SCRAPE_TABLE_COLUMNS.forEach(col => {
    if (col.footerClass) {
      cells.push(`<th class="${col.footerClass}" style="text-align: center"></th>`);
    } else {
      cells.push('<th></th>');
    }
  });
  return `<tr>${cells.join('')}</tr>`;
}

const renderTableContent = fdata => {
  return fdata
    .reduce((acc, data, i) => {
      normalizeScrapeRow(data);
      const cells = [`<td>${i + 1}</td>`];
      SCRAPE_TABLE_COLUMNS.forEach(col => {
        cells.push(renderScrapeCell(col, data));
      });
      acc.push(`<tr>${cells.join('')}</tr>`);
      return acc;
    }, [])
    .join('');
};

function wireAlertDismiss(alertEl) {
  const closeBtn = alertEl.querySelector('.vdp-scrape-alert__close');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => alertEl.remove());
  }
}

const raiseAlert = (level, message, reload) => {
  const wrapper = document.querySelector('.flash-messages-wrapper');
  if (!wrapper) return;
  wrapper.innerHTML = '';

  const alertMessage = document.createElement('div');
  alertMessage.className = `vdp-scrape-alert vdp-scrape-alert--${level}`;
  alertMessage.innerHTML = `
      <i class="fa fa-triangle-exclamation" aria-hidden="true"></i>
      <button type="button" class="vdp-scrape-alert__close" aria-label="Close">
          <span aria-hidden="true">&times;</span>
      </button>
      <span>${message}</span>
      ${
        reload
          ? `<button type="button" class="vdp-btn vdp-btn--primary vdp-btn--sm scrape-reload-btn">Yes</button>
             <p class="vdp-scrape-alert__countdown">[exit in <span id="countdown">4</span> sec]</p>`
          : ''
      }`;

  wrapper.appendChild(alertMessage);
  wireAlertDismiss(alertMessage);

  if (reload) {
    const reloadBtn = alertMessage.querySelector('.scrape-reload-btn');
    if (reloadBtn) reloadBtn.addEventListener('click', fetchScrapeData);

    let timeleft = 4;
    const timer = setInterval(() => {
      timeleft--;
      const countdown = document.getElementById('countdown');
      if (!countdown) {
        clearInterval(timer);
        return;
      }
      countdown.textContent = timeleft;
      if (timeleft <= 0) clearInterval(timer);
    }, 1000);
  }
};

const renderTableStructure = fdata => {
  if (!fdata || !fdata.length) {
    hideScrapeLoader(true);
    const emptyMessage =
      typeof scrapeEmptyMessage === 'string'
        ? scrapeEmptyMessage
        : 'No scrape data for this site yet. Run a crawl or check back after the next scrape.';
    raiseAlert('warning', emptyMessage, false);
    return;
  }

  // No overflow-hidden / w-full on the card or table — horizontal scroll lives in
  // .vdp-table-scroll (injected by VdpClientTable.ensureChrome in vdp_client_table.js).
  const tableStructure = `
      <div class="scraped__data vdp-card p-0">
          <h3 class="scraped__data-title">Scraped data</h3>
          <table id="scrape-data-table" class="vdp-data-table">
              <thead>
              ${buildScrapeTableHead()}
              </thead>
              <tbody id="scrape-data-tbody" > 
              </tbody>
              <tfoot>
                ${buildScrapeTableFoot()}
            </tfoot>       
          </table>          
      </div>  
      `;

  const scrapePanel = document.getElementById('scraped-data-panel');
  const scrapeDetail = document.querySelector('.vdp-site-detail');
  const insertTarget = scrapePanel || scrapeDetail;
  if (!insertTarget) return;

  if (scrapePanel) {
    // Preferred host — see targetsite_detail.html #scraped-data-panel
    scrapePanel.innerHTML = tableStructure;
  } else {
    insertTarget.insertAdjacentHTML('afterend', tableStructure);
  }

  const tBody = document.getElementById('scrape-data-tbody');
  tBody.insertAdjacentHTML('afterbegin', renderTableContent(fdata));

  scrapeModalData = fdata;
  initScrapeDataTable();

  hideScrapeLoader(false, () => {
    // Scroll after overlay dismisses so the table is visible beneath the sticky header.
    setTimeout(scrollToScrapedData, 60);
  });
};

function clearScrapedDataPanel() {
  // Only empty the table host — never walk siblings (would remove #unitDetailModal).
  const panel = document.getElementById('scraped-data-panel');
  if (panel) {
    panel.innerHTML = '';
    return;
  }
  document.querySelectorAll('.scraped__data').forEach(el => el.remove());
}

function fetchScrapeData() {
  if (!document.querySelector('.vdp-site-detail')) return;

  clearScrapedDataPanel();
  showScrapeLoader();
  scrapeModalData = null;

  if (scrapeDataTable) {
    scrapeDataTable.destroy();
    scrapeDataTable = null;
  }

  fetch('/scrape-data-json/', {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  })
    .then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(data => {
      if (typeof filterResult === 'function') {
        filterResult(data);
        return;
      }
      hideScrapeLoader(true);
      console.error('filterResult is not defined on this page.');
    })
    .catch(error => {
      hideScrapeLoader(true);
      console.error('Scrape data load failed:', error);
      raiseAlert('warning', 'Could not load scrape data. Please try again.', false);
    });
}

const loadData = () => {
  if (document.querySelector('.scraped__data') || document.getElementById('scraped-data-panel')?.querySelector('.scraped__data')) {
    raiseAlert('warning', 'Scraped data already loaded. Reload?', true);
    return;
  }

  fetchScrapeData();
};

// ── Unit modal — image gallery + vehicle detail (targetsite_detail.html #unitDetailModal) ──

function initImageUrlsTable() {
  const el = document.getElementById('table_image_urls');
  if (!el || typeof VdpClientTable === 'undefined') return;

  if (imageUrlsTable) {
    imageUrlsTable.destroy();
    imageUrlsTable = null;
  }

  imageUrlsTable = new VdpClientTable(el, {
    stateSaveKey: 'table_image_urls',
    pageLength: 10,
    lengthMenu: [5, 10, 20, 50, 100],
  });
}

// Prev/next for mountImageCarousel — scoped to the modal images host, not document-wide.
function wireCarouselNav(container) {
  const slides = container.getElementsByClassName('vdp-carousel__item');
  if (!slides.length) return;

  let slidePosition = 0;
  const totalSlides = slides.length;

  function updateSlidePosition() {
    Array.from(slides).forEach(slide => {
      slide.classList.remove('vdp-carousel__item--visible');
      slide.classList.add('vdp-carousel__item--hidden');
    });
    slides[slidePosition].classList.add('vdp-carousel__item--visible');
    slides[slidePosition].classList.remove('vdp-carousel__item--hidden');
    const counter = container.querySelector('.image-number');
    if (counter) counter.textContent = slides[slidePosition].dataset.imageNumber;
  }

  container.querySelector('#carousel__button--next')?.addEventListener('click', () => {
    slidePosition = slidePosition === totalSlides - 1 ? 0 : slidePosition + 1;
    updateSlidePosition();
  });

  container.querySelector('#carousel__button--prev')?.addEventListener('click', () => {
    slidePosition = slidePosition === 0 ? totalSlides - 1 : slidePosition - 1;
    updateSlidePosition();
  });
}

// Slideshow viewer — shared by Images column (default) and Stock# detail modal.
function mountImageCarousel(imagesHost, urls) {
  imagesHost.innerHTML = `
    <div class="vdp-carousel__loading text-brand-600">
      <i class="fa fa-spinner fa-pulse fa-3x fa-fw" aria-hidden="true"></i>
    </div>
  `;

  const carouselMarkup = urls
    .map((url, i) => {
      const visibleClass = i === 0 ? ' vdp-carousel__item--visible' : ' vdp-carousel__item--hidden';
      return `
        <div class="vdp-carousel">
          <div class="vdp-carousel__item${visibleClass}" data-image-number="${i + 1}">
            <a href="${url}" target="_blank" rel="noopener noreferrer">
              <img class="vdp-carousel__image" src="${url}" alt="Vehicle image ${i + 1}" loading="lazy" />
            </a>
          </div>
        </div>
      `;
    })
    .join('');

  imagesHost.insertAdjacentHTML('afterbegin', carouselMarkup);

  const firstImage = imagesHost.querySelector('.vdp-carousel__image');
  const finishCarousel = () => {
    imagesHost.querySelector('.vdp-carousel__loading')?.remove();
    imagesHost.insertAdjacentHTML(
      'beforeend',
      `
        <div class="vdp-carousel__actions">
          <button type="button" id="carousel__button--prev" aria-label="Previous slide">
            <i class="fa fa-chevron-left" aria-hidden="true"></i>
          </button>
          <button type="button" id="carousel__button--next" aria-label="Next slide">
            <i class="fa fa-chevron-right" aria-hidden="true"></i>
          </button>
        </div>
        <p class="vdp-carousel__count">
          <span class="image-number">1</span> / ${urls.length}
        </p>
      `,
    );
    wireCarouselNav(imagesHost);
  };

  if (!firstImage) {
    finishCarousel();
    return;
  }

  if (firstImage.complete) {
    finishCarousel();
    return;
  }

  firstImage.addEventListener('load', finishCarousel, { once: true });
  firstImage.addEventListener('error', finishCarousel, { once: true });
}

function mountImageUrlList(imagesHost, urls) {
  const tableStructure = `
    <div class="vdp-unit-modal__table-wrap">
      <table id="table_image_urls" class="vdp-data-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Image URLs (Total: ${urls.length})</th>
          </tr>
        </thead>
        <tbody id="image-urls-tbody">
          ${urls
            .map(
              (url, i) => `
            <tr>
              <td>${i + 1}</td>
              <td>
                <a href="${url}" target="_blank" rel="noopener noreferrer" class="vdp-table-link vdp-cell-url">${url}</a>
              </td>
            </tr>
          `,
            )
            .join('')}
        </tbody>
      </table>
    </div>
  `;

  imagesHost.innerHTML = tableStructure;
  initImageUrlsTable();
}

function setGalleryViewToggle(viewImages, viewList, active) {
  const slideshowActive = active === 'slideshow';
  viewImages?.classList.toggle('is-active', slideshowActive);
  viewList?.classList.toggle('is-active', !slideshowActive);
  viewImages?.setAttribute('aria-pressed', String(slideshowActive));
  viewList?.setAttribute('aria-pressed', String(!slideshowActive));
}

// Slideshow ↔ URL list toggle used by the Images column gallery modal.
function wireGalleryViewToggle(imagesHost, urls, viewImages, viewList) {
  const showSlideshow = () => {
    setGalleryViewToggle(viewImages, viewList, 'slideshow');
    mountImageCarousel(imagesHost, urls);
  };
  const showUrlList = () => {
    setGalleryViewToggle(viewImages, viewList, 'url-list');
    mountImageUrlList(imagesHost, urls);
  };

  viewImages?.addEventListener('click', showSlideshow);
  viewList?.addEventListener('click', showUrlList);
  showSlideshow();
}

function setUnitModalTitle(stockNumber) {
  const title = document.getElementById('unitModalLabel');
  if (title) title.textContent = stockNumber ? `Stock# ${stockNumber}` : 'Vehicle details';
}

// Images column click — slideshow-first gallery (.vdp-unit-modal__body--gallery).
function openImageGalleryModal(data, stockNumber) {
  const unitDetailModal = document.querySelector('#unitDetailModal');
  const mBody = unitDetailModal?.querySelector('.modal-body');
  if (!mBody) return;

  const row = getScrapeRowByStock(data, stockNumber);
  const urls = parseImageUrls(row?.image_urls);
  const count = urls.length;

  showUnitModal();
  setUnitModalTitle(stockNumber);
  mBody.className = 'modal-body vdp-unit-modal__body vdp-unit-modal__body--gallery';

  if (!count) {
    mBody.innerHTML = '<p class="vdp-unit-modal__empty">No images scraped for this vehicle.</p>';
    return;
  }

  mBody.innerHTML = `
    <p class="vdp-unit-modal__gallery-meta">${count} image${count === 1 ? '' : 's'} · Stock# ${stockNumber}</p>
    <div class="vdp-unit-modal__actions vdp-unit-modal__actions--gallery">
      <button type="button" class="vdp-btn vdp-btn--secondary vdp-btn--sm view-images is-active" aria-pressed="true">Slideshow</button>
      <button type="button" class="vdp-btn vdp-btn--secondary vdp-btn--sm view-list" aria-pressed="false">URL list</button>
    </div>
    <div class="vdp-unit-modal__images"></div>
  `;

  wireGalleryViewToggle(
    mBody.querySelector('.vdp-unit-modal__images'),
    urls,
    mBody.querySelector('.view-images'),
    mBody.querySelector('.view-list'),
  );
}

// Stock# click — full row fields; image actions only when image_urls has entries.
function openVehicleDetailModal(data, stockNumber) {
  const unitDetailModal = document.querySelector('#unitDetailModal');
  const mBody = unitDetailModal?.querySelector('.modal-body');
  if (!mBody) return;

  const row = getScrapeRowByStock(data, stockNumber);
  if (!row) return;

  const markUp = Object.entries(VEHICLE_DETAIL_LABELS)
    .map(([label, key]) => {
      const fieldValue = row[key] ?? '';
      if (key === 'vehicle_url') {
        return `
          <div class="vdp-unit-modal__field">
            <span class="vdp-unit-modal__label">${label}</span>
            <a href="${fieldValue}" target="_blank" rel="noopener noreferrer" class="vdp-table-link vdp-cell-url">${fieldValue}</a>
          </div>
        `;
      }
      return `
        <div class="vdp-unit-modal__field">
          <span class="vdp-unit-modal__label">${label}</span>
          <span>${fieldValue}</span>
        </div>
      `;
    })
    .join('');

  const urls = parseImageUrls(row.image_urls);
  const hasImages = urls.length > 0;

  showUnitModal();
  setUnitModalTitle(stockNumber);
  mBody.className = 'modal-body vdp-unit-modal__body';
  mBody.innerHTML = markUp;

  if (hasImages) {
    mBody.insertAdjacentHTML(
      'beforeend',
      `
        <div class="vdp-unit-modal__actions">
          <button type="button" class="vdp-btn vdp-btn--secondary vdp-btn--sm view-images">View images</button>
          <button type="button" class="vdp-btn vdp-btn--secondary vdp-btn--sm view-list">Image URLs</button>
        </div>
        <div class="vdp-unit-modal__images"></div>
      `,
    );

    const imagesHost = mBody.querySelector('.vdp-unit-modal__images');
    mBody.querySelector('.view-images')?.addEventListener('click', () => {
      imagesHost.innerHTML = '';
      mountImageCarousel(imagesHost, urls);
    });
    mBody.querySelector('.view-list')?.addEventListener('click', () => {
      imagesHost.innerHTML = '';
      mountImageUrlList(imagesHost, urls);
    });
  }
}

// Event delegation on #scraped-data-panel — works after VdpClientTable pagination re-draws tbody.
function initScrapeModalDelegation() {
  const panel = document.getElementById('scraped-data-panel');
  if (!panel || panel.dataset.modalDelegation) return;
  panel.dataset.modalDelegation = '1';

  panel.addEventListener('click', e => {
    if (!scrapeModalData) return;

    const stockBtn = e.target.closest('.load__modal--stock');
    if (stockBtn) {
      openVehicleDetailModal(scrapeModalData, stockBtn.dataset.stockNumber);
      return;
    }

    const imagesBtn = e.target.closest('.load__modal--images');
    if (imagesBtn) {
      openImageGalleryModal(scrapeModalData, imagesBtn.dataset.stockNumber);
    }
  });
}

function initScrapeDataTable() {
  const el = document.getElementById('scrape-data-table');
  if (!el || typeof VdpClientTable === 'undefined') return;

  if (scrapeDataTable) {
    scrapeDataTable.destroy();
    scrapeDataTable = null;
  }

  scrapeDataTable = new VdpClientTable(el, {
    stateSaveKey: 'scrape-data-table',
    pageLength: 10,
    onDraw: function () {
      // .total-images footer cell — class set in buildScrapeTableFoot() via SCRAPE_TABLE_COLUMNS.
      const api = this.api();
      const col = api.column('.total-images', { page: 'current' });
      const total = col.data().reduce(function (sum, val) {
        return sum + (parseInt(String(val).replace(/\D/g, ''), 10) || 0);
      }, 0);
      const footer = col.footer();
      if (footer) footer.textContent = 'Total: ' + total;
    },
  });
}

document.addEventListener('DOMContentLoaded', function () {
  initUnitModalDismiss();
  initScrapeModalDelegation();

  const loadBtn = document.querySelector('#load-scrape-data');
  if (loadBtn) loadBtn.addEventListener('click', loadData);
});
