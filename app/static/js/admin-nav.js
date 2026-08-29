/* Partial-navigation router for the admin sidebar.
 *
 * This app renders full server-side pages — there's no SPA framework. A
 * normal sidebar click reloads the entire document, which destroys and
 * recreates the sidebar itself; that's what resets its scroll position and
 * reads as a flicker. This intercepts sidebar clicks, fetches just the
 * target page, and swaps only the #app-main-region content — the sidebar's
 * own DOM node is never touched, so the browser keeps its scroll position
 * for free, same as any other untouched part of the page.
 *
 * Everything else — forms, buttons, links inside the content area, direct
 * loads, hard refreshes — still does a normal full page load; the sidebar's
 * restore-on-load script (in base_admin.html) covers the scroll position
 * for those cases.
 */
(() => {
  'use strict';

  const CONTENT_SELECTOR = '#app-main-region';
  const SCRIPTS_SELECTOR = '#app-page-scripts';
  const sidebarWrapper = document.querySelector('.sidebar-wrapper');
  if (!sidebarWrapper) return;

  let inFlight = null;

  const isPlainLeftClick = (e) =>
    e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;

  const runScripts = (container) => {
    container.querySelectorAll('script').forEach((old) => {
      const fresh = document.createElement('script');
      for (const attr of old.attributes) fresh.setAttribute(attr.name, attr.value);
      fresh.textContent = old.textContent;
      old.replaceWith(fresh);
    });
  };

  // A page can add its own <head> assets (e.g. dashboard.html's ApexCharts
  // CSS) via {% block head %} — those never load unless we bring them over.
  const mergeHeadAssets = (fetchedDoc) => {
    const current = new Set(
      Array.from(document.head.querySelectorAll('link[rel="stylesheet"]'), (l) => l.href)
    );
    fetchedDoc.querySelectorAll('head link[rel="stylesheet"]').forEach((link) => {
      if (!current.has(link.href)) document.head.appendChild(link.cloneNode(true));
    });
  };

  // Sync each sidebar link's active state and badge count from the freshly
  // rendered page, without touching the sidebar's own DOM node/scroll.
  const syncSidebar = (fetchedDoc) => {
    fetchedDoc.querySelectorAll('.sidebar-wrapper a.nav-link[href]').forEach((freshLink) => {
      const href = freshLink.getAttribute('href');
      const current = sidebarWrapper.querySelector(`a.nav-link[href="${CSS.escape(href)}"]`);
      if (!current) return;
      current.className = freshLink.className;
      current.innerHTML = freshLink.innerHTML;
    });
  };

  const swapIn = (fetchedDoc) => {
    const freshContent = fetchedDoc.querySelector(CONTENT_SELECTOR);
    const currentContent = document.querySelector(CONTENT_SELECTOR);
    if (!freshContent || !currentContent) return false;

    mergeHeadAssets(fetchedDoc);
    document.title = fetchedDoc.title;
    currentContent.innerHTML = freshContent.innerHTML;
    runScripts(currentContent);

    const freshScripts = fetchedDoc.querySelector(SCRIPTS_SELECTOR);
    const currentScripts = document.querySelector(SCRIPTS_SELECTOR);
    if (freshScripts && currentScripts) {
      currentScripts.innerHTML = freshScripts.innerHTML;
      runScripts(currentScripts);
    }

    syncSidebar(fetchedDoc);
    window.initAdminTables?.(currentContent);
    window.scrollTo({ top: 0, behavior: 'instant' });
    return true;
  };

  const navigate = (url, { push }) => {
    inFlight?.abort();
    const controller = new AbortController();
    inFlight = controller;

    document.body.classList.add('admin-nav-loading');
    fetch(url, {
      headers: { Accept: 'text/html,application/xhtml+xml' },
      signal: controller.signal,
    })
      .then((res) => {
        if (!res.ok) throw new Error('bad status ' + res.status);
        return res.text();
      })
      .then((html) => {
        const fetchedDoc = new DOMParser().parseFromString(html, 'text/html');
        if (!swapIn(fetchedDoc)) throw new Error('unexpected page shape');
        if (push) history.pushState({ adminNav: true }, '', url);
      })
      .catch((err) => {
        if (err.name === 'AbortError') return; // superseded by a newer click
        // Anything else unexpected (network error, redirected to a login
        // page, a response missing the expected regions, ...) — fall back to
        // a real navigation rather than leaving a broken half-swapped page.
        window.location.href = url;
      })
      .finally(() => {
        if (inFlight === controller) {
          document.body.classList.remove('admin-nav-loading');
          inFlight = null;
        }
      });
  };

  sidebarWrapper.addEventListener('click', (e) => {
    const link = e.target.closest('a.nav-link[href]');
    if (!link || !isPlainLeftClick(e) || link.target === '_blank') return;

    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin) return;
    if (url.href === window.location.href) { e.preventDefault(); return; }

    e.preventDefault();
    navigate(url.href, { push: true });
  });

  window.addEventListener('popstate', () => {
    navigate(window.location.href, { push: false });
  });
})();
