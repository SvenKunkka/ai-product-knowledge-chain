'use strict';

const launchDocumentLabels = { decision: '产品决策纪要', prd: 'PRD', spec: '规格书', verification: '验证依据' };
const launchChannelLabels = { briefing: '新品宣讲', product_page: '产品页面', manual: '说明书', faq: '售后 FAQ' };
const launchFactRoles = [
  ['product', '产品负责人', '核对候选事实与新品范围和 PRD 一致。', '产品事实批准'],
  ['engineering', '研发负责人', '核对规格原文和适用条件。', '研发事实批准'],
  ['qa', '测试负责人', '核对验证依据的边界，并区分待执行用例。', '测试事实批准'],
];

function launchButton(action, label, { secondary = false, enabled = true, role, channel } = {}) {
  if (isArchive()) return '';
  return `<button type="button" class="button ${secondary ? 'button-secondary button-small' : 'button-primary'}"
    data-action="${action}" ${role ? `data-role="${role}"` : ''} ${channel ? `data-channel="${channel}"` : ''}
    ${enabled && !busy ? '' : 'disabled'}>${label}</button>`;
}

function launchProgress() {
  const active = state.status === 'published' ? 4 :
    ['approved', 'publication_partial'].includes(state.status) ? 3 :
    ['launch_facts_approved', 'launch_content_review'].includes(state.status) ? 2 :
    state.status === 'launch_fact_review' ? 1 : 0;
  const labels = ['资料与需求', '事实审核', '内容审核', '发布回读'];
  return `<ol class="steps panel" aria-label="新品项目进度">${labels.map((label, index) => {
    const css = index === active ? 'is-current' : index < active ? 'is-done' : '';
    return `<li class="${css}" ${index === active ? 'aria-current="step"' : ''}><span class="step-index">${index < active ? '✓' : index + 1}</span><span>${label}</span></li>`;
  }).join('')}</ol>`;
}

function launchScopeCard() {
  const { productName, productVersion } = state.scope;
  return `<section class="product-card panel metric-strip" aria-label="新品范围">
    <div class="product-identity">
      <div class="product-symbol"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M7 10h18v13H7zm5 5h8m-8 4h6M11 10V7h10v3"/></svg></div>
      <div><p class="product-name">${e(productName)}</p><p class="product-meta">脱敏产品代号 · 新品项目</p></div>
    </div>
    <dl class="product-summary">
      <div><dt>产品版本</dt><dd class="mono">${e(productVersion)}</dd></div>
      <div><dt>模拟发布版次</dt><dd class="mono">${e(state.release?.version || '待发布')}</dd></div>
    </dl>
  </section>`;
}

function launchFactList(facts) {
  if (!facts?.length) return '<p class="empty">当前没有已关联规格与验证依据的事实。</p>';
  return `<ul class="launch-facts">${facts.map((fact) => `<li>
    <p class="launch-fact-text">${statusChip(fact.id, 'good')} <strong>${e(fact.text)}</strong></p>
    <p class="panel-note">对应需求 <span class="mono">${e(fact.requirementId)}</span></p>
    <details class="launch-detail"><summary>查看规格和验证原文</summary>${sourceCitations(fact.citations)}</details>
  </li>`).join('')}</ul>`;
}

function launchDraftCards(drafts) {
  if (!drafts) return '<p class="empty">事实通过审核后，可生成四类渠道草稿。</p>';
  return `<div class="launch-drafts">${Object.entries(launchChannelLabels).map(([key, label]) => {
    const draft = drafts.channels?.[key];
    if (!draft) return '';
    return `<article class="diff launch-draft">
      <header class="diff-header"><h3>${label}</h3><span class="chips" aria-label="已批准事实编号">${(draft.factIds || []).map((id) => statusChip(id)).join('')}</span></header>
      <div class="diff-value"><strong class="launch-draft-title">${e(draft.title)}</strong><p>${e(draft.text)}</p></div>
    </article>`;
  }).join('')}</div>`;
}

function launchRequirements(analysis) {
  const requirements = analysis?.requirements ?? [];
  if (!requirements.length) return '';
  const linked = requirements.filter((requirement) => requirement.spec).length;
  return `<section class="panel panel-pad">
    <div class="panel-head"><div><h2>需求追溯与测试用例</h2><p class="panel-note">逐项核对决策和 PRD 原文、规格关联、验证依据与待执行用例。</p></div>${statusChip(`${linked}/${requirements.length} 已关联规格`, linked === requirements.length ? 'good' : 'wait')}</div>
    <div class="launch-requirements">${requirements.map((requirement) => `<article class="diff">
      <header class="diff-header"><h3><span class="mono">${e(requirement.id)}</span> ${e(requirement.title)}</h3>${statusChip(requirement.spec ? '已关联规格' : '待关联规格', requirement.spec ? 'good' : 'wait')}</header>
      <div class="launch-requirement-body">
        <p class="launch-requirement-text">${e(requirement.text)}</p>
        <div class="launch-requirement-grid">
          <section><h4>决策与 PRD</h4>${sourceCitations(requirement.citations) || '<p class="empty">待补原文引用。</p>'}</section>
          <section><h4>关联规格</h4>${requirement.spec ? sourceCitations([requirement.spec]) : '<p class="empty">这条需求暂未关联可核对的规格。</p>'}</section>
          <section><h4>验证依据</h4>${requirement.verification ? sourceCitations([requirement.verification]) : '<p class="empty">这条需求暂未匹配到验证依据。</p>'}</section>
        </div>
        ${requirement.test ? `<section class="launch-test"><div class="panel-head"><div><h4>待执行用例 · ${e(requirement.test.title)}</h4></div>${statusChip('待执行', 'wait')}</div>
          <ol>${(requirement.test.steps || []).map((step) => `<li>${e(step)}</li>`).join('')}</ol>
          <p class="trace-detail"><strong>预期结果</strong> ${e(requirement.test.expected)}</p>
        </section>` : ''}
      </div>
    </article>`).join('')}</div>
  </section>`;
}

function launchProductPage() {
  const analysis = state.launchAnalysis;
  const approved = state.approvedFacts ?? [];
  const factLabel = approved.length ? '已批准事实' : '候选事实';
  return heading('产品档案', '查看新品版本、来源与可用于发布的事实。', '<a href="#workspace" class="button button-primary">查看新品工作区 →</a>') +
    launchScopeCard() + launchProgress() +
    `<div class="layout-two"><div class="stack">
      <section class="panel panel-pad">
        <div class="panel-head"><div><h2>${factLabel}</h2><p class="panel-note">${approved.length ? '四类渠道只引用此处锁定的事实。' : '产品、研发与测试分别确认后，才可生成渠道草稿。'}</p></div>${statusChip(...statuses[state.status])}</div>
        ${launchFactList(approved.length ? approved : analysis?.facts)}
      </section>
      ${launchRequirements(analysis)}
    </div><div class="stack">
      <section class="panel panel-pad">
        <div class="panel-head"><div><h2>新品资料</h2><p class="panel-note">保留上传原件和解析行号。</p></div></div>
        <ul class="launch-facts">${Object.entries(launchDocumentLabels).map(([key, label]) => `<li><strong>${label}</strong><p class="trace-detail">${e(state.documents?.[key]?.name || '待上传')}</p></li>`).join('')}</ul>
      </section>
      ${timeline('资料、事实审核和渠道回执保留在当前项目中。')}
    </div></div>`;
}

function launchWorkspacePage() {
  const editable = !isArchive() && ['awaiting_launch_documents', 'ready_for_launch_analysis'].includes(state.status);
  const canAnalyze = state.status === 'ready_for_launch_analysis' && state.modelMode === 'local_ai_available';
  const analysis = state.launchAnalysis;
  return heading('AI 新品工作区', '从产品决策和 PRD 拆解需求，关联规格、验证依据与待执行用例。', statusChip(...statuses[state.status])) +
    launchScopeCard() + launchProgress() +
    `<div class="stack">
      <section class="panel panel-pad action-panel">
        <div class="panel-head"><div><h2>${analysis ? '需求拆解结果' : '拆解需求与用例'}</h2>
          <p class="panel-note">${analysis ? e(analysis.summary) : '四份资料上传后，使用本机 AI 提取候选需求与可追溯事实。'}</p></div>
          ${statusChip(analysis?.model || (state.modelMode === 'local_ai_available' ? '本机 AI' : '本机模型未就绪'), state.modelMode === 'local_ai_available' ? 'good' : 'wait')}
        </div>
        ${analysis ? '<div class="actions"><a href="#review" class="button button-primary">前往审核台 →</a></div>' : `<div class="actions">${launchButton('analyze_launch', '拆解需求与用例', { enabled: canAnalyze })}</div>`}
      </section>
      ${uploadMaterials({ labels: launchDocumentLabels, editable, analyzed: analysis })}
      ${launchRequirements(analysis)}
    </div>`;
}

function launchFactReview() {
  const facts = state.approvedFacts?.length ? state.approvedFacts : state.launchAnalysis?.facts ?? [];
  const approvals = state.factApprovals ?? {};
  const count = launchFactRoles.filter(([role]) => approvals[role]).length;
  const reviewing = state.status === 'launch_fact_review';
  const canReturn = reviewing || state.status === 'launch_facts_approved';
  return `<section class="panel panel-pad">
    <div class="panel-head"><div><h2>第一阶段 · 事实审核</h2><p class="panel-note">仅审核有规格及验证依据的事实。测试用例保留待执行状态。</p></div><span class="review-summary">${count}/${launchFactRoles.length} 已批准</span></div>
    <ul class="review-list">${launchFactRoles.map(([role, title, description, button]) => `<li>
      <div><h3>${title}</h3><p class="trace-detail">${description}${approvals[role] ? ` · ${e(timeText(approvals[role].at))}` : ''}</p></div>
      ${approvals[role] ? statusChip('已批准', 'good') : launchButton('approve_launch_fact', button, { role, secondary: true, enabled: reviewing && facts.length > 0 })}
    </li>`).join('')}</ul>
    ${reviewing && !facts.length ? '<p class="panel-note">目前没有可批准的候选事实。请退回后补齐规格和验证依据，再运行分析。</p>' : ''}
    ${state.factReviewRevision ? `<p class="panel-note">事实审核版次 <span class="mono">${e(state.factReviewRevision)}</span></p>` : ''}
    ${canReturn && !isArchive() ? `<div class="actions">${launchButton('reject_launch_facts', '退回事实审核', { role: 'qa', secondary: true })}</div>` : ''}
    ${!state.launchAnalysis ? '<div class="actions"><a href="#workspace" class="button button-secondary button-small">前往新品工作区</a></div>' : ''}
  </section>`;
}

function launchContentReview() {
  const draftReady = state.status === 'launch_content_review';
  const canReturn = draftReady || state.status === 'approved';
  const contentApproval = state.approvals?.content;
  return `<section class="panel panel-pad">
    <div class="panel-head"><div><h2>第二阶段 · 渠道内容审核</h2><p class="panel-note">事实锁定后生成宣讲、页面、说明书和 FAQ。内容审批绑定本轮草稿。</p></div>
      ${contentApproval ? statusChip('内容已批准', 'good') : statusChip('待内容批准', 'wait')}</div>
    ${contentApproval ? `<p class="trace-detail">内容负责人 · ${e(timeText(contentApproval.at))}</p>` : ''}
    ${state.reviewRevision ? `<p class="panel-note">内容审核版次 <span class="mono">${e(state.reviewRevision)}</span></p>` : ''}
    ${state.status === 'launch_facts_approved' && !isArchive() ? `<div class="actions">${launchButton('generate_launch_drafts', '生成四类渠道草稿', { enabled: state.modelMode === 'local_ai_available' })}</div>` : ''}
    ${canReturn && !isArchive() ? `<div class="actions">${draftReady ? launchButton('approve_launch_content', '内容批准') : ''}${launchButton('reject_launch_content', '退回渠道草稿', { secondary: true })}</div>` : ''}
  </section>`;
}

function launchPublication() {
  const release = state.release;
  return `<section class="panel panel-pad">
    <div class="panel-head"><div><h2>模拟发布与渠道回读</h2><p class="panel-note">${release ? `发布包 <span class="mono">${e(release.id)}</span> · 版次 <span class="mono">${e(release.version)}</span>` : '事实与内容均批准后可发布到四个本机模拟渠道。'}</p></div>${statusChip('模拟渠道')}</div>
    <div class="channel-grid">${Object.entries(launchChannelLabels).map(([key, label]) => {
      const channel = state.channels?.[key] ?? {};
      const verified = channel.status === 'verified';
      const failed = channel.status === 'failed';
      return `<article class="channel-card ${failed ? 'failed' : ''}">
        <div class="panel-head"><h3>${label}</h3>${statusChip(verified ? '已回读核验' : failed ? '写入失败' : '待发布', verified ? 'good' : failed ? 'bad' : '')}</div>
        <p class="trace-detail">${e(channel.detail || '等待发布包。')}</p>
        <dl><div><dt>尝试次数</dt><dd class="mono">${e(channel.attempts ?? 0)}</dd></div><div><dt>实际版次</dt><dd class="mono">${e(channel.actualVersion || '—')}</dd></div><div><dt>渠道回执</dt><dd class="mono">${e(channel.receipt || '—')}</dd></div></dl>
      </article>`;
    }).join('')}</div>
    ${!isArchive() ? `<div class="actions">
      ${!release ? launchButton('publish', '模拟发布', { enabled: state.status === 'approved' }) : ''}
      ${state.channels?.faq?.status === 'failed' ? launchButton('retry_channel', '重试 FAQ', { channel: 'faq' }) : ''}
    </div>` : ''}
  </section>`;
}

function launchReviewPage() {
  const approved = state.approvedFacts ?? [];
  return heading('审核台', '依次核对新品事实与渠道内容，再回读四类模拟发布回执。', statusChip(...statuses[state.status])) +
    launchScopeCard() + launchProgress() +
    `<div class="layout-two"><div class="stack">
      ${launchFactReview()}
      ${launchContentReview()}
      ${launchPublication()}
      ${timeline('事实审批、内容审批和渠道回执均可追溯。')}
    </div><div class="stack">
      <section class="panel panel-pad">
        <div class="panel-head"><div><h2>${approved.length ? '已批准事实' : '候选事实与来源'}</h2><p class="panel-note">按事实编号回查关联需求、规格与验证依据。</p></div></div>
        ${launchFactList(approved.length ? approved : state.launchAnalysis?.facts)}
      </section>
      <section class="panel panel-pad">
        <div class="panel-head"><div><h2>四类渠道草稿</h2><p class="panel-note">草稿附已批准事实编号，可逐项核对产品口径。</p></div></div>
        ${launchDraftCards(state.launchDrafts)}
      </section>
    </div></div>`;
}

const launchPages = { product: launchProductPage, workspace: launchWorkspacePage, review: launchReviewPage };
