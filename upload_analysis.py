"""Find impact and draft changes from uploaded sources, keeping line-level evidence."""

from datetime import datetime
import json
import re

from local_analysis import complete, schema_for

LABELS = {"spec": "规格书", "test": "测试报告", "manual": "说明书", "faq": "售后 FAQ"}
KEYS = {
    "oldSpec": "spec", "newSpec": "spec", "testVersion": "test", "testObservation": "test",
    "manualBefore": "manual", "faqBefore": "faq",
}
OBSERVED = re.compile(
    r"实测|测试结果|实际结果|观察结果|复测|复核结果|实机|运行结果|验证结果|"
    r"observed|test results?|retest|ran |tested|pass(?:ed)?\b|verified",
    re.IGNORECASE,
)
FAILED = re.compile(r"未通过|不符合预期|无法复现|测试失败|\b(?:failed|failure)\b", re.IGNORECASE)
NOT_OBSERVED = re.compile(r"待测|未测试|待验证|尚未执行|尚未实测|未执行|\bnot (?:tested|run|verified)\b", re.IGNORECASE)


def includes_version(text, version):
    return bool(re.search(
        r"(?<![\w.-])" + re.escape(version) + r"(?![a-zA-Z0-9_.-])",
        text,
        re.IGNORECASE | re.ASCII,
    ))


def words(text):
    return set(re.findall(r"[a-z]{3,}|[\u4e00-\u9fff]{2}", text.lower()))


def snippets(document, scope, cues):
    lines = document["lines"]
    if len(lines) <= 22:
        return {index: line[:420] for index, line in enumerate(lines, 1)}
    ranked = []
    for index, line in enumerate(lines, 1):
        version_score = 8 * sum(includes_version(line, scope[key]) for key in ("oldFirmware", "newFirmware"))
        score = version_score + min(len(words(line) & cues), 8) + 4 * bool(OBSERVED.search(line))
        ranked.append((-score, index))
    selected = {1, 2}
    for _, index in sorted(ranked):
        selected.update(candidate for candidate in (index - 1, index, index + 1) if 1 <= candidate <= len(lines))
        if len(selected) >= 19:
            break
    return {index: lines[index - 1][:420] for index in sorted(selected)}


def reference(documents, chunks, key, number):
    kind = KEYS[key]
    if type(number) is not int or number not in chunks[kind]:
        return None
    document = documents[kind]
    quote = document["lines"][number - 1]
    if len(quote) > 420:
        return None
    return {"kind": kind, "name": document["name"], "line": number, "quote": quote}


def check_spec_range(document, reference_item, wanted, other):
    if reference_item is None:
        return False
    index = reference_item["line"] - 1
    quote = reference_item["quote"]
    if includes_version(quote, wanted):
        return not includes_version(quote, other)
    if includes_version(quote, other):
        return False
    for line in reversed(document["lines"][max(0, index - 2):index]):
        if includes_version(line, wanted):
            return not includes_version(line, other)
        if includes_version(line, other):
            return False
    return False


def collect_locations(scope, documents):
    spec_lines = documents["spec"]["lines"]
    cues = set()
    for index, line in enumerate(spec_lines):
        if any(includes_version(line, scope[key]) for key in ("oldFirmware", "newFirmware")):
            cues.update(words(" ".join(spec_lines[index:index + 3])))
    chunks = {kind: snippets(documents[kind], scope, cues) for kind in LABELS}
    prompt = (
        "从四份资料的带编号行里找同一固件行为变更的依据。只选原文中实际存在的行号，找不到填 0。\n"
        "oldSpec 选规格书旧固件明确写出的原行为行；newSpec 选目标固件明确写出的新行为行。"
        "testVersion 选测试报告明确声明这次测试所用的目标固件行；只在预期或计划中出现的版本不算。"
        "testObservation 选测试报告已执行的真实观察结果行，不要选择预期或计划。"
        "manualBefore 和 faqBefore 分别选说明书与 FAQ 中仍在描述旧行为、因此需要改写的那一行。"
        "优先选实际规则句，别选标题、注释或来源说明。\n"
        + json.dumps({"scope": scope, "lines": chunks}, ensure_ascii=False)
    )
    _, locations = complete(
        prompt, schema_for({key: {"type": "integer", "minimum": 0} for key in KEYS}),
        context=16384, prediction=240,
    )
    return {key: reference(documents, chunks, key, locations.get(key)) for key in KEYS}


def test_evidence(scope, documents, refs):
    version_ref = refs["testVersion"]
    observation = refs["testObservation"]
    if not version_ref or not observation:
        return None, "测试报告暂未定位到目标固件和实际测试观察。"
    version_line = version_ref["quote"]
    result_line = observation["quote"]
    if (
        not includes_version(version_line, scope["newFirmware"])
        or includes_version(version_line, scope["oldFirmware"])
        or re.search(r"预期|计划|待测|expected|planned", version_line, re.IGNORECASE)
        or not OBSERVED.search(result_line)
        or NOT_OBSERVED.search(result_line)
        or abs(version_ref["line"] - observation["line"]) > 14
    ):
        return None, "测试报告的版本或观察结果无法与目标固件核对，请补充明确的实测记录。"
    if FAILED.search(result_line):
        return None, "引用的测试结果包含失败信息，请补充已处置的复测证据。"
    document = documents["test"]
    return {
        "id": document["id"], "title": document["name"], "firmware": scope["newFirmware"],
        "result": "已定位实测记录 · 待测试审核",
        "summary": result_line,
        "source": f'{document["name"]} · 第 {version_ref["line"]}、{observation["line"]} 行',
        "citations": [version_ref, observation],
    }, "已定位目标固件与执行结果，等待测试负责人确认。"


def draft_copy(scope, refs):
    prompt = (
        "根据已核对的规格和旧渠道原文，用简体中文写两个栏目文案。"
        "manualTitle 是说明书小标题，描述功能与适用版本的主题，最多 25 字。"
        "faqQuestion 是用户会问的一个问题，聚焦发生变化的操作，最多 60 字。"
        "正文会从核对过的原文自动填充，所以不要在标题或问句写答案、判定结论、版本号或参数。\n"
        + json.dumps({"scope": scope, "sources": {
            key: refs[key]["quote"] for key in ("oldSpec", "newSpec", "manualBefore", "faqBefore")
        }}, ensure_ascii=False)
    )
    model, generated = complete(
        prompt, schema_for({key: {"type": "string"} for key in ("manualTitle", "faqQuestion")}),
        context=4096, prediction=240,
    )
    for key, limit in (("manualTitle", 60), ("faqQuestion", 120)):
        value = generated.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise RuntimeError("本机模型没有返回完整的修改差异，请重新分析。")
    return model, generated["manualTitle"].strip().lstrip("# ").strip(), generated["faqQuestion"].strip()


def versioned_rule(ref, firmware):
    quote = ref["quote"]
    return quote if includes_version(quote, firmware) else f"固件 {firmware}：{quote}"


def channel_originals(documents, original):
    if original["kind"] != "faq":
        return [original]
    lines = documents["faq"]["lines"]
    index = original["line"] - 1
    question = r"^\s*(?:问|Q)\s*[:：]"
    answer = r"^\s*(?:答|A)\s*[:：]"
    if re.match(question, lines[index], re.IGNORECASE) and index + 1 < len(lines):
        adjacent = index + 1
        expected = answer
    elif re.match(answer, lines[index], re.IGNORECASE) and index > 0:
        adjacent = index - 1
        expected = question
    else:
        return [original]
    if len(lines[adjacent]) > 420 or not re.match(expected, lines[adjacent], re.IGNORECASE):
        return [original]
    paired = {**original, "line": adjacent + 1, "quote": lines[adjacent]}
    return sorted([original, paired], key=lambda item: item["line"])


def analyze_upload(scope, documents):
    refs = collect_locations(scope, documents)
    old_ref, new_ref = refs["oldSpec"], refs["newSpec"]
    old_version, new_version = scope["oldFirmware"], scope["newFirmware"]
    if (
        not check_spec_range(documents["spec"], old_ref, old_version, new_version)
        or not check_spec_range(documents["spec"], new_ref, new_version, old_version)
        or old_ref["line"] == new_ref["line"]
    ):
        raise RuntimeError("AI 未能分别定位新旧规格。请检查规格书是否写明各固件版本及行为差异。")
    if not refs["manualBefore"] or not refs["faqBefore"]:
        raise RuntimeError("AI 未能同时定位说明书和 FAQ 中受影响的旧段落，请核对上传资料。")

    evidence, evidence_status = test_evidence(scope, documents, refs)
    model, title, question = draft_copy(scope, refs)
    # Use the cited rules verbatim so channel wording cannot reverse verified behavior.
    rules = "\n".join((versioned_rule(new_ref, new_version), versioned_rule(old_ref, old_version)))
    proposed = {
        "manual": f"{title}\n{rules}",
        "faq": f"问：{question.removeprefix('问：')}\n答：请先确认固件版本和功能配置。\n{rules}",
    }
    summary = f"定位到固件 {old_version} 与 {new_version} 的规则差异，以及说明书和 FAQ 中对应的旧段落。"
    drafts = {}
    for kind, key in (("manual", "manualBefore"), ("faq", "faqBefore")):
        original = refs[key]
        originals = channel_originals(documents, original)
        line_numbers = "、".join(str(item["line"]) for item in originals)
        drafts[kind] = {
            "before": "\n".join(item["quote"] for item in originals),
            "after": proposed[kind],
            "source": f'{original["name"]} · 第 {line_numbers} 行',
            "citations": [*originals, new_ref, old_ref],
        }
    fixture = {
        "product": {"name": scope["productName"], "sku": "资料变更", "hardware": "见上传资料", "region": "本机工作区"},
        "change": {
            "title": "上传资料 · 固件变更",
            "oldFirmware": old_version, "newFirmware": new_version,
            "before": old_ref["quote"], "after": new_ref["quote"],
            "decisionId": "上传规格依据", "decisionReason": f'{new_ref["name"]} · 第 {new_ref["line"]} 行',
            "specId": documents["spec"]["id"], "caseId": documents["test"]["id"],
            "expected": evidence_status,
        },
        "drafts": drafts,
        "report": evidence or {
            "id": documents["test"]["id"], "title": documents["test"]["name"],
            "firmware": new_version, "result": "待补证", "summary": evidence_status,
            "source": documents["test"]["name"],
        },
        "impact": [
            {"title": "规格行为变化", "detail": summary, "kind": "spec", "citations": [old_ref, new_ref]},
            {"title": "目标固件验证", "detail": evidence_status, "kind": "test", "citations": evidence["citations"] if evidence else []},
            *[
                {"title": LABELS[kind], "detail": "旧段落引用了受影响的行为，已生成待审修改。", "kind": kind,
                 "citations": drafts[kind]["citations"]}
                for kind in ("manual", "faq")
            ],
        ],
    }
    return {
        "fixture": fixture,
        "evidence": evidence,
        "aiAnalysis": {
            "model": model,
            "summary": summary,
            "checks": [evidence_status, "审核渠道差异时逐项核对引用和适用版本。"],
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    }
