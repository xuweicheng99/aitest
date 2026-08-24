const form = document.querySelector('#runForm');
const button = document.querySelector('#runButton');
const loading = document.querySelector('#loading');
const errorBox = document.querySelector('#error');
const result = document.querySelector('#result');

async function checkHealth() {
  try {
    const response = await fetch('/api/health');
    document.querySelector('#modeBadge').textContent = response.ok ? '服务在线' : '服务异常';
  } catch {
    document.querySelector('#modeBadge').textContent = '服务离线';
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  errorBox.hidden = true;
  result.hidden = true;
  loading.hidden = false;
  button.disabled = true;
  try {
    const response = await fetch('/api/run', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        url: document.querySelector('#url').value.trim(),
        goal: document.querySelector('#goal').value.trim(),
        headless: document.querySelector('#headless').checked,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '执行失败');
    document.querySelector('#runId').textContent = data.run_id;
    document.querySelector('#finalUrl').textContent = data.result.final_url || '-';
    document.querySelector('#title').textContent = data.result.title || '-';
    const status = document.querySelector('#statusBadge');
    status.textContent = data.result.status === 'passed' ? '通过' : '失败';
    status.className = `badge ${data.result.status}`;
    document.querySelector('#code').textContent = data.generated_code;
    document.querySelector('#logs').textContent = JSON.stringify({
      error: data.result.error, console: data.result.console, page_errors: data.result.page_errors,
    }, null, 2);
    document.querySelector('#screenshotLink').href = data.result.artifacts.screenshot;
    document.querySelector('#traceLink').href = data.result.artifacts.trace;
    result.hidden = false;
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  } finally {
    loading.hidden = true;
    button.disabled = false;
  }
});

checkHealth();

