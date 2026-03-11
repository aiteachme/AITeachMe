const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const statusEl = document.getElementById("status");
const checkBtn = document.getElementById("check-btn");

async function checkHealth() {
  statusEl.textContent = "正在请求...";
  try {
    const res = await fetch(`${API_URL}/api/health`);
    const data = await res.json();
    statusEl.textContent = `✅ 后端响应: ${data.message}`;
    statusEl.style.color = "#22c55e";
  } catch (err) {
    statusEl.textContent = `❌ 连接失败: ${err.message}`;
    statusEl.style.color = "#ef4444";
  }
}

checkBtn.addEventListener("click", checkHealth);

// 页面加载时自动检查一次
checkHealth();
