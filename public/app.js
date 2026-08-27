const state = { plan: null };
const byId = (id) => document.getElementById(id);
const errorBox = byId('error');

function setBusy(active, text = '正在处理') {
  byId('busy').hidden = !active;
  byId('busyText').textContent = text;
  document.querySelectorAll('button').forEach((button) => { button.disabled = active; });
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  window.setTimeout(() => { errorBox.hidden = true; }, 7000);
}

async function responseJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((item) => item.msg).join('；') : data.detail;
    throw new Error(detail || '请求执行失败');
  }
  return data;
}

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((item) => item.classList.toggle('active', item === tab));
    byId('requirementsView').hidden = tab.dataset.view !== 'requirements';
    byId('singleView').hidden = tab.dataset.view !== 'single';
  });
});

async function checkHealth() {
  try {
    const data = await responseJson(await fetch('/api/health'));
    byId('modeBadge').textContent = data.agent_mode === 'llm' ? `AI 模式 · ${data.model}` : '模拟模式';
  } catch { byId('modeBadge').textContent = '服务离线'; }
}

byId('planForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  errorBox.hidden = true;
  byId('planResults').hidden = true;
  const form = new FormData();
  form.append('requirements_text', byId('requirementsText').value.trim());
  form.append('max_cases', byId('maxCases').value);
  const file = byId('requirementFile').files[0];
  if (file) form.append('document', file);
  setBusy(true, '正在解析需求并生成用例');
  try {
    state.plan = await responseJson(await fetch('/api/plans/generate', { method: 'POST', body: form }));
    renderPlan();
  } catch (error) { showError(error.message); } finally { setBusy(false); }
});

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function field(labelText, control) {
  const wrapper = createElement('label', 'field');
  wrapper.append(createElement('span', '', labelText), control);
  return wrapper;
}

function selectControl(options, value, onChange) {
  const select = document.createElement('select');
  options.forEach(([key, label]) => {
    const option = document.createElement('option');
    option.value = key; option.textContent = label; option.selected = key === value; select.append(option);
  });
  select.addEventListener('change', () => onChange(select.value));
  return select;
}

function textArea(value, onChange, rows = 4) {
  const area = document.createElement('textarea');
  area.rows = rows; area.value = value; area.addEventListener('input', () => onChange(area.value));
  return area;
}

function lines(value) { return value.split('\n').map((item) => item.trim()).filter(Boolean); }

function renderPlan() {
  const plan = state.plan;
  byId('planName').textContent = plan.name;
  byId('planSummary').textContent = plan.requirements_summary;
  byId('planReview').hidden = false;
  const assumptions = byId('assumptions');
  assumptions.hidden = !plan.assumptions.length;
  assumptions.textContent = plan.assumptions.length ? `执行前提：${plan.assumptions.join('；')}` : '';
  const enabled = plan.cases.filter((item) => item.enabled).length;
  byId('caseCount').textContent = `${plan.cases.length} 条用例 · 已选 ${enabled} 条`;
  byId('selectAllCases').checked = enabled === plan.cases.length;
  byId('selectAllCases').indeterminate = enabled > 0 && enabled < plan.cases.length;
  byId('caseList').replaceChildren(...plan.cases.map(renderCase));
  byId('planReview').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderCase(testCase) {
  const card = createElement('article', `case-card${testCase.enabled ? '' : ' disabled'}`);
  const head = createElement('div', 'case-head');
  const enabled = document.createElement('input');
  enabled.type = 'checkbox'; enabled.checked = testCase.enabled; enabled.title = '选择用例';
  enabled.addEventListener('change', () => { testCase.enabled = enabled.checked; renderPlan(); });
  const title = document.createElement('input');
  title.className = 'case-title'; title.value = testCase.title; title.setAttribute('aria-label', '用例标题');
  title.addEventListener('input', () => { testCase.title = title.value; });
  const priority = selectControl([['P0','P0'],['P1','P1'],['P2','P2'],['P3','P3']], testCase.priority, (value) => { testCase.priority = value; });
  const type = selectControl([['positive','正向'],['negative','反向'],['boundary','边界'],['permission','权限'],['state','状态']], testCase.case_type, (value) => { testCase.case_type = value; });
  const remove = createElement('button', 'danger-icon', '×');
  remove.type = 'button'; remove.title = '删除用例'; remove.setAttribute('aria-label', '删除用例');
  remove.addEventListener('click', () => { state.plan.cases = state.plan.cases.filter((item) => item !== testCase); renumberCases(); renderPlan(); });
  head.append(enabled, createElement('span', 'case-id', testCase.case_id), title, priority, type, remove);
  const body = createElement('div', 'case-body');
  body.append(
    field('前置条件（每行一条）', textArea(testCase.preconditions.join('\n'), (value) => { testCase.preconditions = lines(value); }, 2)),
    field('操作步骤（每行一步）', textArea(testCase.steps.join('\n'), (value) => { testCase.steps = lines(value); })),
    field('预期结果（每行一条）', textArea(testCase.expected_results.join('\n'), (value) => { testCase.expected_results = lines(value); })),
  );
  card.append(head, body);
  return card;
}

function renumberCases() { state.plan.cases.forEach((item, index) => { item.case_id = `TC-${String(index + 1).padStart(3, '0')}`; }); }

byId('selectAllCases').addEventListener('change', (event) => {
  state.plan.cases.forEach((item) => { item.enabled = event.target.checked; }); renderPlan();
});

byId('addCaseButton').addEventListener('click', () => {
  state.plan.cases.push({ case_id: '', title: '新测试用例', preconditions: [], steps: ['请填写操作步骤'], expected_results: ['请填写可验证的预期结果'], priority: 'P1', case_type: 'positive', source_refs: [], enabled: true });
  renumberCases(); renderPlan();
});

byId('executePlanButton').addEventListener('click', async () => {
  if (!state.plan.cases.some((item) => item.enabled)) return showError('至少选择一条测试用例');
  if (state.plan.cases.some((item) => !item.title.trim() || !item.steps.length || !item.expected_results.length)) return showError('用例标题、操作步骤和预期结果不能为空');
  setBusy(true, '正在逐条执行已选测试用例');
  byId('planResults').hidden = true;
  try {
    const response = await fetch('/api/plans/execute', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: byId('planUrl').value.trim(), plan: state.plan, headless: byId('planHeadless').checked }) });
    renderReport(await responseJson(response));
  } catch (error) { showError(error.message); } finally { setBusy(false); }
});

function renderReport(report) {
  byId('reportStats').replaceChildren(stat('总计', report.total), stat('通过', report.passed), stat('失败', report.failed), stat('耗时', `${(report.duration_ms / 1000).toFixed(1)}s`));
  const rows = report.cases.map((item) => {
    const row = document.createElement('tr');
    const name = document.createElement('td'); name.append(createElement('strong', '', item.case_id), document.createElement('br'), document.createTextNode(item.title));
    const result = document.createElement('td'); result.append(statusBadge(item.status)); if (item.error) result.append(document.createElement('br'), document.createTextNode(item.error));
    const detail = createElement('td', '', item.run ? `${item.run.result.duration_ms} ms / ${item.run.result.step_count} 步` : '-');
    const artifacts = document.createElement('td');
    if (item.run) {
      const detailLink = document.createElement('a'); detailLink.href = `/api/runs/${item.run.run_id}`; detailLink.target = '_blank'; detailLink.textContent = '详情'; artifacts.append(detailLink);
      if (item.run.result.artifacts.screenshot) { const link = document.createElement('a'); link.href = item.run.result.artifacts.screenshot; link.target = '_blank'; link.textContent = '截图'; artifacts.append(' · ', link); }
    } else { artifacts.textContent = '-'; }
    row.append(name, result, detail, artifacts); return row;
  });
  byId('reportBody').replaceChildren(...rows); byId('planResults').hidden = false; byId('planResults').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function stat(label, value) { const item = createElement('span', 'stat'); item.append(createElement('strong', '', value), createElement('span', '', label)); return item; }
function statusBadge(status) { const labels = { passed: '通过', failed: '失败', error: '错误' }; return createElement('span', `badge ${status === 'error' ? 'error-status' : status}`, labels[status] || status); }

byId('runForm').addEventListener('submit', async (event) => {
  event.preventDefault(); setBusy(true, '正在生成并执行测试'); byId('singleResult').hidden = true;
  try {
    const response = await fetch('/api/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: byId('url').value.trim(), goal: byId('goal').value.trim(), headless: byId('headless').checked }) });
    const data = await responseJson(response);
    byId('runId').textContent = data.run_id; byId('finalUrl').textContent = data.result.final_url || '-'; byId('title').textContent = data.result.title || '-';
    const status = byId('statusBadge'); status.textContent = data.result.status === 'passed' ? '通过' : '失败'; status.className = `badge ${data.result.status}`;
    byId('code').textContent = data.generated_code; byId('logs').textContent = JSON.stringify({ error: data.result.error, console: data.result.console, page_errors: data.result.page_errors }, null, 2);
    byId('screenshotLink').href = data.result.artifacts.screenshot || '#'; byId('traceLink').href = data.result.artifacts.trace || '#'; byId('singleResult').hidden = false;
  } catch (error) { showError(error.message); } finally { setBusy(false); }
});

checkHealth();
