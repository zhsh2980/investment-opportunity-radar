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
        });

        if (response.ok) {
            // 登录成功，跳转到首页
            window.location.href = '/';
        } else {
            const data = await response.json();
            alert(data.detail || '登录失败，请检查用户名和密码');
        }
    } catch (error) {
        console.error('登录错误:', error);
        alert('网络错误，请稍后重试');
    } finally {
        submitBtn.innerHTML = originalText;
        submitBtn.disabled = false;
    }
}
