"""Classify uploaded support feedback and draft actions for approved routing."""

from datetime import datetime
import json
import re

from local_analysis import complete, schema_for


CATEGORIES = {
    "faq_gap": ("FAQ 缺口", "faq_update", "FAQ 更新"),
    "doc_error": ("资料错误", "documentation_task", "资料纠错任务"),
    "product_defect": ("产品缺陷线索", "product_improvement", "产品改进任务"),
    "needs_review": ("待核实", "triage", "补证核实任务"),
}
STRING = {"type": "string"}
MARKER = re.compile(r"^\s*(?:反馈|工单|问题|依据|核对)\s*([A-Za-z]*[0-9]+)\s*[:：]\s*", re.IGNORECASE)
METADATA = re.compile(r"^\s*(?:#{1,6}\s|以下为|公开手册|样本说明|本文|来源[:：]|适用范围[:：])")
FIRMWARE = re.compile(
    r"(?:固件(?:版本)?|firmware(?:\s+version)?)\s*[:：]?\s*(?:v)?"
    r"((?:\d+\.)+\d+(?:[-+][A-Za-z0-9.]+)?|FW-[A-Z0-9]+)(?![A-Za-z0-9_.-])",
    re.IGNORECASE,
)
OTHER_MODEL = re.compile(r"旧(?:款|型号)|另一型号|其他型号|跨型号|different model", re.IGNORECASE)
BEHAVIOR_CONFLICT = re.compile(r"实际仍|实际.*不|不生效|不适用|不一致|不符|did not work", re.IGNORECASE)
FAULT = re.compile(r"重复输入|自行输入|连发|漏键|无输入|没有输入|不响应|误触发|卡死|崩溃|uncommanded|chattering", re.IGNORECASE)
PERSISTENT = re.compile(r"仍有|仍持续|仍在|未解决|仍出现|问题持续|persist|keeps happening", re.IGNORECASE)
HOW_TO = re.compile(r"(?:询问|想知道|请问)(?:怎么|如何|怎样)([^。；？！?]+)", re.IGNORECASE)
INSTRUCTION = re.compile(r"长按|按住|切到|选择|进入|插回|插入|开启|hold |press |select ", re.IGNORECASE)


def text(value, limit):
    return value.strip().replace("\x00", "")[:limit] if isinstance(value, str) else ""


def candidate_lines(document, limit):
    lines = [(number, line) for number, line in enumerate(document["lines"], 1)
             if len(line) <= 700 and not METADATA.match(line)]
    marked = [(number, line) for number, line in lines if MARKER.match(line)]
    return dict((marked or lines)[:limit])


def source(documents, kind, line):
    if type(line) is not int or not 1 <= line <= len(documents[kind]["lines"]):
        return None
    doc = documents[kind]
    return {"kind": kind, "name": doc["name"], "line": line, "quote": doc["lines"][line - 1]}


def selected_support(issue, options, proposed):
    marker = MARKER.match(issue)
    if marker:
        matches = [number for number, line in options.items()
                   if (candidate := MARKER.match(line)) and candidate[1].casefold() == marker[1].casefold()]
        if len(matches) == 1:
            return matches[0]
        if matches and proposed not in matches:
            return None
        if not matches and any(MARKER.match(line) for line in options.values()):
            return None
    return proposed if type(proposed) is int and proposed in options else None


def keywords(line):
    english = set(re.findall(r"[a-z]{3,}|\d+\.\d+", line.lower()))
    chinese = set()
    for part in re.findall(r"[\u4e00-\u9fff]+", line):
        chinese.update(part[index:index + 2] for index in range(len(part) - 1))
    return english | chinese


def classify_issue(scope, issue, supports, facts, faq):
    explicit_match = selected_support(issue, supports, None)
    issue_words = keywords(issue)
    if explicit_match is not None:
        candidates = {explicit_match: supports[explicit_match]}
    else:
        candidates = dict(sorted(
            supports.items(), key=lambda pair: len(keywords(pair[1]) & issue_words), reverse=True,
        )[:4])
    visible_facts = {identifier: statement for identifier, statement in facts.items()
                     if len(keywords(statement) & issue_words) >= 3}
    shape = schema_for({
        "title": STRING, "category": {"type": "string", "enum": list(CATEGORIES)},
        "rationale": STRING, "supportLine": {"type": "integer", "minimum": 0},
        "factIds": {"type": "array", "items": STRING, "maxItems": len(visible_facts)},
    })
    prompt = (
        "只分类下面这一条反馈。按优先顺序判断："
        "一、把另一型号的说明套到本型号、或资料与本型号明确依据矛盾，选 doc_error。"
        "二、报告按键自行输入、漏键或功能异常且排查后仍在，选 product_defect，作为待复现线索。"
        "三、用户在问怎么操作，适用资料有步骤但本项目 FAQ 只列功能或没有步骤，选 faq_gap。"
        "配对操作说明的缺口可以独立处理，不能说已解决用户个案。其余选 needs_review。"
        "rationale 用自己的话点明本条反馈与核对依据中的具体证据，不逐字重复分类定义。"
        "supportLine 只能是核对依据的行号，无匹配填 0。factIds 只从给定相关事实选，无关联留空。"
        "写反映症状的简短标题，标题不加分类前缀或编号。\n"
        + json.dumps({"scope": scope, "feedback": issue, "support": candidates,
                      "approvedFacts": visible_facts, "faqBaseline": faq[:2600]}, ensure_ascii=False)
    )
    model, result = complete(prompt, shape, context=8192, prediction=700)
    return model, result, visible_facts


def check_category(issue, support_ref, category, rationale, faq):
    support = support_ref["quote"] if support_ref else ""
    if OTHER_MODEL.search(issue) and BEHAVIOR_CONFLICT.search(issue) and OTHER_MODEL.search(support):
        return "doc_error", "反馈引用了旧型号说明，核对依据给出本型号的不同规则。需纠正资料的适用型号和入口。"
    if FAULT.search(issue) and PERSISTENT.search(issue):
        return "product_defect", "用户报告异常输入，排查后症状仍在。归入待复现的产品缺陷线索，根因和范围待确认。"
    if HOW_TO.search(issue) and INSTRUCTION.search(support) and len(keywords(support) - keywords(faq)) >= 6:
        return "faq_gap", "用户询问具体操作，核对依据给出了可补充的步骤，当前 FAQ 缺少这段操作。个案结果仍待确认。"
    if category in {"faq_gap", "doc_error"} and support_ref is None:
        return "needs_review", "未匹配到可核对的资料行，请补充对应型号的操作资料或正确口径。"
    return category, rationale


def analyze_feedback(scope, product_snapshot, documents):
    issues = candidate_lines(documents["feedback"], 8)
    supports = candidate_lines(documents["support"], 18)
    if not issues or not supports:
        raise RuntimeError("没有找到可分析的反馈或核对依据。请让每条反馈单独成行并保留正文。")

    facts = {item["id"]: item["text"] for item in product_snapshot["approvedFacts"]}
    items = []
    for number, raw_issue in issues.items():
        model, proposed, visible_facts = classify_issue(scope, raw_issue, supports, facts, product_snapshot["faq"]["text"])
        title = text(proposed.get("title"), 85)
        category = proposed.get("category")
        rationale = text(proposed.get("rationale"), 340)
        if not title or not rationale or not isinstance(category, str) or category not in CATEGORIES:
            raise RuntimeError("AI 返回的反馈分类缺少标题或依据，请重试。")
        evidence_number = selected_support(raw_issue, supports, proposed.get("supportLine"))
        support_ref = source(documents, "support", evidence_number)
        category, rationale = check_category(raw_issue, support_ref, category, rationale, product_snapshot["faq"]["text"])
        if category == "faq_gap" and (question := HOW_TO.search(raw_issue)):
            title = f"如何{question[1].strip()}"
        elif category == "doc_error" and OTHER_MODEL.search(raw_issue):
            title = "跨型号快捷键引用" if "快捷键" in raw_issue else "跨型号资料引用"
        elif category == "product_defect" and FAULT.search(raw_issue) and PERSISTENT.search(raw_issue):
            title = "持续性输入异常"
        versions = {match[1] for match in FIRMWARE.finditer(raw_issue)}
        firmware = next(iter(versions)) if len(versions) == 1 else None
        fact_ids = proposed.get("factIds")
        fact_ids = [identifier for identifier in fact_ids if isinstance(identifier, str) and identifier in visible_facts] if isinstance(fact_ids, list) else []
        items.append({
            "id": f"FB-{len(items) + 1:02d}", "title": title, "category": category, "rationale": rationale,
            "firmware": firmware, "versionStatus": "documented" if firmware else "unconfirmed",
            "feedback": source(documents, "feedback", number),
            "support": support_ref, "factIds": list(dict.fromkeys(fact_ids)),
        })
    summary = f'已关联 {scope["productName"]} 档案 {scope["productVersion"]}，提取 {len(items)} 条待审核反馈。'
    return {"model": model, "at": datetime.now().astimezone().isoformat(timespec="seconds"), "summary": summary, "items": items}


def generate_feedback_actions(scope, product_snapshot, approved_feedback):
    fact_map = {item["id"]: item["text"] for item in product_snapshot["approvedFacts"]}
    model_rows = {}
    for item in approved_feedback:
        category = item.get("reviewedCategory", item["category"])
        model_rows[item["id"]] = {
            "type": CATEGORIES[category][2], "title": item["title"], "reportedFirmware": item["firmware"],
            "feedback": item["feedback"]["quote"],
            "support": item["support"]["quote"] if item["support"] else "",
            "facts": [fact_map[identifier] for identifier in item["factIds"]],
        }
    prompt = (
        "按已审核的类型为每条反馈拟标题 title、FAQ 问句 question 和下一步 nextStep。"
        "资料纠错只提出限定型号和核对入口的任务，不宣布已改资料。"
        "产品改进写可执行的复现步骤或数据收集，不能把用户报告写成根因确认、已修复或影响全部固件。"
        "FAQ 问句用简体中文，答案将用核对依据原句，别在问句写未核对的参数。"
        "每条 nextStep 不超过 100 字。\n"
        + json.dumps({"scope": scope, "approvedItems": model_rows}, ensure_ascii=False)
    )
    shape = schema_for({"title": STRING, "question": STRING, "nextStep": STRING})
    model, result = complete(prompt, schema_for({key: shape for key in model_rows}), context=12288, prediction=1700)
    actions = []
    for index, item in enumerate(approved_feedback, 1):
        draft = result.get(item["id"])
        if not isinstance(draft, dict):
            raise RuntimeError("AI 没有为全部已审核反馈生成处理草稿，请重试。")
        category = item.get("reviewedCategory", item["category"])
        _, action_type, type_label = CATEGORIES[category]
        title = text(draft.get("title"), 90) or f'{type_label} · {item["title"]}'
        next_step = text(draft.get("nextStep"), 230)
        source_scope = f'{scope["productName"]} · 产品档案 {scope["productVersion"]} · {scope["productCaseId"]}'
        reported = f'用户报告固件：{item["firmware"]}' if item["firmware"] else "用户设备固件：待确认"
        parts = [source_scope, reported]
        support_ref = item["support"]
        if action_type == "faq_update" and support_ref:
            question = text(draft.get("question"), 140) or item["title"]
            answer, _, boundary = MARKER.sub("", support_ref["quote"], count=1).partition("依据边界：")
            parts.extend([f"问：{question.removeprefix('问：')}", f"答：{answer}"])
            if boundary:
                parts.append(f"核对说明：{boundary}")
        else:
            parts.append(f'反馈：{item["feedback"]["quote"]}')
            if next_step:
                parts.append(f"下一步：{next_step}")
            if action_type == "documentation_task":
                parts.append("待办：定位使用错版资料的入口，修订适用型号与配列说明，并保存新旧口径对照。")
            if action_type == "product_improvement":
                parts.append("状态：待工程复现；记录实际连接、配列、固件和按键事件，再确认原因及影响范围。")
            if support_ref:
                parts.append(f'核对依据：{support_ref["quote"]}')
        if support_ref:
            parts.append(f'来源：{support_ref["name"]} · 第 {support_ref["line"]} 行')
        actions.append({
            "id": f"ACT-{index:02d}", "itemId": item["id"], "type": action_type, "title": title,
            "text": "\n\n".join(parts), "factIds": item["factIds"], "firmware": item["firmware"],
            "productCaseId": scope["productCaseId"], "productVersion": scope["productVersion"], "status": "draft",
        })
    return {"model": model, "at": datetime.now().astimezone().isoformat(timespec="seconds"), "actions": actions}
