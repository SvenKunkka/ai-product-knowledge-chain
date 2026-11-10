"""Review customer feedback and draft local follow-up items for a published product."""

from http import HTTPStatus
import re

from launch_workflow import required_text, source_reference


DOCUMENTS = {"feedback": "售后反馈", "support": "核对依据"}
EDITABLE = {"awaiting_feedback_documents", "ready_for_feedback_analysis"}
CATEGORIES = {
    "faq_gap": "FAQ 缺口",
    "doc_error": "资料错误",
    "product_defect": "产品缺陷",
    "needs_review": "待核对",
}
ACTION_TYPES = {
    "faq_gap": "faq_update",
    "doc_error": "documentation_task",
    "product_defect": "product_improvement",
    "needs_review": "triage",
}
VERSION_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,47}")


class FeedbackError(Exception):
    def __init__(self, message, status=HTTPStatus.CONFLICT):
        super().__init__(message)
        self.status = status


def snapshot_product(parent):
    if parent.get("mode") != "launch" or parent.get("status") != "published":
        raise FeedbackError("售后反馈只能关联已完成发布回读的新品档案。")
    scope = parent["scope"]
    release = parent["release"]
    faq = parent["launchDrafts"]["channels"]["faq"]
    return {
        "caseId": parent["caseId"],
        "productName": scope["productName"],
        "productVersion": scope["productVersion"],
        "releaseVersion": release["version"],
        "approvedFacts": parent["approvedFacts"],
        "faq": {"title": faq["title"], "text": release["contents"]["faq"], "factIds": faq["factIds"]},
    }


def after_upload(state):
    state.update(
        feedbackAnalysis=None, feedbackRevision=None, feedbackApprovals={},
        approvedFeedback=[], feedbackActions=None,
    )
    state["status"] = (
        "ready_for_feedback_analysis" if state["documents"].keys() == DOCUMENTS.keys()
        else "awaiting_feedback_documents"
    )


def fact_links(values, allowed):
    if (
        not isinstance(values, list)
        or any(not isinstance(value, str) or value not in allowed for value in values)
        or len(values) != len(set(values))
    ):
        raise ValueError("invalid product fact links")
    return values


def reported_firmware(item, quote):
    version, status = item.get("firmware"), item.get("versionStatus")
    if status == "unconfirmed" and version is None:
        return None
    if (
        status != "documented"
        or not isinstance(version, str)
        or VERSION_TOKEN.fullmatch(version) is None
        or re.search(
            r"(?<![A-Za-z0-9._+\-])" + re.escape(version) + r"(?![A-Za-z0-9]|[._+\-][A-Za-z0-9])",
            quote,
        ) is None
    ):
        raise ValueError("reported firmware must be cited from the feedback")
    return version


def read_analysis(result, documents, snapshot):
    if not isinstance(result, dict):
        raise ValueError("invalid feedback analysis")
    proposed = result.get("items")
    if not isinstance(proposed, list) or not 1 <= len(proposed) <= 40:
        raise ValueError("invalid feedback item count")
    allowed = {fact["id"] for fact in snapshot["approvedFacts"]}
    items = {}
    for item in proposed:
        identifier = required_text(item["id"])
        if identifier in items:
            raise ValueError("duplicate feedback item")
        category = item["category"]
        if category not in CATEGORIES:
            raise ValueError("invalid feedback category")
        feedback = source_reference(item["feedback"], documents, "feedback")
        support = source_reference(item["support"], documents, "support") if item.get("support") is not None else None
        firmware = reported_firmware(item, feedback["quote"])
        items[identifier] = {
            "id": identifier, "title": required_text(item["title"]), "category": category,
            "rationale": required_text(item["rationale"]), "firmware": firmware,
            "versionStatus": "documented" if firmware is not None else "unconfirmed",
            "feedback": feedback, "support": support, "factIds": fact_links(item["factIds"], allowed),
        }
    return {
        "model": required_text(result["model"]), "at": required_text(result["at"]),
        "summary": required_text(result["summary"]), "items": list(items.values()),
    }


def review_item(state, request):
    identifier = request.get("itemId")
    if not isinstance(identifier, str):
        raise FeedbackError("请选择要审核的反馈。", HTTPStatus.BAD_REQUEST)
    analysis = state["feedbackAnalysis"]
    item = next((item for item in analysis["items"] if item["id"] == identifier), None) if analysis else None
    if item is None:
        raise FeedbackError("没有找到这条反馈。", HTTPStatus.NOT_FOUND)
    return item


def approve_item(state, request, record, now):
    item = review_item(state, request)
    identifier = item["id"]
    category = request.get("category", item["category"])
    if not isinstance(category, str) or category not in CATEGORIES:
        raise FeedbackError("请选择有效的审核分类。", HTTPStatus.BAD_REQUEST)
    approvals = state["feedbackApprovals"]
    if identifier in approvals and approvals[identifier]["category"] == category:
        return
    if state["status"] != "feedback_review":
        raise FeedbackError("反馈已锁定。如需调整，请先退回审核。")
    approvals[identifier] = {"at": now(), "category": category, "revision": state["feedbackRevision"]}
    label = CATEGORIES[category]
    detail = f'{identifier} · {item["title"]} · {label}'
    if category != item["category"]:
        detail += f'（AI 建议：{CATEGORIES[item["category"]]}）'
    record(state, "审核售后反馈", detail)
    items = state["feedbackAnalysis"]["items"]
    if len(approvals) == len(items):
        state["approvedFeedback"] = [
            {**item, "reviewedCategory": approvals[item["id"]]["category"]} for item in items
        ]
        state["status"] = "feedback_approved"
        record(state, "锁定售后审核结果", f"已逐项审核 {len(items)} 条反馈，可生成本机草稿。")


def return_item(state, request, record, _now):
    if state["status"] not in {"feedback_review", "feedback_approved"}:
        raise FeedbackError("当前阶段无法退回售后审核。")
    item = review_item(state, request)
    if state["feedbackApprovals"].pop(item["id"], None) is None:
        return
    state.update(status="feedback_review", approvedFeedback=[])
    record(state, "退回售后反馈", f'{item["id"]} · {item["title"]} 重新进入审核。')


def reject_analysis(state, _request, record, _now):
    if state["status"] not in {"feedback_review", "feedback_approved"}:
        raise FeedbackError("当前阶段无法退回售后分析。")
    after_upload(state)
    record(state, "退回售后分析", "保留已上传资料，可替换后重新分析。")


def read_actions(result, approved_items, scope):
    if not isinstance(result, dict):
        raise ValueError("invalid follow-up draft")
    proposed = result.get("actions")
    approved = {item["id"]: item for item in approved_items}
    if not isinstance(proposed, list) or len(proposed) != len(approved):
        raise ValueError("one action per approved feedback is required")
    actions, seen_items, seen_ids = [], set(), set()
    for item in proposed:
        identifier = required_text(item["id"])
        linked = approved[item["itemId"]]
        item_id = linked["id"]
        action_type = ACTION_TYPES[linked["reviewedCategory"]]
        if (
            item_id in seen_items or identifier in seen_ids
            or item.get("type") != action_type
            or item.get("firmware") != linked["firmware"]
            or item.get("productCaseId") != scope["productCaseId"]
            or item.get("productVersion") != scope["productVersion"]
            or item.get("status") != "draft"
        ):
            raise ValueError("follow-up draft differs from approved feedback")
        seen_items.add(item_id)
        seen_ids.add(identifier)
        actions.append({
            "id": identifier, "itemId": item_id, "type": action_type,
            "title": required_text(item["title"]), "text": required_text(item["text"]),
            "factIds": fact_links(item["factIds"], set(linked["factIds"])),
            "firmware": linked["firmware"], "productCaseId": scope["productCaseId"],
            "productVersion": scope["productVersion"], "status": "draft",
        })
    return {"model": required_text(result["model"]), "at": required_text(result["at"]), "actions": actions}


REVIEW_ACTIONS = {
    "approve_feedback_item": approve_item,
    "return_feedback_item": return_item,
    "reject_feedback_analysis": reject_analysis,
}
