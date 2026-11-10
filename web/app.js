'use strict';

const main = document.getElementById('main');
const notice = document.getElementById('notice');
const newRun = document.getElementById('new-run');
const newUploadRun = document.getElementById('new-upload-run');
const newLaunchRun = document.getElementById('new-launch-run');
const newFeedbackRun = document.getElementById('new-feedback-run');
const currentRunLink = document.getElementById('current-run');
const modeLabel = document.getElementById('case-mode-label');
const brandContext = document.getElementById('brand-context');
const workspaceNavLabel = document.getElementById('workspace-nav-label');
const uploadDialog = document.getElementById('upload-dialog');
const uploadCaseForm = document.getElementById('upload-case-form');
const uploadDialogError = document.getElementById('upload-dialog-error');
const launchDialog = document.getElementById('launch-dialog');
const launchCaseForm = document.getElementById('launch-case-form');
const launchDialogError = document.getElementById('launch-dialog-error');
const routeLabel = document.getElementById('route-label');
const navLinks = document.querySelectorAll('[data-route]');

const routes = { product: '产品档案', workspace: 'AI 变更工作区', review: '审核台' };
const statuses = {
  awaiting_documents: ['待上传资料', 'wait'],
  ready_for_analysis: ['可分析', 'good'],
  awaiting_evidence: ['待补证', 'wait'],
  ready_for_review: ['可提交审核', 'good'],
  in_review: ['审核中', 'wait'],
  awaiting_launch_documents: ['待上传新品资料', 'wait'],
  ready_for_launch_analysis: ['可拆解需求', 'good'],
  launch_fact_review: ['事实待审核', 'wait'],
  launch_facts_approved: ['事实已锁定', 'good'],
  launch_content_review: ['渠道草稿待审核', 'wait'],
  awaiting_feedback_documents: ['待上传售后资料', 'wait'],
  ready_for_feedback_analysis: ['可分析反馈', 'good'],
  feedback_review: ['分类待审核', 'wait'],
  feedback_approved: ['分类已批准', 'good'],
  feedback_actions_generated: ['处理草稿已生成', 'good'],
  approved: ['已批准', 'good'],
  publication_partial: ['部分发布成功', 'wait'],
  published: ['发布已核验', 'good'],
};
const roles = [
  ['product', '产品负责人', '确认变更目标、取舍及适用范围', '产品批准'],
  ['engineering', '研发负责人', '核对规格修订及配对操作', '研发批准'],
  ['qa', '测试负责人', '确认实测报告覆盖目标固件', '测试批准'],
  ['content', '内容负责人', '核对说明书和 FAQ 两份差异', '内容批准'],
];
const channels = { manual: '说明书', faq: '售后 FAQ' };
const documentLabels = { spec: '规格书', test: '测试报告', manual: '说明书', faq: '售后 FAQ' };
const uploadOpenStatuses = ['awaiting_documents', 'ready_for_analysis', 'awaiting_evidence', 'ready_for_review'];
const maximumFileSize = 4 * 1024 * 1024;
const impactKinds = { spec: '规格', test: '测试', manual: '说明书', faq: 'FAQ', unaffected: '无影响' };
const feedback = {
  add_evidence: '脱敏报告已归档，目标固件的证据检查通过。',
  submit_review: '变更已提交，等待演示角色逐项批准。',
  approve: '审批记录已保存。',
  reject: '本轮审核已退回，草稿和证据仍可查阅。',
  publish: '说明书已回读核验。FAQ 首次模拟写入失败，可单独重试。',
  retry_channel: 'FAQ 已重新发布并核验实际版次。',
  new_run: '已创建一轮独立演练。',
  new_upload_run: '资料变更已创建，请上传四份材料。',
  new_launch_run: '新品项目已创建，请上传四份材料。',
  upload_document: '资料已保存，原文行号可以回查。',
  run_analysis: '本机 AI 的建议已保存，可在工作区查看。',
  analyze_launch: '需求、规格关联与待执行用例已保存。可前往审核台核对候选事实。',
  approve_launch_fact: '事实审核记录已保存。',
  reject_launch_facts: '事实审核已退回。已上传资料可替换，更新后可重新拆解。',
  generate_launch_drafts: '四类渠道草稿已生成。每份草稿都附有引用的已批准事实编号。',
  approve_launch_content: '内容审核记录已保存，可以模拟发布。',
  reject_launch_content: '渠道草稿已退回，已批准事实可用于重新生成。',
  new_feedback_run: '售后反馈批次已创建，并关联到产品档案。',
  analyze_feedback: '分类、适用范围和证据已保存，可到审核台逐项核对。',
  approve_feedback_item: '反馈分类审核已保存。',
  generate_feedback_actions: '处理草稿已生成并保存在本机。',
};
const creationForms = {
  new_upload_run: { dialog: uploadDialog, form: uploadCaseForm, error: uploadDialogError },
  new_launch_run: { dialog: launchDialog, form: launchCaseForm, error: launchDialogError },
};
const busyNotice = {
  run_analysis: '本机 AI 正在分析，请等待结果。',
  analyze_launch: '本机 AI 正在拆解需求、关联规格与整理用例，请等待结果。',
  generate_launch_drafts: '本机 AI 正在整理四类渠道草稿，请等待结果。',
  analyze_feedback: '本机 AI 正在核对售后原文、版本和产品事实，请等待结果。',
  generate_feedback_actions: '本机 AI 正在整理已批准的处理草稿，请等待结果。',
  upload_document: '正在读取并解析资料…',
};

let state;
let selectedFirmware;
let busy = null;
const pendingFiles = new Map();

const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));
const e = escapeHtml;

const isUpload = () => state?.mode === 'upload';
const isLaunch = () => state?.mode === 'launch';
const isFeedback = () => state?.mode === 'feedback';
const isArchive = () => state?.isCurrent === false;
const canUpload = () => !isArchive() && uploadOpenStatuses.includes(state.status);
const canCreateFeedback = () => !isArchive() && (isFeedback() || (isLaunch() && state.status === 'published'));

function sourceCitations(citations) {
  if (!citations?.length) return '';
  return `<ul class="source-citations" aria-label="原文引用">${citations.map(({ kind, name, line, quote }) =>
    `<li><cite>${e(name || documentLabels[kind] || launchDocumentLabels[kind] || feedbackDocumentLabels[kind] || '上传资料')}${line != null ? ` · 第 ${e(line)} 行` : ''}</cite>${quote ? `<blockquote>${e(quote)}</blockquote>` : ''}</li>`
  ).join('')}</ul>`;
}

function currentRoute() {
  const hash = window.location.hash.slice(1);
  return Object.hasOwn(routes, hash) ? hash : 'product';
}

function statusChip(label, variant = '') {
  return `<span class="chip ${variant}">${e(label)}</span>`;
}

function timeText(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value ?? '') :
    new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date);
}

function heading(title, detail, action = '') {
  return `<header class="page-heading"><div>
    <p class="eyebrow">${isArchive() ? '历史记录 · 只读' : isFeedback() ? '售后反馈批次' : isLaunch() ? '新品项目' : isUpload() ? '资料变更' : '演练记录'} · <span class="mono">${e(state.caseId)}</span></p>
    <h1>${title}</h1>
    <p class="page-description">${detail}</p>
  </div>${action}</header>`;
}

function steps() {
  const active = state.status === 'published' ? 4 :
    ['approved', 'publication_partial'].includes(state.status) ? 3 :
    state.status === 'in_review' ? 2 : 1;
  return `<ol class="steps panel" aria-label="变更进度">${['档案与范围', '证据归档', '分角色审核', '发布回读'].map((label, index) => {
    const css = index === active ? 'is-current' : index < active ? 'is-done' : '';
    return `<li class="${css}" ${index === active ? 'aria-current="step"' : ''}><span class="step-index">${index < active ? '✓' : index + 1}</span><span>${label}</span></li>`;
  }).join('')}</ol>`;
}

function productCard() {
  const product = state.fixture?.product ?? { name: state.scope?.productName };
  const change = state.fixture?.change ?? state.scope;
  const launched = state.status === 'published';
  const currentVersion = launched ? change.newFirmware : change.oldFirmware;
  const targetLabel = launched ? '已核验发布' : '本次目标固件';
  return `<section class="product-card panel metric-strip" aria-label="产品摘要">
    <div class="product-identity">
      <div class="product-symbol"><svg viewBox="0 0 32 32" aria-hidden="true"><rect x="8" y="3.5" width="16" height="25" rx="8"/><path d="M16 3.5V12m-8 .5h16"/></svg></div>
      <div><p class="product-name">${e(product.name)}</p><p class="product-meta">${isUpload() ? '<span>脱敏代号 · 本机资料</span>' : `<span>${e(product.sku)}</span><span>硬件 ${e(product.hardware)}</span><span>${e(product.region)}</span><span>2.4 GHz</span>`}</p></div>
    </div>
    <dl class="product-summary">
      <div><dt>${isUpload() ? '登记的旧固件' : '当前完整发布固件'}</dt><dd class="mono">${e(isUpload() ? change.oldFirmware : currentVersion)}</dd></div>
      <div><dt>${isUpload() && launched ? '目标固件 · 模拟发布已核验' : targetLabel}</dt><dd class="mono">${e(change.newFirmware)}</dd></div>
    </dl>
  </section>`;
}

function traceItem(title, detail) {
  return `<li><span class="trace-dot" aria-hidden="true"></span><div><p class="trace-title">${title}</p><p class="trace-detail">${detail}</p></div></li>`;
}

function productPage() {
  if (isUpload() && !state.aiAnalysis) {
    return heading('产品档案', '查阅资料变更范围及登记的固件版本。', '<a href="#workspace" class="button button-primary">查看变更工作区 →</a>') +
      productCard() + `<section class="panel panel-pad"><h2>等待资料分析</h2><p class="panel-note">在变更工作区上传四份材料并运行分析后，这里会显示带原文依据的规格差异。</p></section>`;
  }
  const { change, drafts } = state.fixture;
  const firmware = selectedFirmware ?? change.oldFirmware;
  const showingNew = firmware === change.newFirmware;
  const published = state.status === 'published';
  const status = isUpload()
    ? showingNew ? statusChip(published ? '模拟发布已核验' : '目标版', published ? 'good' : 'wait') : statusChip('登记的旧版')
    : showingNew
      ? published ? statusChip('当前发布', 'good') : statusChip(state.status === 'publication_partial' ? '部分发布' : '待正式发布', 'wait')
      : published ? statusChip('历史版本') : statusChip('当前发布', 'good');
  const fact = showingNew ? change.after : change.before;
  const factCitations = (showingNew ? change.afterCitations : change.beforeCitations) ??
    state.fixture.impact?.find((item) => item.kind === 'spec')?.citations?.filter((citation) => citation.quote === fact);
  const docLabel = showingNew && !published ? '目标版资料预览' : '该版本渠道资料';
  const reportText = showingNew
    ? state.evidence ? `${e(state.evidence.id)} · 固件 ${e(state.evidence.firmware)}` : '目标版本测试报告待归档'
    : isUpload() ? '旧版口径依据本次上传的历史资料。' : `本轮复测仅覆盖固件 ${e(change.newFirmware)}。`;

  return heading('产品档案', '在同一档案里核对产品版本、受控规格与发布口径。', '<a href="#workspace" class="button button-primary">查看变更工作区 →</a>') +
    productCard() +
    `<div class="layout-two"><div class="stack">
      <section class="panel panel-pad">
        <div class="panel-head"><div><h2>${isUpload() ? '版本与规格对照' : '版本与有效规格'}</h2><p class="panel-note">${isUpload() ? '按已上传的资料核对各版本适用范围。' : '切换固件版本可分别查看各自的配对说明。'}</p></div>${status}</div>
        <div class="versions" aria-label="选择固件版本">${[change.oldFirmware, change.newFirmware].map((version) =>
          `<button type="button" class="version" data-firmware="${e(version)}" aria-pressed="${version === firmware}">固件 ${e(version)}</button>`
        ).join('')}</div>
        <div class="product-fact"><span class="diff-label">${isUpload() ? '规格原文依据' : '配对操作 · 仅适用 2.4 GHz 接收器'}</span><strong>${e(fact)}</strong></div>
        ${isUpload() ? sourceCitations(factCitations) : ''}
        <dl class="detail-grid">
          <div><dt>规格编号</dt><dd class="mono">${e(change.specId)}</dd></div>
          <div><dt>固件版本</dt><dd class="mono">${e(firmware)}</dd></div>
          <div><dt>${showingNew ? '验证用例' : '证据范围'}</dt><dd>${showingNew ? `<span class="mono">${e(change.caseId)}</span>` : '历史发布资料'}</dd></div>
        </dl>
      </section>
      <section class="panel panel-pad">
        <div class="panel-head"><div><h2>${docLabel}</h2><p class="panel-note">只显示所选固件对应的内容。</p></div></div>
        <ul class="trace-list">${Object.entries(channels).map(([key, label]) =>
          traceItem(label, e(drafts[key][showingNew ? 'after' : 'before']))
        ).join('')}</ul>
      </section>
    </div><div class="stack">
      <section class="panel panel-pad">
        <div class="panel-head"><div><h2>依据与追溯</h2><p class="panel-note">决策、用例和实测分别留存。</p></div></div>
        <ul class="trace-list">
          ${showingNew
            ? traceItem(`决策 <span class="mono">${e(change.decisionId)}</span>`, e(change.decisionReason)) +
              traceItem(`用例 <span class="mono">${e(change.caseId)}</span>`, e(change.expected))
            : traceItem('历史发布依据', `固件 ${e(change.oldFirmware)} 对应的说明书和售后 FAQ。`)}
          ${traceItem('实测证据', reportText)}
        </ul>
      </section>
      <section class="panel panel-pad">
        <div class="panel-head"><div><h2>本轮变更</h2><p class="panel-note">${e(change.title)}</p></div>${statusChip(...statuses[state.status])}</div>
        <div class="actions"><a class="button button-secondary button-small" href="#workspace">查看证据与草稿</a></div>
      </section>
    </div></div>`;
}

function diffCards() {
  if (isUpload() && !state.aiAnalysis) return '<p class="empty">等待本机 AI 分析资料。</p>';
  const { drafts, change } = state.fixture;
  return Object.entries(channels).map(([key, label]) => `<article class="diff">
    <div class="diff-header"><h3>${label}</h3>${drafts[key].source ? `<span class="chip mono">${e(drafts[key].source)}</span>` : ''}</div>
    <div class="diff-body">
      <div class="diff-value"><span class="diff-label">现行版 · ${e(change.oldFirmware)}</span>${e(drafts[key].before)}</div>
      <div class="diff-value after"><span class="diff-label">变更版 · ${e(change.newFirmware)}</span>${e(drafts[key].after)}</div>
    </div>${sourceCitations(drafts[key].citations)}
  </article>`).join('');
}

function timeline(note = '补证、审核和发布回执留在当前演练中。') {
  const history = [...state.history].reverse();
  const entry = (event) => `<li><div class="history-line"><strong>${e(event.label)}</strong><time datetime="${e(event.at)}">${e(timeText(event.at))}</time></div><p class="history-detail">${e(event.detail)}</p></li>`;
  return `<section class="panel panel-pad"><div class="panel-head"><div><h2>操作记录</h2><p class="panel-note">${e(note)}</p></div></div>
    ${history.length ? `<ol class="history">${history.slice(0, 4).map(entry).join('')}</ol>` : '<p class="empty">暂无操作记录。</p>'}
    ${history.length > 4 ? `<details class="history-toggle"><summary>查看更早的 ${history.length - 4} 条记录</summary><ol class="history">${history.slice(4).map(entry).join('')}</ol></details>` : ''}
  </section>`;
}

function analysisPanel() {
  const available = state.modelMode === 'local_ai_available';
  const analysis = state.aiAnalysis;
  const mode = available ? '本机 AI + 规则校验' : isUpload() ? '本机模型未就绪' : '规则演练 · 未接模型';
  const text = available
    ? isUpload() ? '从上传材料识别影响和证据，生成说明书及 FAQ 的修改差异。' : '本机模型可以检查适用范围、证据和渠道影响。建议独立保留，发布依据由规则校验与人工审核确定。'
    : isUpload() ? '启动本机模型服务后可分析这组资料。已上传资料会保留。' : '当前使用固定规则回放已脱敏的变更、影响项和渠道差异。';
  const awaitingUploads = isUpload() && Object.keys(state.documents ?? {}).length < Object.keys(documentLabels).length;
  const showAnalyze = available && !isArchive() && (!isUpload() || ['awaiting_documents', 'ready_for_analysis'].includes(state.status));
  return `<section class="panel panel-pad">
    <div class="panel-head"><div><h2>变更分析</h2><p class="panel-note">${text}</p></div>${statusChip(mode, available ? 'good' : '')}</div>
    ${analysis ? `<div class="callout"><strong>本机模型 · ${e(analysis.model)}</strong><p>${e(analysis.summary)}</p></div>
      ${analysis.checks?.length ? `<ul class="analysis-checks">${analysis.checks.map((check) => `<li>${e(check)}</li>`).join('')}</ul>` : ''}` : ''}
    ${showAnalyze ? `<div class="actions"><button type="button" class="button ${isUpload() ? 'button-primary' : 'button-secondary button-small'}" data-action="run_analysis" ${busy || awaitingUploads ? 'disabled' : ''}>${busy === 'run_analysis' ? '本机 AI 分析中…' : '运行本机 AI 分析'}</button>${awaitingUploads ? '<span class="panel-note">上传四份材料后可运行。</span>' : ''}</div>` : ''}
  </section>`;
}

function uploadMaterials({ labels = documentLabels, editable = canUpload(), analyzed = state.aiAnalysis } = {}) {
  const documents = state.documents ?? {};
  return `<section class="panel panel-pad">
    <div class="panel-head"><div><h2>上传资料</h2><p class="panel-note">每份不超过 4 MiB。支持有文本层的 PDF、DOCX、Markdown 和 TXT。</p></div>${statusChip(`${Object.keys(documents).length}/${Object.keys(labels).length} 已上传`, isFeedback() ? 'feedback-status' : '')}</div>
    <div class="upload-grid">${Object.entries(labels).map(([kind, label]) => {
      const doc = documents[kind];
      const pending = pendingFiles.get(kind);
      const fileSize = doc ? (doc.size >= 1024 ? `${Math.ceil(doc.size / 1024)} KB` : `${doc.size} B`) : '';
      const actionLabel = label === 'PRD' ? ' PRD' : label;
      return `<section class="material-card"><div class="panel-head"><h3>${label}</h3>${statusChip(doc ? '已解析' : '待上传', doc ? 'good' : '')}</div>
        ${doc ? `<p class="trace-detail"><strong>${e(doc.name)}</strong> · ${e(fileSize)} · ${doc.lines.length} 行</p>
          <details class="material-preview"><summary>查看解析行号</summary><ol>${doc.lines.slice(0, 40).map((line) => `<li>${e(line)}</li>`).join('')}</ol>${doc.lines.length > 40 ? '<p>预览前 40 行，分析引用保留各自的原文行号。</p>' : ''}</details>` : '<p class="trace-detail">暂无资料。</p>'}
        ${editable ? `<form class="material-form" data-upload-kind="${kind}">
          <label class="material-input">${doc ? '替换' : '选择'}${actionLabel}<input type="file" accept=".pdf,.docx,.md,.txt" data-document-kind="${kind}" ${busy ? 'disabled' : ''}></label>
          <p class="trace-detail pending-file" ${pending ? '' : 'hidden'}>${pending ? `待上传 · ${e(pending.name)}` : ''}</p>
          <button type="submit" class="button button-secondary button-small" ${busy || !pending ? 'disabled' : ''}>上传${actionLabel}</button>
        </form>` : ''}
      </section>`;
    }).join('')}</div>
    ${editable && analyzed ? '<p class="panel-note material-replace-note">更换已分析的资料后，需重新分析和审核。</p>' : ''}
  </section>`;
}

function uploadWorkspacePage() {
  const { scope, evidence, aiAnalysis } = state;
  const { change, impact = [] } = state.fixture ?? {};
  const ready = state.status === 'ready_for_review';
  const evidenceMissing = state.status === 'awaiting_evidence';
  const action = isArchive() ? '' : ready ? `<button type="button" class="button button-primary" data-action="submit_review" ${busy ? 'disabled' : ''}>提交审核</button>` :
    !canUpload() ? '<a class="button button-primary" href="#review">查看审核进度 →</a>' : '';
  return heading('AI 变更工作区', '上传脱敏的历史资料，核对 AI 找到的原文依据和修改差异。', statusChip(...statuses[state.status])) + steps() +
    `<div class="layout-two"><div class="stack">
      <section class="panel panel-pad action-panel ${evidenceMissing ? 'warning' : ''}">
        <div class="panel-head"><div><h2>${e(change?.title || '上传资料固件变更')}</h2><p class="panel-note">${e(scope.productName)} · 固件 <span class="mono">${e(scope.oldFirmware)}</span> → <span class="mono">${e(scope.newFirmware)}</span></p></div></div>
        ${evidence ? `<div class="callout"><strong>已定位目标版本的测试记录</strong><p>${e(evidence.summary)}</p></div>${sourceCitations(evidence.citations)}` :
          evidenceMissing ? `<div class="callout warning"><strong>缺少目标版本的测试证据</strong><p>请核对测试报告是否覆盖 ${e(scope.newFirmware)}，替换报告后重新分析。</p></div>` :
            '<p class="trace-detail">提交审核前需核对测试报告覆盖目标固件。</p>'}
        ${action ? `<div class="actions">${action}</div>` : ''}
      </section>
      ${uploadMaterials()}
      ${aiAnalysis ? `<section class="panel panel-pad"><div class="panel-head"><div><h2>说明书与 FAQ 差异</h2><p class="panel-note">逐项核对上传原文、修改建议和适用版本。</p></div></div>${diffCards()}</section>` : ''}
    </div><div class="stack">
      ${analysisPanel()}
      ${aiAnalysis && impact.length ? `<section class="panel panel-pad"><div class="panel-head"><div><h2>影响清单</h2><p class="panel-note">依据上传资料定位受影响的内容。</p></div>${statusChip(`${impact.length} 项`)}</div><ul class="impact-list">${impact.map((item) => `<li><div><p class="impact-title">${e(item.title)}</p><p class="trace-detail">${e(item.detail)}</p>${sourceCitations(item.citations)}</div>${statusChip(impactKinds[item.kind] || item.kind)}</li>`).join('')}</ul></section>` : ''}
      ${timeline()}
    </div></div>`;
}

function workspacePage() {
  if (isUpload()) return uploadWorkspacePage();
  const { change, report, impact } = state.fixture;
  const waiting = state.status === 'awaiting_evidence';
  const ready = state.status === 'ready_for_review';
  const evidence = state.evidence;
  const progress = statusChip(...statuses[state.status]);
  const statusAction = isArchive() ? '' : waiting ? `<button type="button" class="button button-primary" data-action="add_evidence" ${busy ? 'disabled' : ''}>导入脱敏报告</button>`
    : ready ? `<button type="button" class="button button-primary" data-action="submit_review" ${busy ? 'disabled' : ''}>提交审核</button>`
      : '<a class="button button-primary" href="#review">查看审核进度 →</a>';
  return heading('AI 变更工作区', '核对目标范围与实测报告，生成可以逐项审核的修改差异。', progress) + steps() +
    `<div class="layout-two"><div class="stack">
      <section class="panel panel-pad action-panel ${waiting ? 'warning' : ''}">
        <div class="panel-head"><div><h2>${e(change.title)}</h2><p class="panel-note">固件 <span class="mono">${e(change.oldFirmware)}</span> → <span class="mono">${e(change.newFirmware)}</span> · 2.4 GHz 接收器</p></div></div>
        <div class="callout ${waiting ? 'warning' : ''}">${waiting
          ? `<strong>缺少目标固件实测证据</strong><p>需要导入固件 ${e(change.newFirmware)} 的配对验证报告。待补证期间可以查看草稿。</p>`
          : `<strong>目标版本证据已归档</strong><p>${e(evidence?.summary ?? '')}</p>`}</div>
        <dl class="detail-grid">
          <div><dt>用例</dt><dd class="mono">${e(change.caseId)}</dd></div>
          <div><dt>报告编号</dt><dd class="mono">${e(evidence?.id ?? report.id)}</dd></div>
          <div><dt>实测结论</dt><dd>${e(evidence?.result ?? '待补证')}</dd></div>
        </dl>
        <p class="panel-note">${e(evidence?.source ?? report.source)}</p>
        <div class="actions">${statusAction}${waiting ? '<button type="button" class="button button-secondary" disabled>提交审核</button>' : ''}</div>
      </section>
      <section class="panel panel-pad">
        <div class="panel-head"><div><h2>说明书与 FAQ 差异</h2><p class="panel-note">按旧版和目标版并排查看。</p></div></div>
        ${diffCards()}
      </section>
    </div><div class="stack">
      ${analysisPanel()}
      <section class="panel panel-pad">
        <div class="panel-head"><div><h2>影响清单</h2><p class="panel-note">基于试点已登记的引用关系。</p></div>${statusChip(`${impact.length} 项`)}</div>
        <ul class="impact-list">${impact.map((item) => `<li><div><p class="impact-title">${e(item.title)}</p><p class="trace-detail">${e(item.detail)}</p></div>${statusChip(impactKinds[item.kind] || item.kind)}</li>`).join('')}</ul>
      </section>
      ${timeline()}
    </div></div>`;
}

function reviewPage() {
  const change = state.fixture?.change ?? state.scope;
  const active = state.status === 'in_review' && !isArchive();
  const approvedCount = roles.filter(([key]) => state.approvals[key]).length;
  const headline = state.status === 'published' ? '两个渠道均已回读核验。' :
    state.status === 'publication_partial' ? 'FAQ 首次模拟写入失败，可仅重试该渠道。' :
    state.status === 'approved' ? '四个角色均已批准，可以锁定发布版次。' :
    active ? '角色为演示身份。审核记录绑定当前证据与草稿。' : '先在变更工作区补齐实测证据并提交审核。';
  const startButton = active || approvedCount
    ? ''
    : '<a href="#workspace" class="button button-secondary button-small">前往变更工作区</a>';
  const releaseNote = state.release
    ? `发布包 <span class="mono">${e(state.release.id)}</span> · 目标版次 <span class="mono">${e(state.release.version)}</span> · 固件 <span class="mono">${e(state.release.firmware)}</span>`
    : '全部角色批准后即可模拟发布。说明书先成功，FAQ 首次写入演练失败恢复。';

  return heading('审核台', '逐项确认决策、规格、实测证据和渠道内容，回读每个渠道采用的版次。', statusChip(...statuses[state.status])) + steps() +
    `<div class="layout-two"><div class="stack">
      <section class="panel panel-pad">
        <div class="panel-head"><div><h2>分角色审批</h2><p class="panel-note">${headline}</p></div><span class="review-summary">${approvedCount}/${roles.length} 已批准</span></div>
        <ul class="review-list">${roles.map(([key, label, detail, button]) => {
          const approval = state.approvals[key];
          const note = isUpload() && key === 'engineering' ? '核对规格修订及适用范围' : detail;
          return `<li><div><h3>${label}</h3><p class="trace-detail">${note}${approval ? ` · ${e(timeText(approval.at))}` : ''}</p></div>
          ${approval ? statusChip('已批准', 'good') : `<button type="button" class="button button-secondary button-small" data-action="approve" data-role="${key}" ${!active || busy ? 'disabled' : ''}>${button}</button>`}</li>`;
        }).join('')}</ul>
        ${startButton ? `<div class="actions">${startButton}</div>` : ''}
        ${active ? `<div class="actions"><button type="button" class="button button-secondary button-small" data-action="reject" data-role="qa" ${busy ? 'disabled' : ''}>以测试身份退回</button></div><p class="panel-note">退回会清空本轮审批，保留实测证据和草稿。</p>` : ''}
      </section>
      <section class="panel panel-pad">
        <div class="panel-head"><div><h2>渠道发布与回读</h2><p class="panel-note">${releaseNote}</p></div>${statusChip('模拟渠道')}</div>
        <div class="channel-grid">${Object.entries(channels).map(([key, label]) => {
          const channel = state.channels[key];
          const variant = channel.status === 'verified' ? 'good' : channel.status === 'failed' ? 'bad' : '';
          const channelStatus = channel.status === 'verified' ? '已回读核验' : channel.status === 'failed' ? '写入失败' : '待发布';
          return `<article class="channel-card ${channel.status === 'failed' ? 'failed' : ''}">
            <div class="panel-head"><h3>${label}</h3>${statusChip(channelStatus, variant)}</div>
            <p class="trace-detail">${e(channel.detail || '等待发布包。')}</p>
            <dl><div><dt>尝试次数</dt><dd class="mono">${e(channel.attempts)}</dd></div><div><dt>实际版次</dt><dd class="mono">${e(channel.actualVersion || '—')}</dd></div><div><dt>渠道回执</dt><dd class="mono">${e(channel.receipt || '—')}</dd></div></dl>
          </article>`;
        }).join('')}</div>
        <div class="actions">
          ${!state.release && !isArchive() ? `<button type="button" class="button button-primary" data-action="publish" ${state.status !== 'approved' || busy ? 'disabled' : ''}>模拟发布</button>` : ''}
          ${state.channels.faq.status === 'failed' && !isArchive() ? `<button type="button" class="button button-primary" data-action="retry_channel" data-channel="faq" ${busy ? 'disabled' : ''}>重试 FAQ</button>` : ''}
        </div>
      </section>
    </div><div class="stack">
      <section class="panel panel-pad">
        <div class="panel-head"><div><h2>审核与发布依据</h2><p class="panel-note">${state.evidence ? `实测证据 <span class="mono">${e(state.evidence.id)}</span> · ${e(state.evidence.firmware)}` : '实测证据待补齐'}</p></div></div>
        <details class="review-evidence">
          <summary>查看决策、规格与实测</summary>
          <ul class="trace-list">
            ${traceItem(`决策 <span class="mono">${e(change.decisionId)}</span>`, e(change.decisionReason))}
            ${traceItem(`规格 <span class="mono">${e(change.specId)}</span>`, e(change.after))}
            ${traceItem('实测与来源', state.evidence ? `${e(state.evidence.summary)}<br>${e(state.evidence.source)}` : '目标版报告待归档。')}
          </ul>
          ${sourceCitations(state.evidence?.citations)}
          ${state.reviewRevision ? `<p class="panel-note">审核依据版次 <span class="mono">${e(state.reviewRevision)}</span></p>` : ''}
        </details>
        ${diffCards()}
      </section>
      ${timeline()}
    </div></div>`;
}

function render({ focus = false } = {}) {
  const route = currentRoute();
  const workspaceLabel = isFeedback() ? 'AI 售后工作区' : isLaunch() ? 'AI 新品工作区' : routes.workspace;
  const pageLabel = route === 'workspace' ? workspaceLabel : routes[route];
  routeLabel.textContent = pageLabel;
  workspaceNavLabel.textContent = workspaceLabel;
  brandContext.textContent = isFeedback() ? '售后反馈演练' : isLaunch() ? '新品发布演练' : '固件变更演练';
  document.title = `${pageLabel} · 产品知识链`;
  for (const link of navLinks) {
    if (link.dataset.route === route) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  newRun.disabled = !state || Boolean(busy) || isArchive();
  newUploadRun.disabled = newRun.disabled;
  newLaunchRun.disabled = newRun.disabled;
  newFeedbackRun.disabled = newRun.disabled || !canCreateFeedback();
  newFeedbackRun.hidden = !canCreateFeedback();
  newLaunchRun.classList.toggle('button-primary', !canCreateFeedback());
  newLaunchRun.classList.toggle('button-secondary', canCreateFeedback());
  newRun.hidden = isArchive();
  newUploadRun.hidden = isArchive();
  newLaunchRun.hidden = isArchive();
  currentRunLink.hidden = !isArchive();
  currentRunLink.textContent = isFeedback() ? '返回当前工作区' : isLaunch() ? '返回当前项目' : '返回当前变更';
  modeLabel.textContent = isFeedback() ? '售后资料 · 本机草稿' : isLaunch() ? '新品资料 · 模拟渠道' : isUpload() ? '脱敏资料 · 模拟渠道' : '虚构样本 · 模拟渠道';
  if (!state) return;
  const builders = isFeedback() ? feedbackPages : isLaunch() ? launchPages : { product: productPage, workspace: workspacePage, review: reviewPage };
  main.innerHTML = builders[route]();
  main.setAttribute('aria-busy', busy ? 'true' : 'false');
  if (focus) main.focus();
}

function displayNotice(text, isError = false) {
  notice.textContent = text;
  notice.classList.toggle('is-error', isError);
  notice.hidden = !text;
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '本机服务暂未返回结果。');
  return data;
}

async function start() {
  displayNotice('');
  try {
    const selectedCase = new URLSearchParams(window.location.search).get('caseId');
    const endpoint = selectedCase ? `/api/demo?caseId=${encodeURIComponent(selectedCase)}` : '/api/demo';
    state = await requestJson(endpoint);
    render();
  } catch (error) {
    main.innerHTML = `<section class="panel panel-pad"><h1>暂时无法读取演练</h1><p class="page-description">${e(error.message)}</p><div class="actions"><button type="button" class="button button-secondary" data-action="reconnect">重新连接</button><a class="button button-secondary" href="/">返回当前变更</a></div></section>`;
  }
}

function readFileBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('无法读取文件，请重新选择后再试。'));
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1]);
    reader.readAsDataURL(file);
  });
}

async function applyAction(action, extras = {}, file) {
  if (busy || !state || isArchive()) return;
  busy = action;
  const payload = { action, caseId: state.caseId, ...extras };
  const creation = creationForms[action];
  displayNotice(busyNotice[action] || '');
  if (creation) {
    creation.error.hidden = true;
    creation.form.querySelector('button[type="submit"]').disabled = true;
  }
  render();
  try {
    if (file) payload.contentBase64 = await readFileBase64(file);
    state = await requestJson('/api/actions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (action === 'upload_document') pendingFiles.delete(payload.kind);
    if (action === 'new_run' || action === 'new_feedback_run' || creation) {
      selectedFirmware = undefined;
      pendingFiles.clear();
      history.replaceState(null, '', window.location.pathname + window.location.hash);
    }
    if (action === 'submit_review') window.location.hash = '#review';
    if (action === 'new_run') window.location.hash = '#product';
    if (action === 'new_feedback_run') window.location.hash = '#workspace';
    if (creation) {
      creation.dialog.close();
      window.location.hash = '#workspace';
    }
    const launchPublishNotice = isLaunch() && action === 'publish'
      ? state.status === 'publication_partial' ? '新品宣讲、产品页面和说明书已回读。FAQ 首次模拟失败，可单独重试。' : '四类渠道均已回读核验。'
      : '';
    displayNotice(launchPublishNotice || feedback[action] || '演练状态已更新。');
  } catch (error) {
    displayNotice(error.message, true);
    if (creation?.dialog.open) {
      creation.error.textContent = error.message;
      creation.error.hidden = false;
    }
  } finally {
    busy = null;
    render();
    if (creation) creation.form.querySelector('button[type="submit"]').disabled = false;
    const sameButton = action === 'upload_document' ? document.querySelector(`input[data-document-kind="${payload.kind}"]`) :
      [...document.querySelectorAll(`[data-action="${action}"]`)].find((button) =>
        (!payload.role || button.dataset.role === payload.role) && (!payload.itemId || button.dataset.itemId === payload.itemId));
    if (!creation?.dialog.open && sameButton && !sameButton.disabled && !sameButton.hidden) sameButton.focus({ preventScroll: true });
    else if (!creation?.dialog.open) {
      const nextButton = main.querySelector('.button-primary:not(:disabled)');
      if (nextButton) nextButton.focus({ preventScroll: true });
      else main.focus({ preventScroll: true });
    }
  }
}

function perform(button) {
  const action = button.dataset.action;
  if (action === 'reconnect') return start();
  const extras = {};
  if (action === 'add_evidence') extras.firmware = state.fixture.change.newFirmware;
  if (button.dataset.role) extras.role = button.dataset.role;
  if (button.dataset.channel) extras.channel = button.dataset.channel;
  if (action === 'new_feedback_run') {
    if (!canCreateFeedback()) return;
    extras.productCaseId = isFeedback() ? state.scope.productCaseId : state.caseId;
  }
  if (action === 'approve_feedback_item') {
    extras.itemId = button.dataset.itemId;
    extras.category = button.closest('[data-feedback-review]')?.querySelector('select')?.value;
  }
  return applyAction(action, extras);
}

newUploadRun.addEventListener('click', () => {
  uploadCaseForm.reset();
  uploadDialogError.hidden = true;
  uploadDialog.showModal();
});
document.getElementById('close-upload-dialog').addEventListener('click', () => uploadDialog.close());
uploadCaseForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const fields = Object.fromEntries(new FormData(uploadCaseForm));
  for (const key of Object.keys(fields)) fields[key] = fields[key].trim();
  if (Object.values(fields).some((value) => !value) || fields.oldFirmware === fields.newFirmware) {
    uploadDialogError.textContent = '请输入产品名称，并填写不同的旧固件版本和目标版本。';
    uploadDialogError.hidden = false;
    return;
  }
  applyAction('new_upload_run', fields);
});

newLaunchRun.addEventListener('click', () => {
  launchCaseForm.reset();
  launchDialogError.hidden = true;
  launchDialog.showModal();
});
document.getElementById('close-launch-dialog').addEventListener('click', () => launchDialog.close());
launchCaseForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const fields = Object.fromEntries(new FormData(launchCaseForm));
  for (const key of Object.keys(fields)) fields[key] = fields[key].trim();
  if (Object.values(fields).some((value) => !value)) {
    launchDialogError.textContent = '请输入脱敏产品名称和产品版本。';
    launchDialogError.hidden = false;
    return;
  }
  applyAction('new_launch_run', fields);
});

main.addEventListener('change', (event) => {
  const input = event.target.closest('input[data-document-kind]');
  if (!input) return;
  const kind = input.dataset.documentKind;
  const file = input.files[0];
  const slot = input.closest('form');
  const pending = slot.querySelector('.pending-file');
  if (!file || file.size > maximumFileSize || file.size === 0) {
    pendingFiles.delete(kind);
    pending.hidden = true;
    slot.querySelector('button').disabled = true;
    if (file) displayNotice('请选择非空且不超过 4 MiB 的文件。', true);
    return;
  }
  pendingFiles.set(kind, file);
  pending.textContent = `待上传 · ${file.name}`;
  pending.hidden = false;
  slot.querySelector('button').disabled = false;
  displayNotice('');
});

main.addEventListener('submit', (event) => {
  const form = event.target.closest('form[data-upload-kind]');
  if (!form) return;
  event.preventDefault();
  const kind = form.dataset.uploadKind;
  const file = pendingFiles.get(kind);
  if (file) applyAction('upload_document', { kind, name: file.name }, file);
});

document.addEventListener('click', (event) => {
  if (event.target.closest('.skip-link')) {
    event.preventDefault();
    main.focus();
    return;
  }
  const firmware = event.target.closest('button[data-firmware]');
  if (firmware) {
    selectedFirmware = firmware.dataset.firmware;
    render();
    document.querySelector('button[data-firmware][aria-pressed="true"]')?.focus({ preventScroll: true });
    return;
  }
  const button = event.target.closest('button[data-action]');
  if (button) perform(button);
});
window.addEventListener('hashchange', () => render({ focus: true }));
start();
