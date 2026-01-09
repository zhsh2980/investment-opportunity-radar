/**
 * 投资机会雷达 - 前端脚本
 */

// 页面加载完成后执行
document.addEventListener('DOMContentLoaded', function () {
    console.log('📡 投资机会雷达已加载');

    // 登录表单处理（如果存在）
    const loginForm = document.querySelector('.login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
    }
});

/**
 * 切换密码显示/隐藏
 */
function togglePassword() {
    const passwordInput = document.getElementById('password');
    const eyeIcon = document.querySelector('.eye-icon');
    const eyeOffIcon = document.querySelector('.eye-off-icon');

    if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        eyeIcon.style.display = 'none';
        eyeOffIcon.style.display = 'block';
    } else {
        passwordInput.type = 'password';
        eyeIcon.style.display = 'block';
        eyeOffIcon.style.display = 'none';
    }
}

/**
 * 处理登录表单提交
 */
async function handleLogin(event) {
    event.preventDefault();

    const form = event.target;
    const submitBtn = form.querySelector('.login-btn');
    const originalText = submitBtn.innerHTML;

    // 显示加载状态
    submitBtn.innerHTML = '<span>登录中...</span>';
    submitBtn.disabled = true;

    try {
        const formData = new FormData(form);
        const response = await fetch(form.action, {
            method: 'POST',
            body: formData,
            redirect: 'manual', // 不自动跟随重定向
        });

        // 303 重定向表示登录成功
        if (response.type === 'opaqueredirect' || response.status === 303 || response.status === 302) {
            window.location.href = '/';
            return;
        }

        // 200 也可能表示成功（如果后端返回 JSON）
        if (response.ok) {
            window.location.href = '/';
            return;
        }

        // 处理错误
        if (response.status === 401 || response.status === 403) {
            const data = await response.json().catch(() => ({}));
            alert(data.detail || '用户名或密码错误');
        } else {
            const data = await response.json().catch(() => ({}));
            alert(data.detail || '登录失败，请稍后重试');
        }
    } catch (error) {
        console.error('登录错误:', error);
        alert('网络错误，请稍后重试');
    } finally {
        submitBtn.innerHTML = originalText;
        submitBtn.disabled = false;
    }
}

/**
 * 切换移动端导航菜单
 * 挂载到 window 对象以确保 onclick 属性可以访问
 */
window.toggleMobileMenu = function () {
    const menu = document.getElementById('mobileMenu');
    if (menu) {
        menu.classList.toggle('hidden');
    }
};
