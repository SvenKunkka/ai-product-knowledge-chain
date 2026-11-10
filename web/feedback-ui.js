'use strict';

const feedbackDocumentLabels = { feedback: '售后反馈', support: '核对依据' };
const feedbackCategories = {
  faq_gap: ['FAQ 缺口', 'good'],
  doc_error: ['资料错误', 'wait'],
  product_defect: ['产品缺陷线索', 'bad'],
  needs_review: ['待核实', 'wait'],
};
const feedbackActionLabels = {
  faq_update: 'FAQ 更新',
  documentation_task: '资料纠错任务',
  product_improvement: '产品改进任务',
  triage: '待核实任务',
};

function feedbackProductLink(label = '打开关联产品档案') {
  const parent = state.scope.productCaseId;
  return `<a class="button button-secondary button-small" href="/?caseId=${encodeURIComponent(parent)}#product">${e(label)} →</a>`;
}

function feedbackScopeCard() {
  const scope = state.scope;
  return `<section class="product-card panel metric-strip" aria-label="关联产品范围">
    <div class="product-identity">
      <div class="product-symbol"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M6 7h20v14H14l-5 5v-5H6zM11 12h10m-10 4h7"/></svg></div>
      <div><p class="product-name">${e(scope.productName)}</p><p class="product-meta">关联档案 · ${e(scope.productCaseId)}</p></div>
    </div>
    <dl class="product-summary">
      <div><dt>档案产品版本</dt><dd class="mono">${e(scope.productVersion)}</dd></div>
      <div><dt>引用的发布版次</dt><dd class="mono">${e(state.productSnapshot?.releaseVersion || '待核对')}</dd></div>
    </dl>
  </section>`;
}

function feedbackProgress() {
  const active = state.status === 'feedback_actions_generated' ? 4 :
    state.status === 'feedback_approved' ? 3 :
    state.status === 'feedback_review' ? 2 :
    state.status === 'ready_for_feedback_analysis' ? 1 : 0;
  const labels = ['反馈资料', '分析与分类', '逐项审核', '处理草稿'];
  return `<ol class="steps panel" aria-label="售后反馈进度">${labels.map((label, index) => {
    const css = index === active ? 'is-current' : index < active ? 'is-done' : '';
    return `<li class="${css}" ${index === active ? 'aria-current="step"' : ''}><span class="step-index">${index < active ? '✓' : index + 1}</span><span>${label}</span></li>`;
  }).join('')}</ol>`;
}

function feedbackCategoryChip(category) {
  return statusChip(...(feedbackCategories[category] || feedbackCategories.needs_review));
}

function feedbackFactChips(ids) {
  return ids?.length
    ? `<span class="chips" aria-label="关联事实编号">${ids.map((id) => statusChip(id)).join('')}</span>`
    : '<span class="panel-note">无直接关联的已批准事实</span>';
}

function feedbackIssue(item, reviewing = false) {
  const approval = state.feedbackApprovals?.[item.id];
  const versionRecorded = item.versionStatus === 'documented' && item.firmware;
  const canApprove = reviewing && !approval && !isArchive() && state.status === 'feedback_review';
  return `<article class="diff feedback-issue" data-feedback-review>
    <header class="diff-header"><h3><span class="mono">${e(item.id)}</span> ${e(item.title)}</h3>
      <span class="chips">${feedbackCategoryChip(approval?.category ?? item.category)}${approval ? statusChip('已批准', 'good') : ''}</span>
    </header>
    <div class="feedback-card-body">
      <p class="feedback-rationale">${e(item.rationale)}</p>
      <dl class="feedback-version"><div><dt>关联档案版本</dt><dd class="mono">${e(state.scope.productVersion)}</dd></div>
        <div><dt>反馈披露的固件</dt><dd>${versionRecorded ? `<span class="mono">${e(item.firmware)}</span> · 原文已披露` : '待确认'}</dd></div>
      </dl>
      ${feedbackFactChips(item.factIds)}
      <details class="launch-detail" ${reviewing && !approval ? 'open' : ''}>
        <summary>查看反馈与核对依据原文</summary>
        ${sourceCitations([item.feedback, item.support].filter(Boolean))}
        ${item.support ? '' : '<p class="panel-note">核对依据待补充。</p>'}
      </details>
      ${approval ? `<p class="panel-note">已审分类 · ${e(feedbackCategories[approval.category]?.[0] || '待核实')} · ${e(timeText(approval.at))}</p>` : ''}
      ${canApprove ? `<div class="feedback-review-controls">
        <label>审核分类 · ${e(item.id)}<select ${busy ? 'disabled' : ''}>${Object.entries(feedbackCategories).map(([key, [label]]) =>
          `<option value="${key}" ${key === item.category ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
        <button type="button" class="button button-primary button-small" data-action="approve_feedback_item" data-item-id="${e(item.id)}" ${busy ? 'disabled' : ''}>批准 ${e(item.id)}</button>
      </div>` : ''}
    </div>
  </article>`;
}

function feedbackCases(reviewing = false) {
  const analysis = state.feedbackAnalysis;
  if (!analysis) return '';
  const items = analysis.items || [];
  const approvals = items.filter((item) => state.feedbackApprovals?.[item.id]).length;
  const complete = items.length > 0 && approvals === items.length;
  return `<section class="panel panel-pad">
    <div class="panel-head"><div><h2>${reviewing ? '逐项分类审核' : '反馈分析结果'}</h2>
      <p class="panel-note">${complete ? '已完成逐条审核，可按反馈编号回查原文。' : e(analysis.summary)}</p></div>
      ${statusChip(reviewing ? `${approvals}/${items.length} 已批准` : `${items.length} 条反馈`, complete ? 'good feedback-status' : 'feedback-status')}
    </div>
    ${items.length ? items.map((item) => feedbackIssue(item, reviewing)).join('') : '<p class="empty">暂无可审核的反馈条目。</p>'}
  </section>`;
}

function feedbackActionCards() {
  const result = state.feedbackActions;
  const canGenerate = state.status === 'feedback_approved' && !isArchive() && state.modelMode === 'local_ai_available';
  return `<section class="panel panel-pad">
    <div class="panel-head"><div><h2>处理草稿</h2><p class="panel-note">逐项审核通过后生成，保存在本机。</p></div>
      ${result ? statusChip(`${result.actions.length} 份草稿`, 'good') : ''}
    </div>
    ${result ? result.actions.map((action) => `<article class="diff">
      <header class="diff-header"><h3>${e(feedbackActionLabels[action.type] || '处理草稿')}</h3>
        <span class="chips">${statusChip(action.id)}${statusChip('草稿')}</span></header>
      <div class="diff-value">
        <strong class="launch-draft-title">${e(action.title)}</strong>
        <p>${e(action.text)}</p>
        <p class="trace-detail">反馈 ${e(action.itemId)} · 产品版本 ${e(action.productVersion || state.scope.productVersion)} · 固件 ${e(action.firmware || '待确认')}</p>
        ${feedbackFactChips(action.factIds)}
      </div>
    </article>`).join('') : '<p class="empty">处理草稿待生成。</p>'}
    ${state.status === 'feedback_approved' && !isArchive() ? `<div class="actions">
      <button type="button" class="button button-primary button-small" data-action="generate_feedback_actions" ${busy || !canGenerate ? 'disabled' : ''}>生成处理草稿</button>
      ${canGenerate ? '' : '<span class="panel-note">本机模型未就绪。</span>'}
    </div>` : ''}
  </section>`;
}

function feedbackProductPage() {
  const snapshot = state.productSnapshot ?? {};
  return heading('产品档案', '查看本次售后反馈关联的发布版、事实和 FAQ。', feedbackProductLink()) + feedbackScopeCard() +
    feedbackProgress() + `<div class="layout-two"><div class="stack">
      <section class="panel panel-pad"><div class="panel-head"><div><h2>引用的已批准事实</h2><p class="panel-note">原始档案及发布记录可从上方入口查看。</p></div></div>
        ${launchFactList(snapshot.approvedFacts)}
      </section>
      <section class="panel panel-pad"><div class="panel-head"><div><h2>发布版 FAQ</h2><p class="panel-note">分析反馈时用于核对内容覆盖。</p></div></div>
        ${snapshot.faq ? `<article class="diff"><div class="diff-value"><strong class="launch-draft-title">${e(snapshot.faq.title)}</strong><p>${e(snapshot.faq.text)}</p>${feedbackFactChips(snapshot.faq.factIds)}</div></article>`
          : '<p class="empty">没有关联的 FAQ 快照。</p>'}
      </section>
    </div><div class="stack">${feedbackActionCards()}${timeline('资料、分析和审核记录保存在当前批次。')}</div></div>`;
}

function feedbackWorkspacePage() {
  const analysis = state.feedbackAnalysis;
  const editable = !isArchive() && ['awaiting_feedback_documents', 'ready_for_feedback_analysis'].includes(state.status);
  const canAnalyze = state.status === 'ready_for_feedback_analysis' && state.modelMode === 'local_ai_available';
  return heading('AI 售后工作区', '核对反馈、官方依据与发布版 FAQ，记录每条反馈的适用范围。', statusChip(...statuses[state.status])) +
    feedbackScopeCard() + feedbackProgress() + `<div class="stack">
      <section class="panel panel-pad action-panel">
        <div class="panel-head"><div><h2>分析售后反馈</h2><p class="panel-note">上传脱敏反馈及核对依据。固件版本以反馈原文披露为准。</p></div>
          ${statusChip(analysis?.model?.split(':')[0] || (state.modelMode === 'local_ai_available' ? '本机 AI' : '本机模型未就绪'), state.modelMode === 'local_ai_available' ? 'good feedback-status' : 'wait feedback-status')}
        </div>
        <div class="actions">${analysis ? '<a class="button button-primary" href="#review">前往审核台 →</a>' :
          !isArchive() ? `<button type="button" class="button button-primary" data-action="analyze_feedback" ${busy || !canAnalyze ? 'disabled' : ''}>分析售后反馈</button>` : ''}
          ${feedbackProductLink()}
        </div>
      </section>
      ${uploadMaterials({ labels: feedbackDocumentLabels, editable, analyzed: analysis })}
      ${feedbackCases()}
    </div>`;
}

function feedbackReviewPage() {
  const reviewLinks = `<div class="actions">${statusChip(...statuses[state.status])}${feedbackProductLink()}</div>`;
  return heading('审核台', '确认或调整每条反馈的分类，再生成 FAQ 更新、资料纠错或产品改进任务。', reviewLinks) +
    feedbackScopeCard() + feedbackProgress() + `<div class="layout-two"><div class="stack">
      ${feedbackCases(true) || '<section class="panel panel-pad"><h2>待分析反馈</h2><div class="actions"><a class="button button-primary" href="#workspace">前往售后工作区</a></div></section>'}
    </div><div class="stack">${feedbackActionCards()}${timeline('按反馈编号追溯分类与处理草稿。')}</div></div>`;
}

const feedbackPages = { product: feedbackProductPage, workspace: feedbackWorkspacePage, review: feedbackReviewPage };
