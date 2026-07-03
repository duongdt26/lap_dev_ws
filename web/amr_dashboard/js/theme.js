/**
 * theme.js — Chế độ sáng / tối, lưu localStorage
 */

(function () {
  const STORAGE_KEY = 'amr-theme';
  const btn = document.getElementById('btn-theme-toggle');

  function getTheme() {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  }

  function applyTheme(theme) {
    if (theme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
      btn.setAttribute('aria-label', 'Chế độ tối');
      btn.title = 'Chuyển sang chế độ tối';
    } else {
      document.documentElement.removeAttribute('data-theme');
      btn.setAttribute('aria-label', 'Chế độ sáng');
      btn.title = 'Chuyển sang chế độ sáng';
    }
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {}
  }

  btn.addEventListener('click', () => {
    applyTheme(getTheme() === 'light' ? 'dark' : 'light');
  });

  applyTheme(getTheme());
})();
