/**
 * auth.js — Session cookie cho FastAPI.
 * Nếu trang đang chạy bằng amr_web_server.py cũ (API 404), tự vào legacy mode.
 */
(function () {
  const modal = document.getElementById('auth-modal');
  const form = document.getElementById('auth-login-form');
  const usernameInput = document.getElementById('auth-username');
  const passwordInput = document.getElementById('auth-password');
  const errorEl = document.getElementById('auth-error');
  const submitBtn = document.getElementById('btn-auth-login');
  const userBox = document.getElementById('auth-user-box');
  const userLabel = document.getElementById('auth-user-label');
  const logoutBtn = document.getElementById('btn-auth-logout');

  let currentUser = null;
  let apiAvailable = false;
  let readySent = false;

  function dispatchReady(detail) {
    if (!readySent) {
      readySent = true;
      window.dispatchEvent(new CustomEvent('amr-auth-ready', { detail }));
    }
    window.dispatchEvent(new CustomEvent('amr-auth-user', { detail }));
  }

  function lockApp(locked) {
    document.body.classList.toggle('auth-locked', !!locked);
  }

  function showLogin(message = '') {
    lockApp(true);
    modal?.classList.remove('hidden');
    modal?.setAttribute('aria-hidden', 'false');
    if (errorEl) errorEl.textContent = message;
    setTimeout(() => usernameInput?.focus(), 0);
  }

  function hideLogin() {
    lockApp(false);
    modal?.classList.add('hidden');
    modal?.setAttribute('aria-hidden', 'true');
    if (passwordInput) passwordInput.value = '';
    if (errorEl) errorEl.textContent = '';
  }

  function setUser(user) {
    currentUser = user;
    document.body.dataset.authRole = user?.role || 'legacy';
    if (userBox && userLabel) {
      if (user) {
        userLabel.textContent = user.username || user.role || 'user';
        userBox.classList.remove('hidden');
      } else {
        userLabel.textContent = '';
        userBox.classList.add('hidden');
      }
    }
  }

  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (
      options.body != null
      && !headers.has('Content-Type')
      && !(options.body instanceof FormData)
    ) {
      headers.set('Content-Type', 'application/json');
    }
    const response = await fetch(path, {
      ...options,
      headers,
      credentials: 'same-origin',
    });
    if (response.status === 401 && path !== '/api/auth/login') {
      currentUser = null;
      window.AmrRos?.disconnect?.();
      showLogin('Phiên đăng nhập đã hết hạn');
    }
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const body = await response.json();
        message = body.detail || message;
        if (Array.isArray(body.detail)) {
          message = body.detail.map((d) => d.msg || d).join('; ');
        }
      } catch {
        /* response không phải JSON */
      }
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    if (response.status === 204) return null;
    return response.json();
  }

  async function bootstrap() {
    try {
      const response = await fetch('/api/auth/me', {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });
      if (response.status === 404) {
        setUser(null);
        hideLogin();
        dispatchReady({ legacy: true });
        return;
      }
      apiAvailable = true;
      if (response.status === 401) {
        showLogin();
        return;
      }
      if (!response.ok) throw new Error(`API HTTP ${response.status}`);
      const user = await response.json();
      setUser(user);
      hideLogin();
      dispatchReady({ user });
    } catch (error) {
      // Giữ khả năng chạy server tĩnh cũ trong giai đoạn chuyển đổi.
      console.warn('AMR API chưa sẵn sàng, dùng legacy mode:', error);
      setUser(null);
      hideLogin();
      dispatchReady({ legacy: true });
    }
  }

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!apiAvailable) return;
    submitBtn.disabled = true;
    if (errorEl) errorEl.textContent = '';
    try {
      const user = await request('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          username: usernameInput.value.trim(),
          password: passwordInput.value,
        }),
      });
      setUser(user);
      hideLogin();
      dispatchReady({ user });
    } catch (error) {
      showLogin(error.message || 'Đăng nhập thất bại');
    } finally {
      submitBtn.disabled = false;
    }
  });

  logoutBtn?.addEventListener('click', async () => {
    if (!apiAvailable) return;
    try {
      await request('/api/auth/logout', { method: 'POST' });
    } catch (error) {
      console.warn('Logout:', error);
    }
    window.AmrRos?.disconnect?.();
    currentUser = null;
    readySent = false;
    if (userBox) userBox.classList.add('hidden');
    document.body.dataset.authRole = '';
    window.dispatchEvent(new CustomEvent('amr-auth-user', { detail: { user: null } }));
    showLogin('Đã đăng xuất');
  });

  window.AmrApi = {
    request,
    getUser: () => currentUser,
    isAvailable: () => apiAvailable,
    canWrite: () => ['admin', 'operator'].includes(currentUser?.role),
  };

  bootstrap();
})();
