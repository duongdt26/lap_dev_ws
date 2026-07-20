/**
 * role-tabs.js — Switch Operator / Setter role panels
 */

(function () {
  const tabs = document.querySelectorAll('.role-tab');
  const sections = document.querySelectorAll('.panel-section[data-role]');

  function setRole(role) {
    document.body.dataset.role = role;
    tabs.forEach((tab) => {
      const active = tab.dataset.role === role;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });

    sections.forEach((sec) => {
      const roles = (sec.dataset.role || '').split(/\s+/);
      const show = roles.includes('both') || roles.includes(role);
      sec.classList.toggle('hidden', !show);
    });
    window.dispatchEvent(
      new CustomEvent('amr-role-changed', { detail: { role } })
    );
  }

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => setRole(tab.dataset.role));
  });

  // Luôn vào màn hình Vận hành trước để tránh lộ thao tác cấu hình nguy hiểm.
  setRole('operator');
})();
