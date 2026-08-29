/* Generic, dependency-free search + sort for admin list tables.
 * Search: <input class="admin-table-search" data-table-target="tableId">
 * Sort:   <th data-sort> inside <table id="tableId"> — click to toggle asc/desc.
 * Both work directly on the server-rendered rows, no data duplication.
 *
 * Exposed as window.initAdminTables(root) — called once on initial load, and
 * again by admin-nav.js after every AJAX content swap (always against freshly
 * inserted nodes, so there's no risk of double-binding a listener twice). */
(() => {
  'use strict';

  const parseCell = (text) => {
    const cleaned = text.replace(/[$,%]/g, '').trim();
    return cleaned !== '' && !Number.isNaN(Number(cleaned)) ? Number(cleaned) : null;
  };

  const initSearch = (input) => {
    const table = document.getElementById(input.dataset.tableTarget);
    if (!table) return;
    const tbody = table.tBodies[0];
    if (!tbody) return;
    input.addEventListener('input', () => {
      const needle = input.value.trim().toLowerCase();
      let visible = 0;
      Array.from(tbody.rows).forEach((row) => {
        const match = !needle || row.textContent.toLowerCase().includes(needle);
        row.hidden = !match;
        if (match) visible += 1;
      });
      const empty = table.closest('[data-table-wrap]')?.querySelector('.admin-table-empty');
      if (empty) empty.hidden = visible !== 0;
    });
  };

  const initSort = (th) => {
    const table = th.closest('table');
    const tbody = table?.tBodies[0];
    if (!tbody) return;
    th.setAttribute('role', 'button');
    th.classList.add('admin-sortable-th');
    th.addEventListener('click', () => {
      const cellIndex = th.cellIndex;
      const asc = th.dataset.sortDir !== 'asc';
      Array.from(table.querySelectorAll('th[data-sort]')).forEach((other) => {
        delete other.dataset.sortDir;
        other.querySelector('.admin-sort-icon')?.remove();
      });
      th.dataset.sortDir = asc ? 'asc' : 'desc';
      const icon = document.createElement('i');
      icon.className = `bi bi-caret-${asc ? 'up' : 'down'}-fill admin-sort-icon ms-1`;
      th.appendChild(icon);

      const rows = Array.from(tbody.rows);
      rows.sort((a, b) => {
        const aText = a.cells[cellIndex]?.textContent.trim() ?? '';
        const bText = b.cells[cellIndex]?.textContent.trim() ?? '';
        const aNum = parseCell(aText);
        const bNum = parseCell(bText);
        let cmp;
        if (aNum !== null && bNum !== null) {
          cmp = aNum - bNum;
        } else {
          cmp = aText.localeCompare(bText, undefined, { numeric: true, sensitivity: 'base' });
        }
        return asc ? cmp : -cmp;
      });
      rows.forEach((row) => tbody.appendChild(row));
    });
  };

  window.initAdminTables = (root = document) => {
    root.querySelectorAll('.admin-table-search').forEach(initSearch);
    root.querySelectorAll('th[data-sort]').forEach(initSort);
  };

  document.addEventListener('DOMContentLoaded', () => window.initAdminTables());
})();
