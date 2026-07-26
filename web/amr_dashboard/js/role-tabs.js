/**
 * role-tabs.js — Switch Operator / Setter panels theo tài khoản đăng nhập
 *
 * admin   → chỉ Setter (setup)
 * operator → chỉ Operator
 * legacy / chưa login API → cả hai tab
 */

(function () {
  const tabs = document.querySelectorAll('.role-tab');
  const sections = document.querySelectorAll('.panel-section[data-role]');
  const tabOperator = document.querySelector('.role-tab[data-role="operator"]');
  const tabSetter = document.querySelector('.role-tab[data-role="setup"]');

  let lockedUiRole = null; // 'operator' | 'setup' | null (cho phép chuyển tab)

  function setRole(role) {
    if (lockedUiRole && role !== lockedUiRole) return;

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

    document.body.dataset.uiRole = role;
    window.dispatchEvent(new CustomEvent('amr-ui-role', { detail: { role } }));
  }

  function applyAuthUser(user, legacy = false) {
    const authRole = legacy ? 'legacy' : (user?.role || '');

    if (authRole === 'admin') {
      lockedUiRole = 'setup';
      tabOperator?.classList.add('hidden');
      tabSetter?.classList.remove('hidden');
      setRole('setup');
      return;
    }

    if (authRole === 'operator') {
      lockedUiRole = 'operator';
      tabSetter?.classList.add('hidden');
      tabOperator?.classList.remove('hidden');
      setRole('operator');
      return;
    }

    // legacy / viewer / unknown — hiện cả hai, mặc định Operator
    lockedUiRole = null;
    tabOperator?.classList.remove('hidden');
    tabSetter?.classList.remove('hidden');
    setRole('operator');
  }

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => setRole(tab.dataset.role));
  });

  window.addEventListener('amr-auth-ready', (event) => {
    applyAuthUser(event.detail?.user, !!event.detail?.legacy);
  });

  window.addEventListener('amr-auth-user', (event) => {
    applyAuthUser(event.detail?.user, !!event.detail?.legacy);
  });

  // Mặc định trước khi auth sẵn sàng
  setRole('operator');

  window.AmrRoleTabs = { setRole, applyAuthUser };
})();
