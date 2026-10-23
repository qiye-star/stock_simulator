/**
 * 认证页与账户弹窗的渲染辅助（只操作 index.html 中已有节点，不生成结构）。
 * 文本一律 textContent，不拼接 HTML。
 */

/** 登录页 tab 切换：激活 .auth-tabs 内的按钮与对应表单。 */
export function setAuthTab(name, doc = document) {
  doc.querySelectorAll('.auth-tabs .tab-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === name);
  });
  doc.getElementById('login-form')?.classList.toggle('active', name === 'login');
  doc.getElementById('register-form')?.classList.toggle('active', name === 'register');
}

/**
 * @param {string} id 错误提示节点 id
 * @param {string} [message] 为空则清空
 * @param {Document} [doc]
 */
export function setErrorText(id, message = '', doc = document) {
  const el = doc.getElementById(id);
  if (el) el.textContent = message;
}

/** 清空登录 / 注册表单与错误提示。 */
export function clearAuthForms(doc = document) {
  for (const id of ['login-username', 'login-password', 'reg-username', 'reg-password', 'reg-confirm']) {
    const input = doc.getElementById(id);
    if (input instanceof HTMLInputElement) input.value = '';
  }
  setErrorText('login-error', '', doc);
  setErrorText('reg-error', '', doc);
}

/**
 * 修改密码弹窗：显示 / 隐藏错误（沿用 legacy 的 style.display 约定）。
 * @param {string} [message] 为空则隐藏
 * @param {Document} [doc]
 */
export function setChangePasswordError(message = '', doc = document) {
  const el = doc.getElementById('change-password-error');
  if (!el) return;
  el.textContent = message;
  el.style.display = message ? 'block' : 'none';
}

/** 打开修改密码弹窗前清空输入。 */
export function resetChangePasswordForm(doc = document) {
  for (const id of ['current-password', 'new-password', 'confirm-password']) {
    const input = doc.getElementById(id);
    if (input instanceof HTMLInputElement) input.value = '';
  }
  setChangePasswordError('', doc);
}

/** @param {string} id @param {Document} [doc] @returns {string} */
export function readValue(id, doc = document) {
  const el = doc.getElementById(id);
  return el instanceof HTMLInputElement ? el.value : '';
}
