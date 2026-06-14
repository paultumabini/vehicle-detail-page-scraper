/*
  newscrape.js — New Scrape form helpers (targetsite_form.html).

  Account pre-select (from Accounts + button):
    1. SiteCreateView.get_initial() sets site_name from ?account=<pk>
    2. preselectAccountFromUrl() runs after /account-provider-json/ loads
    3. fillAccountFields() copies site_url, site_id, web_provider from account data

  Site URL → domain name (site id):
    extractDomainFromSiteUrl() → registrable name only, no TLD (example.com.au → example).
    initSiteUrlDomainSync() fills #id_site_id as the operator types.

  Web Provider combobox:
    Replaces native <datalist> — dropdown is DOM-owned so main.css scrollbars apply.

  Checkbox toolbar:
    initScrapeCheckboxToolbar() — All/None buttons for scrape-item fields (.vdp-scrape-item-cb)
*/

async function fetchApi(url) {
  const res = await fetch(url);
  return await res.json();
}

/** Site id label from a URL — scheme/path/www stripped, TLD dropped (TargetSite.site_id PK).

  Examples:
    https://www.palladinomazda.ca/  → palladinomazda
    https://www.example.com.au/     → example
    https://www.google.com          → google
    https://shop.dealer.com/inventory → dealer
*/
function extractDomainFromSiteUrl(rawUrl) {
  const trimmed = (rawUrl || '').trim();
  if (!trimmed) return '';

  let hostname = '';
  try {
    const withScheme = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
    hostname = new URL(withScheme).hostname;
  } catch {
    // Partial URL while typing — best-effort until input is parseable.
    hostname = trimmed.replace(/^https?:\/\//i, '').split(/[/?#]/)[0];
  }

  return stripSiteIdFromHostname(hostname);
}

/** Second-level labels that precede a country code (com.au, co.uk, net.nz, …). */
const COMPOUND_TLD_LABELS = new Set([
  'com',
  'net',
  'org',
  'edu',
  'gov',
  'co',
  'ac',
  'asn',
  'id',
  'ne',
  'or',
  'web',
]);

/** Drop www. and TLD — keep registrable name; handles simple (.ca) and compound (.com.au) TLDs. */
function stripSiteIdFromHostname(hostname) {
  const host = (hostname || '').replace(/^www\./i, '').trim();
  const parts = host.split('.').filter(Boolean);
  if (!parts.length) return '';
  if (parts.length === 1) return parts[0];

  const tld = parts[parts.length - 1].toLowerCase();
  const sld = parts[parts.length - 2].toLowerCase();
  const compoundTld = tld.length === 2 && COMPOUND_TLD_LABELS.has(sld) && parts.length >= 3;

  if (compoundTld) {
    return parts[parts.length - 3];
  }
  return parts[parts.length - 2];
}

/** Auto-fill Domain Name from Site URL on input/change (manual entry or after account pre-fill). */
function initSiteUrlDomainSync(form) {
  const siteUrlInput = form.elements.site_url;
  const domainInput = form.elements.id_site_id;
  if (!siteUrlInput || !domainInput) return;

  const syncDomain = () => {
    const domain = extractDomainFromSiteUrl(siteUrlInput.value);
    if (domain) {
      domainInput.value = domain;
    }
  };

  siteUrlInput.addEventListener('input', syncDomain);
  siteUrlInput.addEventListener('change', syncDomain);
}

/** Styled combobox for #id_web_provider — filter, pick, or type a new provider. */
function initProviderCombobox(input, providerNames) {
  if (!input || input.dataset.comboboxInit) return;
  input.dataset.comboboxInit = '1';
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-expanded', 'false');

  // Wrap input + menu — built in JS so the Django widget stays a plain TextInput.
  const wrap = document.createElement('div');
  wrap.className = 'vdp-combobox';
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);

  const menu = document.createElement('ul');
  menu.className = 'vdp-combobox__menu';
  menu.id = 'web-provider-menu';
  menu.setAttribute('role', 'listbox');
  menu.hidden = true;
  input.setAttribute('aria-controls', menu.id);
  wrap.appendChild(menu);

  let activeIndex = -1;

  function filterOptions(query) {
    const q = query.trim().toLowerCase();
    if (!q) return providerNames;
    return providerNames.filter(name => name.toLowerCase().includes(q));
  }

  function closeMenu() {
    menu.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    activeIndex = -1;
    menu.querySelectorAll('.vdp-combobox__option.is-active').forEach(el => {
      el.classList.remove('is-active');
    });
  }

  function selectOption(name) {
    input.value = name;
    closeMenu();
  }

  function renderOptions(items) {
    menu.innerHTML = '';
    activeIndex = -1;

    if (!items.length) {
      closeMenu();
      return;
    }

    items.forEach(name => {
      const option = document.createElement('li');
      option.className = 'vdp-combobox__option';
      option.setAttribute('role', 'option');
      option.textContent = name;
      // mousedown (not click) — fires before input blur so the menu stays open long enough to select.
      option.addEventListener('mousedown', event => {
        event.preventDefault();
        selectOption(name);
      });
      menu.appendChild(option);
    });

    menu.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  }

  function openMenu() {
    renderOptions(filterOptions(input.value));
  }

  function setActiveOption(options) {
    options.forEach((el, index) => {
      el.classList.toggle('is-active', index === activeIndex);
      if (index === activeIndex) {
        el.scrollIntoView({ block: 'nearest' });
      }
    });
  }

  input.addEventListener('focus', openMenu);
  input.addEventListener('input', openMenu);
  // Delay close so mousedown on an option can run before the menu is torn down.
  input.addEventListener('blur', () => {
    window.setTimeout(closeMenu, 150);
  });

  input.addEventListener('keydown', event => {
    const options = menu.querySelectorAll('.vdp-combobox__option');

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (menu.hidden) openMenu();
      activeIndex = Math.min(activeIndex + 1, options.length - 1);
      setActiveOption(options);
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (menu.hidden) openMenu();
      activeIndex = Math.max(activeIndex - 1, 0);
      setActiveOption(options);
      return;
    }

    if (event.key === 'Enter' && !menu.hidden && activeIndex >= 0) {
      event.preventDefault();
      selectOption(options[activeIndex].textContent);
      return;
    }

    if (event.key === 'Escape') {
      closeMenu();
    }
  });
}

// Name kept for targetsite_form.html inline call — loads /web-provider-json/ then mounts combobox.
async function addProviderDataList(func, url1, url2) {
  const providerList = await fetchApi(url1);
  const providerNames = [...new Set(providerList.map(p => p.name))].sort((a, b) =>
    a > b ? 1 : -1,
  );
  initProviderCombobox(document.getElementById('id_web_provider'), providerNames);
  func(providerList, url2);
}

/** Mirror site_name change handler — used for manual select and ?account= deep link. */
function fillAccountFields(form, providers, accountList, accountId) {
  if (!accountId) return;

  accountList.forEach(({ account_id, site_url, web_provider_id }) => {
    if (account_id.toString() === accountId.toString()) {
      form.elements.site_url.value = site_url || '';
      // Same hostname logic as initSiteUrlDomainSync — replaces legacy regex that stripped TLD.
      form.elements.id_site_id.value = extractDomainFromSiteUrl(site_url);
      providers.forEach(({ id, name }) => {
        if (id === web_provider_id) form.elements.web_provider.value = name;
      });
    }
  });
}

/** Read ?account= from URL set by account_row.html + button href. */
function preselectAccountFromUrl(form, providers, accountList) {
  const accountId = new URLSearchParams(window.location.search).get('account');
  if (!accountId || !form.elements.site_name) return;

  form.elements.site_name.value = accountId;
  fillAccountFields(form, providers, accountList, accountId);
}

// populate other account info
async function addAccountList(providers, url) {
  const accountList = await fetchApi(url);
  const form = document.querySelector('form');

  form.elements.site_name.addEventListener('change', function () {
    fillAccountFields(form, providers, accountList, this.value);

    if (!form.elements.site_name.selectedIndex) {
      form.elements.site_url.value = '';
      form.elements.id_site_id.value = '';
      form.elements.web_provider.value = '';
    }
  });

  preselectAccountFromUrl(form, providers, accountList);
}

/*
  All / None toolbar on targetsite_form.html (replaces legacy fa-check-square icons).
  Targets .vdp-scrape-item-cb only — not any other checkboxes on the page.
*/
function initScrapeCheckboxToolbar() {
  const form = document.querySelector('.vdp-scrape-form');
  if (!form) return;

  const checkboxes = form.querySelectorAll('.vdp-scrape-item-cb');
  const checkAll = form.querySelector('[data-check-all]');
  const uncheckAll = form.querySelector('[data-uncheck-all]');

  if (checkAll) {
    checkAll.addEventListener('click', () => {
      checkboxes.forEach(cb => {
        cb.checked = true;
      });
    });
  }

  if (uncheckAll) {
    uncheckAll.addEventListener('click', () => {
      checkboxes.forEach(cb => {
        cb.checked = false;
      });
    });
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initScrapeCheckboxToolbar();
  // Wire domain sync on load — does not depend on /account-provider-json/ finishing.
  const form = document.querySelector('.vdp-scrape-form');
  if (form) {
    initSiteUrlDomainSync(form);
  }
});
