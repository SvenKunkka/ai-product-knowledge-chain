"""Extract launch requirements and render approved facts into four channel drafts."""

from datetime import datetime
import json
import re

from local_analysis import complete, schema_for


CHANNEL_LABELS = {
    "briefing": "新品宣讲",
    "product_page": "产品页面",
    "manual": "说明书",
    "faq": "售后 FAQ",
}
STRING = {"type": "string"}
POSITION = {"type": "integer", "minimum": 0}
METADATA = re.compile(
    r"^\s*(?:#{1,6}\s|适用(?:范围|版本)|范围为|项目代号|本文|来源[:：]|"
    r"(?:scope|source|version)\s*:)", re.IGNORECASE
)


def compact_sources(scope, documents):
    """Keep stable original line numbers when selecting bounded model input."""
    scope_words = set(re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]{2}", scope["productName"]))
    sources = {}
    for kind, doc in documents.items():
        lines = doc["lines"]
        content = [(number, line) for number, line in enumerate(lines, 1) if not METADATA.match(line)]
        if len(content) <= 22:
            selected = [number for number, _ in content]
        else:
            ranked = []
            for number, line in content:
                words = set(re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]{2}", line))
                markers = len(re.findall(r"需求|支持|需要|验收|验证|规格|适用|选择|设置|必须", line))
                scope_match = int(scope["productVersion"].casefold() in line.casefold())
                score = len(scope_words & words) + min(markers, 4) + 3 * scope_match
                ranked.append((-score, number))
            selected = sorted(number for _, number in sorted(ranked)[:22])
        sources[kind] = {number: lines[number - 1][:360] for number in selected}
    return sources


def ref(documents, sources, kind, number):
    if type(number) is not int or number not in sources[kind]:
        return None
    document = documents[kind]
    quote = document["lines"][number - 1]
    if len(quote) > 360:
        return None
    return {"kind": kind, "name": document["name"], "line": number, "quote": quote}


def clean(value, limit):
    if not isinstance(value, str):
        return ""
    return value.strip().replace("\x00", "")[:limit]


def terms(line):
    english = set(re.findall(r"[a-z]{3,}", line.lower()))
    chinese = set()
    for part in re.findall(r"[\u4e00-\u9fff]+", line):
        chinese.update(part[index:index + 2] for index in range(len(part) - 1))
    return english | chinese


def retry_mapping(scope, sources, number, fields):
    spec = sources["spec"][number]
    vocabulary = terms(spec)
    candidates = {}
    for kind in ("decision", "prd", "verification"):
        ranked = sorted(
            sources[kind].items(),
            key=lambda pair: len(terms(pair[1]) & vocabulary),
            reverse=True,
        )
        candidates[kind] = dict(ranked[:4])
    if max((len(terms(line) & vocabulary) for line in candidates["prd"].values()), default=0) < 3:
        return None
    prompt = (
        "只检查给定的一个规格能力，不处理其他功能。选择包含这项能力的 PRD 行 prdLine、"
        "支持它的决策行 decisionLine、说明如何复核同一能力的验证依据行 verificationLine。"
        "如果同一 PRD 行还有别的能力，仍可用于这项能力。缺失填 0。"
        "title 与 need 只写这项规格能力，不泛写整行 PRD。\n"
        + json.dumps({"scope": scope, "spec": spec, "candidates": candidates}, ensure_ascii=False)
    )
    _, result = complete(prompt, schema_for(fields), context=6144, prediction=460)
    return result


def match_capabilities(scope, sources):
    spec_keys = {f"spec_{number}": number for number in list(sources["spec"])[:12]}
    if not spec_keys or not sources["prd"]:
        raise RuntimeError("规格书或 PRD 缺少可关联的功能正文。")
    match_fields = {"title": STRING, "need": STRING, "prdLine": POSITION, "decisionLine": POSITION}
    schema = schema_for({
        "matches": schema_for({
            key: schema_for({**match_fields, "verificationLine": POSITION}) for key in spec_keys
        }),
        "unmatched": {"type": "array", "maxItems": 4, "items": schema_for(match_fields)},
    })
    prompt = (
        "将 PRD 拆成独立可验收需求。matches 中每个 spec_N 对应规格书第 N 行。"
        "逐条判断该规格描述的能力是否在 PRD 中提出，填 prdLine；同一 PRD 行提出多个能力时"
        "可同时匹配多个 spec_N，每项只描述对应规格的能力。填同一能力的 decisionLine 和 verificationLine。"
        "没有对应内容时行号为 0，未在 PRD 出现的规格不要当成需求。"
        "unmatched 只列 PRD 有明确要求而所有规格都未覆盖的能力。"
        "title 和 need 用简体中文，写清功能及对象。版本、配列和文件出处为背景。\n"
        + json.dumps({"scope": scope, "specKeys": spec_keys, "sources": sources}, ensure_ascii=False)
    )
    _, result = complete(prompt, schema, context=20480, prediction=2700)
    matches, unmatched = result.get("matches"), result.get("unmatched")
    if not isinstance(matches, dict) or not isinstance(unmatched, list):
        raise RuntimeError("本机 AI 未生成可读取的规格关联，请检查 PRD 后重试。")
    rows = []
    retried = 0
    for key, number in spec_keys.items():
        item = matches.get(key)
        if retried < 3 and (
            not isinstance(item, dict)
            or item.get("prdLine") not in sources["prd"]
            or item.get("verificationLine") not in sources["verification"]
            or not clean(item.get("title"), 75)
        ):
            retry = retry_mapping(scope, sources, number, {**match_fields, "verificationLine": POSITION})
            if retry is not None:
                retried += 1
                if retry.get("prdLine") in sources["prd"]:
                    item = retry
        rows.append((item, number))
    return rows + [
        (item, 0) for item in unmatched[:4]
    ]


def proposed_tests(scope, requirements):
    test_shape = schema_for({
        "title": STRING,
        "steps": {"type": "array", "items": STRING, "minItems": 2, "maxItems": 4},
    })
    plan = {item["id"]: {
        "requirement": item["text"],
        "spec": item["spec"]["quote"] if item["spec"] else "",
        "verification": item["verification"]["quote"] if item["verification"] else "",
    } for item in requirements}
    prompt = (
        "为每个需求 ID 拟一项独立的待执行测试。只测当前 ID 的能力。"
        "根据该项规格和验证依据，写测试标题及 2 至 4 个具体操作与观察步骤。"
        "若规格列出多种模式或多项设置，必须逐一测试并记录实际输入或回读值。"
        "列出需读回的配置或需观察的事件，不添加材料没有的数值，"
        "不声称测试已经执行或通过。用简体中文。\n"
        + json.dumps({"scope": scope, "testInputs": plan}, ensure_ascii=False)
    )
    model, result = complete(
        prompt, schema_for({key: test_shape for key in plan}), context=8192, prediction=2500,
    )
    for item in requirements:
        proposed = result.get(item["id"])
        if not isinstance(proposed, dict):
            raise RuntimeError("AI 未为所有需求拟出测试用例，请重新分析。")
        title, steps = clean(proposed.get("title"), 100), proposed.get("steps")
        steps = [step for entry in steps[:4] if (step := clean(entry, 180))] if isinstance(steps, list) else []
        if not title or len(steps) < 2:
            raise RuntimeError("AI 返回的测试用例缺少可执行步骤，请重新分析。")
        verification = item["verification"]
        if verification:
            steps = [f"按验证依据覆盖所列操作：{verification['quote']}", *steps[:3]]
        item["test"] = {
            "title": title, "steps": steps,
            "expected": item["spec"]["quote"] if item["spec"] else "补充规格和验收条件后确定。",
            "status": "待执行",
        }
    return model


def analyze_launch(scope, documents):
    sources = compact_sources(scope, documents)
    matches = match_capabilities(scope, sources)
    requirements = []
    facts = []
    seen = set()
    for item, spec_line in matches:
        if not isinstance(item, dict):
            continue
        requirement = ref(documents, sources, "prd", item.get("prdLine"))
        title = clean(item.get("title"), 75)
        text = clean(item.get("need"), 260)
        if not requirement or not title or not text:
            continue
        decision = ref(documents, sources, "decision", item.get("decisionLine"))
        spec = ref(documents, sources, "spec", spec_line)
        verification = ref(documents, sources, "verification", item.get("verificationLine")) if spec else None
        key = (requirement["line"], spec["line"] if spec else title)
        if key in seen:
            continue
        seen.add(key)
        req_id = f"REQ-{len(requirements) + 1:02d}"
        requirements.append({
            "id": req_id, "title": title, "text": text,
            "citations": [citation for citation in (decision, requirement) if citation],
            "spec": spec, "verification": verification,
        })
        if spec and verification:
            facts.append({
                "id": f"FACT-{len(facts) + 1:02d}",
                "title": title,
                "text": spec["quote"],
                "requirementId": req_id,
                "citations": [spec, verification],
            })
        if len(requirements) == 8:
            break
    if not requirements:
        raise RuntimeError("AI 未定位可追溯的需求及用例。请将 PRD 写明具体能力或验收条件后重试。")
    model = proposed_tests(scope, requirements)
    return {
        "model": model, "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": f"已拆出 {len(requirements)} 条需求和对应的待执行用例。{len(facts)} 条规格具备引用依据，可提交事实审核。",
        "requirements": requirements, "facts": facts,
    }


def generate_launch_drafts(scope, approved_facts):
    basis = [
        {"id": item["id"], "title": item.get("title", ""), "fact": item["text"],
         "reference": next((cite["quote"] for cite in item["citations"] if cite["kind"] == "verification"), "")}
        for item in approved_facts
    ]
    schema = schema_for({
        "headlines": schema_for({channel: STRING for channel in CHANNEL_LABELS}),
        "topics": schema_for({item["id"]: schema_for({"heading": STRING, "question": STRING}) for item in basis}),
    })
    prompt = (
        "根据审核通过的事实写四类渠道的栏目文案。headlines 下分别填写 briefing 新品宣讲、"
        "product_page 产品页面、manual 说明书、faq 售后问答的标题。"
        "topics 的键为事实 ID，每个事实生成简短的功能小标题 heading 与用户会问的问题 question。"
        "全部用简体中文，标题不超过 25 字，问题不超过 55 字。"
        "只写主题和问题，正文由审核过的原文填充。避免性能承诺、比较性卖点、参数和额外功能。\n"
        + json.dumps({"scope": scope, "approvedFacts": basis}, ensure_ascii=False)
    )
    model, result = complete(prompt, schema, context=8192, prediction=1100)
    headings = result.get("headlines")
    topics = result.get("topics")
    if not isinstance(headings, dict) or not isinstance(topics, dict):
        raise RuntimeError("本机 AI 未生成完整渠道文案，请重试。")
    product = scope["productName"]
    version = scope["productVersion"]
    fact_ids = [item["id"] for item in basis]
    channels = {}
    for channel, label in CHANNEL_LABELS.items():
        title = clean(headings.get(channel), 85) or f"{product} {label}"
        entries = [f"适用产品：{product} · {version}"]
        if channel == "briefing":
            entries.append("开场：以下介绍本版产品已经审核的功能。")
        elif channel == "product_page":
            entries.append("产品功能")
        for index, item in enumerate(basis, 1):
            topic = topics.get(item["id"])
            if not isinstance(topic, dict):
                topic = {}
            heading = clean(topic.get("heading"), 75) or item["title"] or f"功能 {index}"
            question = clean(topic.get("question"), 130) or f"{heading}如何使用？"
            if channel == "faq":
                question = question.removeprefix("问：").rstrip("？?") + "？"
                entries.append(f"问：{question}\n答：{item['fact']}")
            elif channel == "manual":
                entries.append(f"{index}. {heading}\n{item['fact']}\n使用依据：{item['reference']}")
            elif channel == "briefing":
                entries.append(f"宣讲要点 {index} · {heading}\n讲稿：{item['fact']}")
            else:
                entries.append(f"{heading}\n{item['fact']}")
        channels[channel] = {"title": title, "text": "\n\n".join(entries), "factIds": fact_ids}
    return {"model": model, "at": datetime.now().astimezone().isoformat(timespec="seconds"), "channels": channels}
