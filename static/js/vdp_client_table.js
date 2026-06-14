'use strict';

/*
  vdp_client_table.js — lightweight client-side table (no jQuery / DataTables).

  Used for target sites and scrape detail pages where all rows are already in the DOM.
  Injects toolbar/footer chrome; persists page/search/sort in localStorage.

  Row delete on target sites still uses full-page POST + redirect — not auto-synced;
  call removeRow() here if inline delete without reload is added later.
*/

class VdpClientTable {
  constructor(tableEl, options = {}) {
    if (!tableEl) return null;
    if (tableEl._vdpTable) {
      tableEl._vdpTable.destroy(false);
    }

    this.table = tableEl;
    this.tbody = tableEl.querySelector('tbody');
    this.tfoot = tableEl.querySelector('tfoot');
    this.options = {
      pageLength: options.pageLength ?? 10,
      lengthMenu: options.lengthMenu ?? [10, 25, 50, 100],
      stateSaveKey: options.stateSaveKey ?? tableEl.id ?? 'vdp-table',
      nonSortableColumns: new Set(options.nonSortableColumns ?? []),
      exactColumnFilters: new Set(options.exactColumnFilters ?? []),
      initialColumnFilters: options.initialColumnFilters ?? {},
      onDraw: options.onDraw ?? options.footerCallback ?? null,
    };

    this._pageLength = this.options.pageLength;
    this.allRows = Array.from(this.tbody.querySelectorAll('tr')).map(function (tr) {
      return tr.cloneNode(true);
    });
    this.columnSearches = {};
    this.globalSearch = '';
    this.sortCol = null;
    this.sortDir = 'asc';
    this.pageIndex = 0;
    this.filteredRows = [];

    Object.entries(this.options.initialColumnFilters).forEach(
      function (entry) {
        const col = entry[0];
        const val = entry[1];
        if (val && !this.columnSearches[col]) {
          this.columnSearches[col] = val;
        }
      }.bind(this),
    );

    tableEl._vdpTable = this;
    this.loadState();
    this.ensureChrome();
    this.bindChromeEvents();
    this.bindHeaderSort();
    this.draw();
  }

  column(index) {
    const self = this;
    return {
      search: function (value) {
        self.columnSearches[index] = value ?? '';
        return self._chainApi();
      },
    };
  }

  _chainApi() {
    const self = this;
    return {
      draw: function () {
        self.draw();
      },
    };
  }

  api() {
    const self = this;
    return {
      draw: function () {
        self.draw();
      },
      column: function (selector, opts) {
        const idx = self.getColumnIndex(selector);
        return {
          data: function () {
            const rows =
              opts && opts.page === 'current'
                ? self.getCurrentPageRows()
                : self.filteredRows;
            return rows.map(function (row) {
              return self.getCellText(row, idx);
            });
          },
          footer: function () {
            return self.getFooterCell(idx);
          },
        };
      },
    };
  }

  getColumnIndex(selector) {
    if (typeof selector === 'number') return selector;
    if (String(selector).charAt(0) === '.') {
      const cls = String(selector).slice(1);
      const headers = this.table.querySelectorAll('thead th');
      return Array.from(headers).findIndex(function (th) {
        return th.classList.contains(cls);
      });
    }
    return parseInt(selector, 10);
  }

  getCellText(row, colIndex) {
    const cell = row.cells[colIndex];
    if (!cell) return '';
    const clone = cell.cloneNode(true);
    clone.querySelectorAll('.dt-val').forEach(function (el) {
      el.remove();
    });
    return clone.textContent.trim();
  }

  getColumnFilterValue(row, colIndex) {
    const cell = row.cells[colIndex];
    if (!cell) return '';
    const dtVal = cell.querySelector('.dt-val');
    if (dtVal) return dtVal.textContent.trim();
    return cell.textContent.trim();
  }

  getFooterCell(colIndex) {
    if (!this.tfoot || !this.tfoot.rows.length) return null;
    return this.tfoot.rows[0].cells[colIndex] || null;
  }

  getCurrentPageRows() {
    const start = this.pageIndex * this._pageLength;
    return this.filteredRows.slice(start, start + this._pageLength);
  }

  destroy(restoreRows) {
    if (restoreRows !== false) {
      this.tbody.innerHTML = '';
      this.allRows.forEach(
        function (row) {
          this.tbody.appendChild(row.cloneNode(true));
        }.bind(this),
      );
    }
    if (this.panel && this.panel.parentNode) {
      this.panel.parentNode.removeChild(this.panel);
    }
    delete this.table._vdpTable;
  }

  loadState() {
    try {
      const raw = localStorage.getItem('vdp-table:' + this.options.stateSaveKey);
      if (!raw) return;
      const state = JSON.parse(raw);
      if (state.pageLength) this._pageLength = state.pageLength;
      if (state.pageIndex != null) this.pageIndex = state.pageIndex;
      if (state.globalSearch) this.globalSearch = state.globalSearch;
      if (state.sortCol != null) this.sortCol = state.sortCol;
      if (state.sortDir) this.sortDir = state.sortDir;
    } catch (_err) {
      /* ignore corrupt state */
    }
  }

  saveState() {
    localStorage.setItem(
      'vdp-table:' + this.options.stateSaveKey,
      JSON.stringify({
        pageLength: this._pageLength,
        pageIndex: this.pageIndex,
        globalSearch: this.globalSearch,
        sortCol: this.sortCol,
        sortDir: this.sortDir,
      }),
    );
  }

  ensureChrome() {
    if (this.panel) return;

    const panel = document.createElement('div');
    panel.className = 'vdp-table-panel';

    const toolbar = document.createElement('div');
    toolbar.className = 'vdp-table-toolbar';
    toolbar.innerHTML =
      '<label class="vdp-table-length">' +
      '<select class="vdp-table-length-select" aria-label="Rows per page"></select>' +
      '<span> per page</span></label>' +
      '<label class="vdp-table-search">' +
      '<input type="search" class="vdp-table-search-input" placeholder="Search here" aria-label="Search table">' +
      '</label>';

    const footer = document.createElement('div');
    footer.className = 'vdp-table-footer';
    footer.innerHTML =
      '<div class="vdp-table-info"></div>' +
      '<nav class="vdp-table-paging" aria-label="Table pagination"></nav>';

    const scrollWrap = document.createElement('div');
    scrollWrap.className = 'vdp-table-scroll';
    // Table-only scroll — toolbar/footer remain full-width (see .vdp-table-scroll in main.css).

    panel.appendChild(toolbar);
    this.table.parentNode.insertBefore(panel, this.table);
    scrollWrap.appendChild(this.table);
    panel.appendChild(scrollWrap);
    panel.appendChild(footer);

    this.panel = panel;
    this.lengthSelect = toolbar.querySelector('.vdp-table-length-select');
    this.searchInput = toolbar.querySelector('.vdp-table-search-input');
    this.infoEl = footer.querySelector('.vdp-table-info');
    this.pagingEl = footer.querySelector('.vdp-table-paging');

    this.lengthSelect.innerHTML = this.options.lengthMenu
      .map(function (n) {
        return '<option value="' + n + '">' + n + '</option>';
      })
      .join('');
    this.lengthSelect.value = String(this._pageLength);
    this.searchInput.value = this.globalSearch;
  }

  bindChromeEvents() {
    const self = this;
    this.lengthSelect.addEventListener('change', function () {
      self._pageLength = parseInt(this.value, 10) || self._pageLength;
      self.pageIndex = 0;
      self.draw();
    });

    let searchTimer;
    this.searchInput.addEventListener('input', function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        self.globalSearch = self.searchInput.value.trim();
        self.pageIndex = 0;
        self.draw();
      }, 250);
    });
  }

  bindHeaderSort() {
    const self = this;
    const headers = this.table.querySelectorAll('thead th');
    headers.forEach(function (th, index) {
      if (self.options.nonSortableColumns.has(index)) return;
      th.classList.add('vdp-sortable');
      th.addEventListener('click', function () {
        if (self.sortCol === index) {
          self.sortDir = self.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
          self.sortCol = index;
          self.sortDir = 'asc';
        }
        self.draw();
      });
    });
  }

  compareRows(a, b, colIndex, dir) {
    const av = this.getCellText(a, colIndex);
    const bv = this.getCellText(b, colIndex);
    const an = parseFloat(av.replace(/[^\d.-]/g, ''));
    const bn = parseFloat(bv.replace(/[^\d.-]/g, ''));
    let cmp;
    if (!Number.isNaN(an) && !Number.isNaN(bn) && av !== '' && bv !== '') {
      cmp = an - bn;
    } else {
      cmp = av.localeCompare(bv, undefined, { sensitivity: 'base' });
    }
    return dir === 'desc' ? -cmp : cmp;
  }

  draw() {
    let rows = this.allRows.slice();

    if (this.globalSearch) {
      const q = this.globalSearch.toLowerCase();
      rows = rows.filter(function (row) {
        return row.textContent.toLowerCase().includes(q);
      });
    }

    Object.keys(this.columnSearches).forEach(
      function (col) {
        const val = this.columnSearches[col];
        if (!val) return;
        const c = parseInt(col, 10);
        const exact = this.options.exactColumnFilters.has(c);
        rows = rows.filter(
          function (row) {
            const haystack = this.getColumnFilterValue(row, c);
            if (exact) {
              return haystack === val;
            }
            return haystack.toLowerCase().includes(val.toLowerCase());
          }.bind(this),
        );
      }.bind(this),
    );

    if (this.sortCol != null) {
      const col = this.sortCol;
      const dir = this.sortDir;
      rows.sort(
        function (a, b) {
          return this.compareRows(a, b, col, dir);
        }.bind(this),
      );
    }

    this.filteredRows = rows;
    const total = rows.length;
    const pages = Math.max(Math.ceil(total / this._pageLength), 1);
    if (this.pageIndex >= pages) this.pageIndex = pages - 1;

    const start = this.pageIndex * this._pageLength;
    const pageRows = rows.slice(start, start + this._pageLength);

    this.tbody.innerHTML = '';
    pageRows.forEach(
      function (row) {
        this.tbody.appendChild(row.cloneNode(true));
      }.bind(this),
    );

    this.updateChrome(total, start, pageRows.length, pages);

    if (this.options.onDraw) {
      this.options.onDraw.call({ api: this.api.bind(this) });
    }

    this.saveState();
  }

  updateChrome(total, start, shown, pages) {
    if (total === 0) {
      this.infoEl.textContent = 'No matching entries';
    } else {
      this.infoEl.textContent =
        'Showing ' +
        (start + 1) +
        '–' +
        (start + shown) +
        ' of ' +
        total;
    }

    this.renderPaging(pages);
    this.updateSortIndicators();
  }

  updateSortIndicators() {
    const headers = this.table.querySelectorAll('thead th');
    headers.forEach(
      function (th, index) {
        th.classList.remove('vdp-sorted-asc', 'vdp-sorted-desc');
        if (index === this.sortCol) {
          th.classList.add(this.sortDir === 'asc' ? 'vdp-sorted-asc' : 'vdp-sorted-desc');
        }
      }.bind(this),
    );
  }

  renderPaging(pages) {
    const self = this;
    const current = this.pageIndex;
    this.pagingEl.innerHTML = '';

    function addButton(label, page, disabled, isCurrent) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'vdp-paging-btn';
      btn.textContent = label;
      if (disabled) btn.disabled = true;
      if (isCurrent) btn.classList.add('current');
      if (!disabled && !isCurrent) {
        btn.addEventListener('click', function () {
          self.pageIndex = page;
          self.draw();
        });
      }
      self.pagingEl.appendChild(btn);
    }

    addButton('‹', current - 1, current === 0, false);

    const windowSize = 5;
    let startPage = Math.max(current - Math.floor(windowSize / 2), 0);
    let endPage = Math.min(startPage + windowSize, pages);
    startPage = Math.max(endPage - windowSize, 0);

    for (let p = startPage; p < endPage; p += 1) {
      addButton(String(p + 1), p, false, p === current);
    }

    addButton('›', current + 1, current >= pages - 1, false);
  }
}

window.VdpClientTable = VdpClientTable;
