"""Fact review and content release rules for a new product launch."""

from hashlib import sha256
from http import HTTPStatus
import json
import re


DOCUMENTS = {"decision": "产品决策纪要", "prd": "PRD", "spec": "规格书", "verification": "验证依据"}
CHANNELS = {
    "manual": "说明书",
    "faq": "售后 FAQ",
    "briefing": "新品宣讲",
    "product_page": "产品页面",
}
FACT_ROLES = {"product": "产品负责人", "engineering": "研发负责人", "qa": "测试负责人"}
EDITABLE = {"awaiting_launch_documents", "ready_for_launch_analysis"}


class LaunchError(Exception):
    def __init__(self, message, status=HTTPStatus.CONFLICT):
        super().__init__(message)
        self.status = status


def read_scope(request):
    name = request.get("productName")
    version = request.get("productVersion")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100 or not name.strip().isprintable():
        raise LaunchError("请填写 1 至 100 字的脱敏产品名。", HTTPStatus.BAD_REQUEST)
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,47}", version.strip()):
        raise LaunchError("产品版本请用 1 至 48 位字母、数字、点、下划线、加号或短横线。", HTTPStatus.BAD_REQUEST)
    return {"productName": name.strip(), "productVersion": version.strip()}


def clear_analysis(state):
    state.update(
        launchAnalysis=None, factApprovals={}, factReviewRevision=None, approvedFacts=[],
        launchDrafts=None, approvals={}, reviewContents=None, reviewRevision=None,
    )


def after_upload(state):
    clear_analysis(state)
    state["status"] = "ready_for_launch_analysis" if state["documents"].keys() == DOCUMENTS.keys() else "awaiting_launch_documents"


def source_hashes(state):
    return {kind: document["digest"] for kind, document in state["documents"].items()}


def revision(state, phase, value):
    source = json.dumps(
        [state["scope"], source_hashes(state), len(state["history"]), value],
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return f'{state["caseId"]}/{phase}/{sha256(source).hexdigest()[:12]}'


def required_text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing text")
    return value


def source_reference(value, documents, kind=None):
    if not isinstance(value, dict):
        raise ValueError("invalid citation")
    source_kind = value.get("kind")
    if not isinstance(source_kind, str) or source_kind not in documents or (kind is not None and source_kind != kind):
        raise ValueError("citation kind mismatch")
    document = documents[source_kind]
    line = value.get("line")
    if (
        type(line) is not int
        or not 1 <= line <= len(document["lines"])
        or value.get("name") != document["name"]
        or value.get("quote") != document["lines"][line - 1]
    ):
        raise ValueError("citation text mismatch")
    return {"kind": source_kind, "name": document["name"], "line": line, "quote": value["quote"]}


def read_analysis(result, documents):
    if not isinstance(result, dict):
        raise ValueError("invalid launch analysis")
    requirements = result.get("requirements")
    facts = result.get("facts")
    if not isinstance(requirements, list) or not requirements or not isinstance(facts, list):
        raise ValueError("invalid requirements or facts")
    normalized_requirements = {}
    for item in requirements:
        identifier = required_text(item["id"])
        if identifier in normalized_requirements:
            raise ValueError("duplicate requirement")
        citations = [source_reference(reference, documents) for reference in item["citations"]]
        if not any(citation["kind"] == "prd" for citation in citations):
            raise ValueError("requirement is missing a PRD citation")
        spec = source_reference(item["spec"], documents, "spec") if item.get("spec") is not None else None
        verification = (
            source_reference(item["verification"], documents, "verification")
            if item.get("verification") is not None else None
        )
        test = item["test"]
        steps = test["steps"]
        if not isinstance(steps, list) or not steps:
            raise ValueError("invalid test steps")
        normalized_requirements[identifier] = {
            "id": identifier, "title": required_text(item["title"]), "text": required_text(item["text"]),
            "citations": citations, "spec": spec, "verification": verification,
            "test": {
                "title": required_text(test["title"]), "steps": [required_text(step) for step in steps],
                "expected": required_text(test["expected"]), "status": "待执行",
            },
        }

    normalized_facts = {}
    for item in facts:
        identifier = required_text(item["id"])
        if identifier in normalized_facts:
            raise ValueError("duplicate fact")
        requirement_id = required_text(item["requirementId"])
        requirement = normalized_requirements[requirement_id]
        spec, verification = requirement["spec"], requirement["verification"]
        citations = [source_reference(reference, documents) for reference in item["citations"]]
        if spec is None or verification is None or spec not in citations or verification not in citations:
            raise ValueError("fact lacks linked specification and verification references")
        if item["text"] != spec["quote"]:
            raise ValueError("fact text does not match the specification")
        normalized_facts[identifier] = {
            "id": identifier, "title": requirement["title"], "text": spec["quote"],
            "requirementId": requirement_id, "citations": citations,
        }
    return {
        "model": required_text(result["model"]), "at": required_text(result["at"]),
        "summary": required_text(result["summary"]),
        "requirements": list(normalized_requirements.values()), "facts": list(normalized_facts.values()),
    }


def read_drafts(result, facts):
    fact_map = {fact["id"]: fact["text"] for fact in facts}
    proposed = result["channels"]
    if not isinstance(proposed, dict) or proposed.keys() != CHANNELS.keys():
        raise ValueError("draft channels are incomplete")
    channels = {}
    for key, draft in proposed.items():
        text = required_text(draft["text"])
        fact_ids = draft["factIds"]
        if (
            not isinstance(fact_ids, list)
            or not fact_ids
            or any(not isinstance(identifier, str) or identifier not in fact_map for identifier in fact_ids)
            or len(fact_ids) != len(set(fact_ids))
            or any(fact_map[identifier] not in text for identifier in fact_ids)
            or any(fact in text for identifier, fact in fact_map.items() if identifier not in fact_ids)
        ):
            raise ValueError("channel draft contains unlinked or unknown facts")
        channels[key] = {"title": required_text(draft["title"]), "text": text, "factIds": fact_ids}
    return {"model": required_text(result["model"]), "at": required_text(result["at"]), "channels": channels}


def approve_fact(state, request, record, now):
    role = request.get("role")
    if not isinstance(role, str) or role not in FACT_ROLES:
        raise LaunchError("请选择产品、研发或测试角色。", HTTPStatus.BAD_REQUEST)
    if role in state["factApprovals"]:
        return
    if state["status"] != "launch_fact_review" or not state["launchAnalysis"]["facts"]:
        raise LaunchError("请先从规格和验证依据中定位可审核的事实。")
    label = FACT_ROLES[role]
    state["factApprovals"][role] = {"at": now(), "label": label, "revision": state["factReviewRevision"]}
    record(state, f"{label}批准新品事实", "本次批准绑定事实候选及四份原件的版本指纹。")
    if state["factApprovals"].keys() == FACT_ROLES.keys():
        state["approvedFacts"] = state["launchAnalysis"]["facts"]
        state["status"] = "launch_facts_approved"
        record(state, "锁定已批准新品事实", f'已锁定 {len(state["approvedFacts"])} 条可用于起草的事实。')


def reject_facts(state, request, record, _now):
    if state["status"] not in {"launch_fact_review", "launch_facts_approved"}:
        raise LaunchError("当前阶段无法退回事实审核。")
    role = request.get("role", "qa")
    if not isinstance(role, str) or role not in FACT_ROLES:
        raise LaunchError("请选择产品、研发或测试角色。", HTTPStatus.BAD_REQUEST)
    after_upload(state)
    record(state, f"{FACT_ROLES[role]}退回新品事实", "保留四份原件，清空本轮分析与批准。可替换资料后重新分析。")


def approve_content(state, _request, record, now):
    if "content" in state["approvals"]:
        return
    if state["status"] != "launch_content_review":
        raise LaunchError("请先根据已批准的事实生成四份待审内容。")
    contents = {key: draft["text"] for key, draft in state["launchDrafts"]["channels"].items()}
    state["reviewContents"] = contents
    state["reviewRevision"] = revision(state, "content", [state["factReviewRevision"], state["launchDrafts"]])
    state["approvals"]["content"] = {"at": now(), "label": "内容负责人", "revision": state["reviewRevision"]}
    state["status"] = "approved"
    record(state, "内容负责人批准新品资料", "宣讲、产品页面、说明书和售后 FAQ 均已锁定待发布文案。")


def reject_content(state, _request, record, _now):
    if state["status"] not in {"launch_content_review", "approved"} or state["release"] is not None:
        raise LaunchError("当前阶段无法退回新品内容审核。")
    state.update(status="launch_facts_approved", launchDrafts=None, approvals={}, reviewRevision=None, reviewContents=None)
    record(state, "内容负责人退回新品草稿", "保留已批准的产品事实，可重新生成渠道草稿。")


REVIEW_ACTIONS = {
    "approve_launch_fact": approve_fact,
    "reject_launch_facts": reject_facts,
    "approve_launch_content": approve_content,
    "reject_launch_content": reject_content,
}
