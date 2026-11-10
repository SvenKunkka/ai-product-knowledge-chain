#!/usr/bin/env python3
"""Local product knowledge workflow with demo and uploaded materials."""

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from functools import partial
from hashlib import sha256
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit

import feedback_workflow as feedback
from fixture import FIXTURE
import launch_workflow as launch
from upload_documents import DocumentError, KINDS, MAX_REQUEST, parse_document

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parents[1] / "work" if ROOT.parent.name == "outputs" else ROOT
DEFAULT_DB = WORK / "ai-product-knowledge.sqlite3"
ROLES = {
    "product": "产品负责人",
    "engineering": "研发负责人",
    "qa": "测试负责人",
    "content": "内容负责人",
}
CHANNELS = {"manual": "说明书", "faq": "售后 FAQ"}
BEIJING = timezone(timedelta(hours=8))
UPLOAD_EDITABLE = {"awaiting_documents", "ready_for_analysis", "awaiting_evidence", "ready_for_review"}


class RequestError(Exception):
    def __init__(self, message, status=HTTPStatus.CONFLICT):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(BEIJING).isoformat(timespec="seconds")


def record(state, label, detail):
    state["history"].append({"at": now(), "label": label, "detail": detail})


def case_id(number):
    return f"FWC-{number:03d}"


def case_channels(state):
    if state.get("mode") == "feedback":
        return {}
    return launch.CHANNELS if state.get("mode") == "launch" else CHANNELS


def create_run(db, scope=None, mode="upload", product_snapshot=None):
    number = db.execute("INSERT INTO runs(state) VALUES ('{}')").lastrowid
    state = {
        "caseId": case_id(number),
        "status": "awaiting_evidence",
        "evidence": None,
        "approvals": {},
        "reviewRevision": None,
        "reviewContents": None,
        "channels": {
            name: {
                "status": "pending",
                "attempts": 0,
                "receipt": None,
                "detail": "等待审核后模拟发布",
                "actualVersion": None,
            }
            for name in case_channels({"mode": mode})
        },
        "history": [],
        "release": None,
        "aiAnalysis": None,
    }
    if mode == "feedback":
        state.update(mode="feedback", scope=scope, documents={}, productSnapshot=product_snapshot)
        feedback.after_upload(state)
        record(
            state, "创建售后反馈项目",
            f'{scope["productName"]} · {scope["productVersion"]} · 已关联产品档案 {scope["productCaseId"]}。',
        )
    elif mode == "launch":
        state.update(mode="launch", scope=scope, documents={})
        launch.after_upload(state)
        record(state, "创建新品项目", f'{scope["productName"]} · {scope["productVersion"]}，等待决策纪要、PRD、规格和验证依据。')
    elif scope:
        state.update(mode="upload", scope=scope, documents={}, status="awaiting_documents")
        record(state, "创建上传变更", f'{scope["productName"]} · {scope["oldFirmware"]} → {scope["newFirmware"]}，等待四份资料。')
    else:
        record(state, "创建固件变更演练", "已锁定北辰 M2 · R1 · 固件 1.5.0，等待目标版本的实测证据。")
    save_run(db, number, state)
    return state


def save_run(db, number, state):
    db.execute(
        "UPDATE runs SET state = ? WHERE id = ?",
        (json.dumps(state, ensure_ascii=False), number),
    )


def latest_run(db, expected_id=None):
    number, raw_state = db.execute(
        "SELECT id, state FROM runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if expected_id is not None and expected_id != case_id(number):
        raise RequestError("当前演练已切换，请刷新页面再继续。")
    return number, json.loads(raw_state)


def initialize(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY,
                state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS simulated_deliveries (
                run_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                version TEXT NOT NULL,
                firmware TEXT NOT NULL,
                content TEXT NOT NULL,
                receipt TEXT NOT NULL,
                PRIMARY KEY (run_id, channel)
            );
            CREATE TABLE IF NOT EXISTS upload_blobs (
                digest TEXT PRIMARY KEY,
                content BLOB NOT NULL,
                lines TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS upload_document_versions (
                run_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                digest TEXT NOT NULL,
                name TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                PRIMARY KEY (run_id, kind, digest),
                FOREIGN KEY (run_id) REFERENCES runs(id),
                FOREIGN KEY (digest) REFERENCES upload_blobs(digest)
            );
            """
        )
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM runs LIMIT 1").fetchone():
            create_run(db)


def load_run(db, requested_id):
    if not isinstance(requested_id, str) or re.fullmatch(r"FWC-[0-9]{3,19}", requested_id) is None:
        raise RequestError("找不到这次演练。", HTTPStatus.NOT_FOUND)
    number = int(requested_id[4:])
    if number > 2**63 - 1 or case_id(number) != requested_id:
        raise RequestError("找不到这次演练。", HTTPStatus.NOT_FOUND)
    row = db.execute("SELECT state FROM runs WHERE id = ?", (number,)).fetchone()
    if row is None:
        raise RequestError("找不到这次演练。", HTTPStatus.NOT_FOUND)
    return number, json.loads(row[0])


def read_run(path, requested_id=None, *, include_current=False):
    with closing(sqlite3.connect(path)) as db:
        db.execute("BEGIN")
        latest_number, latest_state = latest_run(db)
        if requested_id is None:
            return (latest_state, True) if include_current else latest_state
        number, state = load_run(db, requested_id)
        return (state, number == latest_number) if include_current else state


def feedback_parent(db, current, requested_id):
    if requested_id is None:
        if current.get("mode") == "launch":
            return current
        if current.get("mode") != "feedback":
            raise RequestError("请选择已完成发布回读的新品档案。")
        requested_id = current["scope"]["productCaseId"]
    return load_run(db, requested_id)[1]


def read_scope(request):
    values = [request.get(key) for key in ("productName", "oldFirmware", "newFirmware")]
    if not all(isinstance(value, str) for value in values):
        raise RequestError("请填写脱敏产品名和新旧固件版本。", HTTPStatus.BAD_REQUEST)
    name, old, new = (value.strip() for value in values)
    if not name or len(name) > 100 or not name.isprintable():
        raise RequestError("请填写 1 至 100 字的脱敏产品名。", HTTPStatus.BAD_REQUEST)
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,47}", version) for version in (old, new)):
        raise RequestError("固件版本请用 1 至 48 位字母、数字、点、下划线、加号或短横线。", HTTPStatus.BAD_REQUEST)
    if old.casefold() == new.casefold():
        raise RequestError("新旧固件版本不能相同。", HTTPStatus.BAD_REQUEST)
    return {"productName": name, "oldFirmware": old, "newFirmware": new}


def require_editable_upload(state):
    if state.get("mode") == "feedback":
        if state["status"] not in feedback.EDITABLE:
            raise RequestError("售后资料已锁定。审核中请先退回，已生成草稿请新建售后项目。")
        return feedback.DOCUMENTS
    if state.get("mode") == "launch":
        if state["status"] not in launch.EDITABLE:
            raise RequestError("新品资料已锁定。审核中请先退回，已发布请新建新品项目。")
        return launch.DOCUMENTS
    if state.get("mode") != "upload":
        raise RequestError("请先新建一张上传变更单。")
    if state["status"] not in UPLOAD_EDITABLE:
        raise RequestError("当前资料已锁定。审核中请先退回，已发布请新建变更单。")
    return KINDS


def upload_document(path, requested_id, request):
    with closing(sqlite3.connect(path)) as db:
        _, state = latest_run(db, requested_id)
        kinds = require_editable_upload(state)
    try:
        document, raw = parse_document(request.get("kind"), request.get("name"), request.get("contentBase64"), kinds=kinds)
    except DocumentError as exc:
        raise RequestError(str(exc), exc.status) from exc

    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        number, state = latest_run(db, requested_id)
        require_editable_upload(state)
        kind = document["kind"]
        digest = document["digest"]
        current = state["documents"].get(kind)
        if current and current["digest"] == digest:
            return state
        document["uploadedAt"] = now()
        db.execute(
            "INSERT OR IGNORE INTO upload_blobs(digest, content, lines) VALUES (?, ?, ?)",
            (digest, raw, json.dumps(document["lines"], ensure_ascii=False)),
        )
        db.execute(
            "INSERT OR IGNORE INTO upload_document_versions(run_id, kind, digest, name, uploaded_at) VALUES (?, ?, ?, ?, ?)",
            (number, kind, digest, document["name"], document["uploadedAt"]),
        )
        state["documents"][kind] = document
        if state.get("mode") == "feedback":
            feedback.after_upload(state)
        elif state.get("mode") == "launch":
            launch.after_upload(state)
        else:
            state.update(
                status="ready_for_analysis" if state["documents"].keys() == KINDS.keys() else "awaiting_documents",
                aiAnalysis=None, evidence=None, approvals={}, reviewRevision=None, reviewContents=None,
            )
            state.pop("fixture", None)
        detail = f'{document["name"]} · {len(document["lines"])} 行可引用正文。'
        if current:
            detail += "已保留旧文件版本，需重新分析。"
        record(state, f'已{"替换" if current else "上传"}{kinds[kind]}', detail)
        save_run(db, number, state)
        return state


def source_hashes(state):
    return {kind: doc["digest"] for kind, doc in state.get("documents", {}).items()}


def run_fixture(state):
    if state.get("mode") != "upload":
        return FIXTURE
    if state.get("fixture"):
        return state["fixture"]
    scope = state["scope"]
    return {
        "product": {"name": scope["productName"], "sku": "待提取", "hardware": "待提取", "region": "待提取"},
        "change": {
            "title": "上传资料固件变更", "oldFirmware": scope["oldFirmware"], "newFirmware": scope["newFirmware"],
            "before": "等待分析", "after": "等待分析", "decisionId": "待提取", "decisionReason": "等待分析",
            "specId": "待提取", "caseId": "待提取", "expected": "等待分析",
        },
        "report": {"id": "待提取", "title": "测试报告", "firmware": scope["newFirmware"],
                   "result": "待核对", "summary": "等待分析", "source": "上传资料"},
        "drafts": {kind: {"before": "等待分析", "after": "等待分析", "source": KINDS[kind]} for kind in CHANNELS},
        "impact": [],
    }


def add_evidence(state, request):
    if state.get("mode") == "upload":
        raise RequestError("上传变更需从目标固件的实际测试报告提取证据。")
    report = FIXTURE["report"]
    if request.get("firmware") != report["firmware"]:
        raise RequestError("实测报告必须覆盖固件 1.5.0。旧版报告不能用于本次变更。")
    if state["evidence"] is not None:
        return
    state["evidence"] = {**report, "at": now()}
    state["status"] = "ready_for_review"
    record(state, "补齐实测证据", f'{report["id"]} · 固件 {report["firmware"]} · {report["result"]}')


def draft_contents(state):
    drafts = run_fixture(state)["drafts"]
    return {channel: drafts[channel]["after"] for channel in CHANNELS}


def submit_review(state, _request):
    if state["status"] == "in_review":
        return
    if state["status"] != "ready_for_review":
        raise RequestError("请补齐适用版本的实测报告，再提交审核。")
    evidence = state["evidence"]
    contents = draft_contents(state)
    source = json.dumps([evidence, contents, source_hashes(state)], sort_keys=True, ensure_ascii=False).encode("utf-8")
    state["reviewRevision"] = f'{state["caseId"]}/{evidence["id"]}/{sha256(source).hexdigest()[:12]}'
    state["reviewContents"] = contents
    state["status"] = "in_review"
    record(state, "提交四方审核", f'本轮审核绑定固件 {evidence["firmware"]} 的实测报告及两份渠道草稿。')


def review_role(request):
    role = request.get("role")
    if not isinstance(role, str) or role not in ROLES:
        raise RequestError("请选择有效的演示审核角色。", HTTPStatus.BAD_REQUEST)
    return role


def approve(state, request):
    role = review_role(request)
    if role in state["approvals"]:
        return
    if state["status"] != "in_review":
        raise RequestError("这张变更单尚未进入审核。")
    label = ROLES[role]
    state["approvals"][role] = {"at": now(), "label": label, "revision": state["reviewRevision"]}
    record(state, f"{label}通过", "已确认本轮待审差异和对应实测证据。")
    if state["approvals"].keys() == ROLES.keys():
        state["status"] = "approved"
        record(state, "审核完成", "四个演示角色均已通过，可以锁定模拟发布版本。")


def reject(state, request):
    role = review_role(request)
    returnable = {"in_review", "approved"} if state.get("mode") == "upload" else {"in_review"}
    if state["status"] not in returnable:
        raise RequestError("这张变更单当前没有待退回的审核。")
    state["status"] = "ready_for_review"
    state["approvals"] = {}
    state["reviewRevision"] = None
    state["reviewContents"] = None
    record(state, f"{ROLES[role]}退回", "保留实测证据，清空本轮审批。确认后可重新送审。")


def deliver(db, number, state, channel):
    release = state["release"]
    version = release["version"]
    product_version = release.get("productVersion")
    target_version = product_version or release["firmware"]
    contents = release.get("contents") or draft_contents(state)
    content = contents[channel]
    receipt = f'{release["id"]}-{channel.upper()}'
    db.execute(
        """
        INSERT INTO simulated_deliveries(run_id, channel, version, firmware, content, receipt)
        VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(run_id, channel) DO NOTHING
        """,
        (number, channel, version, target_version, content, receipt),
    )
    result = db.execute(
        """
        SELECT version, firmware, content, receipt
        FROM simulated_deliveries WHERE run_id = ? AND channel = ?
        """,
        (number, channel),
    ).fetchone()
    if result != (version, target_version, content, receipt):
        raise RequestError("模拟渠道回读与锁定版本不一致，请检查本地数据。", HTTPStatus.SERVICE_UNAVAILABLE)
    entry = state["channels"][channel]
    entry.update(
        status="verified",
        attempts=entry["attempts"] + 1,
        receipt=result[3],
        detail=f'已回读{"产品版本" if product_version else "固件"} {result[1]} 的模拟发布内容',
        actualVersion=result[0],
    )
    record(state, f"{case_channels(state)[channel]}回读通过", f"{version} · 回执 {receipt}")


def publish(db, number, state, _request):
    if state["release"] is not None:
        return
    if state["status"] != "approved":
        raise RequestError("四个演示角色全部通过后才可以模拟发布。")
    is_launch = state.get("mode") == "launch"
    target_key = "productVersion" if is_launch else "firmware"
    target_version = state["scope"]["productVersion"] if is_launch else run_fixture(state)["change"]["newFirmware"]
    state["release"] = {
        "id": f"REL-{number:03d}",
        "version": f"{target_version}-r{number:03d}",
        target_key: target_version,
        "at": now(),
        "contents": state.get("reviewContents") or draft_contents(state),
        "sourceHashes": source_hashes(state),
    }
    if is_launch:
        state["release"].update(
            approvedFactIds=[item["id"] for item in state["approvedFacts"]],
            channelFactIds={key: draft["factIds"] for key, draft in state["launchDrafts"]["channels"].items()},
        )
    record(state, "锁定发布版本", f'{state["release"]["version"]} · 仅用于本机模拟渠道。')
    for channel in case_channels(state):
        if channel != "faq":
            deliver(db, number, state, channel)
    state["channels"]["faq"].update(
        status="failed",
        attempts=1,
        detail="演练预设的首次渠道超时，等待单独重试。",
    )
    record(state, "售后 FAQ 首次模拟失败", "模拟渠道未写入。其他成功渠道的回执已保留。" if is_launch else "模拟渠道未写入。说明书回执已保留。")
    state["status"] = "publication_partial"


def retry_channel(db, number, state, request):
    channel = request.get("channel")
    if channel != "faq":
        raise RequestError("本轮仅支持重试失败的售后 FAQ 渠道。", HTTPStatus.BAD_REQUEST)
    status = state["channels"][channel]["status"]
    if status == "verified":
        return
    if status != "failed":
        raise RequestError("售后 FAQ 当前没有失败的发布需要重试。")
    deliver(db, number, state, channel)
    state["status"] = "published"
    if state.get("mode") == "launch":
        record(state, "四渠道模拟发布完成", "新品宣讲、产品页面、说明书和售后 FAQ 均已回读到锁定版本。")
    else:
        record(state, "双渠道模拟发布完成", "说明书和售后 FAQ 均已回读到锁定版本。")


ACTIONS = {
    "add_evidence": add_evidence,
    "submit_review": submit_review,
    "approve": approve,
    "reject": reject,
}
DELIVERY_ACTIONS = {"publish": publish, "retry_channel": retry_channel}


def read_upload_analysis(result, state):
    fixture, analysis, evidence = (result[key] for key in ("fixture", "aiAnalysis", "evidence"))
    scope = state["scope"]
    fallback = run_fixture(state)
    if not isinstance(analysis, dict) or not isinstance(analysis.get("summary"), str):
        raise ValueError("invalid upload analysis")
    if not isinstance(fixture, dict):
        raise ValueError("invalid upload fixture")
    for kind in CHANNELS:
        draft = fixture["drafts"][kind]
        if not all(isinstance(draft.get(field), str) and draft[field].strip() for field in ("before", "after", "source")):
            raise ValueError("invalid upload draft")
    fixture = {
        **fallback, **fixture,
        "product": {**fallback["product"], **fixture.get("product", {}), "name": scope["productName"]},
        "change": {**fallback["change"], **fixture.get("change", {}),
                   "oldFirmware": scope["oldFirmware"], "newFirmware": scope["newFirmware"]},
    }
    if evidence is not None:
        if not isinstance(evidence, dict) or not all(
            isinstance(evidence.get(key), str) and evidence[key].strip()
            for key in ("id", "firmware", "title", "result", "summary", "source")
        ):
            raise ValueError("invalid upload evidence")
        if evidence["firmware"] != scope["newFirmware"]:
            raise ValueError("evidence scope mismatch")
    return fixture, analysis, evidence


def analysis_action(path, requested_id):
    if not os.environ.get("PRODUCT_KNOWLEDGE_OLLAMA_URL"):
        raise RequestError("本地模型尚未启用，无法从上传资料生成分析。")
    with closing(sqlite3.connect(path)) as db:
        _, state = latest_run(db, requested_id)
        if state.get("mode") == "feedback":
            raise RequestError("请在售后工作区分析反馈。")
        if state.get("mode") == "launch":
            raise RequestError("请在新品工作区运行需求拆解。")
        if state.get("aiAnalysis"):
            return state
    upload = state.get("mode") == "upload"
    hashes = source_hashes(state)
    if upload and (state["status"] != "ready_for_analysis" or hashes.keys() != KINDS.keys()):
        raise RequestError("请先上传可读取的规格书、测试报告、说明书和售后 FAQ。")
    try:
        if upload:
            from upload_analysis import analyze_upload

            result = analyze_upload(state["scope"], state["documents"])
            fixture, analysis, evidence = read_upload_analysis(result, state)
        else:
            from local_analysis import analyze

            analysis = analyze(FIXTURE)
    except RuntimeError as exc:
        message = str(exc)[:320] or "本地模型暂时无法生成分析，请稍后重试。"
        raise RequestError(message, HTTPStatus.SERVICE_UNAVAILABLE) from exc
    except Exception as exc:
        raise RequestError(
            "本地模型暂时无法生成有效分析。请核对资料后重试。",
            HTTPStatus.SERVICE_UNAVAILABLE,
        ) from exc
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        number, state = latest_run(db, requested_id)
        if upload and source_hashes(state) != hashes:
            raise RequestError("分析期间资料有更新，请对当前文件重新分析。")
        if not state.get("aiAnalysis"):
            state["aiAnalysis"] = analysis
            if upload:
                state.update(
                    fixture=fixture,
                    evidence=evidence,
                    status="ready_for_review" if evidence else "awaiting_evidence",
                )
                if evidence:
                    record(state, "本地 AI 分析完成", f'已生成影响与渠道差异，实测来源覆盖固件 {evidence["firmware"]}，待四方审核。')
                else:
                    record(state, "本地 AI 分析完成 · 待补证", "已生成影响与渠道差异，未找到足够的目标固件实测证据。")
            else:
                record(state, "本地 AI 生成复核建议", "建议供审核人参考，未改动规格、实测或审批状态。")
            save_run(db, number, state)
        return state


def launch_model_action(path, requested_id, action):
    if not os.environ.get("PRODUCT_KNOWLEDGE_OLLAMA_URL"):
        raise RequestError("本机模型尚未启用，无法分析新品资料。")
    analyzing = action == "analyze_launch"
    result_key = "launchAnalysis" if analyzing else "launchDrafts"
    required_status = "ready_for_launch_analysis" if analyzing else "launch_facts_approved"
    with closing(sqlite3.connect(path)) as db:
        _, state = latest_run(db, requested_id)
    if state.get("mode") != "launch":
        raise RequestError("请先新建一个新品项目。")
    if state[result_key] is not None:
        return state
    if state["status"] != required_status:
        raise RequestError(
            "请先上传四类新品资料。" if analyzing else "需要产品、研发和测试三个角色批准事实后才能生成渠道内容。"
        )
    hashes = source_hashes(state)
    fact_revision = state["factReviewRevision"]
    history_length = len(state["history"])
    try:
        import launch_analysis

        if analyzing:
            result = launch_analysis.analyze_launch(state["scope"], state["documents"])
            normalized = launch.read_analysis(result, state["documents"])
        else:
            result = launch_analysis.generate_launch_drafts(state["scope"], state["approvedFacts"])
            normalized = launch.read_drafts(result, state["approvedFacts"])
    except RuntimeError as exc:
        message = str(exc)[:320] or "本地模型暂时无法完成新品任务，请稍后重试。"
        raise RequestError(message, HTTPStatus.SERVICE_UNAVAILABLE) from exc
    except (AttributeError, ImportError, KeyError, TypeError, ValueError) as exc:
        raise RequestError("模型返回的新品结果缺少有效原文引用，请核对资料后重试。", HTTPStatus.SERVICE_UNAVAILABLE) from exc

    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        number, current = latest_run(db, requested_id)
        if current["scope"] != state["scope"] or source_hashes(current) != hashes:
            raise RequestError("执行期间资料有更新，请对当前文件重新执行。")
        if not analyzing and current["factReviewRevision"] != fact_revision:
            raise RequestError("执行期间批准事实有更新，请重新生成草稿。")
        if current[result_key] is not None:
            return current
        if current["status"] != required_status or len(current["history"]) != history_length:
            raise RequestError("执行期间任务阶段有变化，请刷新后重试。")
        current[result_key] = normalized
        if analyzing:
            current["factReviewRevision"] = launch.revision(current, "facts", normalized["facts"])
            current["status"] = "launch_fact_review"
            record(
                current, "完成新品需求拆解",
                f'找到 {len(normalized["requirements"])} 项需求、'
                f'{len(normalized["facts"])} 条可审核事实；测试用例均待执行。',
            )
        else:
            current["status"] = "launch_content_review"
            record(current, "生成四类新品草稿", "内容引用已批准事实，等待内容负责人审核。")
        save_run(db, number, current)
        return current


def feedback_model_action(path, requested_id, action):
    if not os.environ.get("PRODUCT_KNOWLEDGE_OLLAMA_URL"):
        raise RequestError("本机模型尚未启用，无法分析售后资料。")
    analyzing = action == "analyze_feedback"
    result_key = "feedbackAnalysis" if analyzing else "feedbackActions"
    required_status = "ready_for_feedback_analysis" if analyzing else "feedback_approved"
    with closing(sqlite3.connect(path)) as db:
        _, state = latest_run(db, requested_id)
    if state.get("mode") != "feedback":
        raise RequestError("请先新建一个售后反馈项目。")
    if state[result_key] is not None:
        return state
    if state["status"] != required_status:
        raise RequestError(
            "请先上传售后反馈和核对依据。" if analyzing else "请逐项审核反馈后再生成处理草稿。"
        )
    hashes = source_hashes(state)
    history_length = len(state["history"])
    scope, snapshot = state["scope"], state["productSnapshot"]
    try:
        import feedback_analysis

        if analyzing:
            result = feedback_analysis.analyze_feedback(scope, snapshot, state["documents"])
            normalized = feedback.read_analysis(result, state["documents"], snapshot)
        else:
            result = feedback_analysis.generate_feedback_actions(scope, snapshot, state["approvedFeedback"])
            normalized = feedback.read_actions(result, state["approvedFeedback"], scope)
    except RuntimeError as exc:
        message = str(exc)[:320] or "本地模型暂时无法完成售后任务，请稍后重试。"
        raise RequestError(message, HTTPStatus.SERVICE_UNAVAILABLE) from exc
    except (AttributeError, ImportError, KeyError, TypeError, ValueError) as exc:
        raise RequestError("模型返回的售后结果与资料或审核内容不一致，请核对后重试。", HTTPStatus.SERVICE_UNAVAILABLE) from exc

    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        number, current = latest_run(db, requested_id)
        if source_hashes(current) != hashes or current["scope"] != scope:
            raise RequestError("执行期间售后资料有更新，请对当前文件重新执行。")
        if current[result_key] is not None:
            return current
        if current["status"] != required_status or len(current["history"]) != history_length:
            raise RequestError("执行期间审核或任务阶段有变化，请刷新后重试。")
        current[result_key] = normalized
        if analyzing:
            current["feedbackRevision"] = launch.revision(
                current, "feedback", [snapshot["releaseVersion"], normalized["items"]]
            )
            current["status"] = "feedback_review"
            record(current, "完成售后反馈分析", f'找到 {len(normalized["items"])} 条待人工审核的反馈。')
        else:
            current["status"] = "feedback_actions_generated"
            record(current, "生成售后处理草稿", f'按已审核反馈生成 {len(normalized["actions"])} 项本机草稿。')
        save_run(db, number, current)
        return current


def apply_action(path, request):
    action = request.get("action")
    requested_id = request.get("caseId")
    if not isinstance(action, str) or (
        action not in ACTIONS and action not in DELIVERY_ACTIONS
        and action not in launch.REVIEW_ACTIONS
        and action not in feedback.REVIEW_ACTIONS
        and action not in {"new_run", "new_upload_run", "new_launch_run", "upload_document", "run_analysis",
                           "analyze_launch", "generate_launch_drafts", "new_feedback_run",
                           "analyze_feedback", "generate_feedback_actions"}
    ):
        raise RequestError("无法识别这项操作。", HTTPStatus.BAD_REQUEST)
    if not isinstance(requested_id, str) and not (action == "new_run" and requested_id is None):
        raise RequestError("缺少演练编号，请刷新页面后重试。", HTTPStatus.BAD_REQUEST)
    if action == "run_analysis":
        return analysis_action(path, requested_id)
    if action in {"analyze_launch", "generate_launch_drafts"}:
        return launch_model_action(path, requested_id, action)
    if action in {"analyze_feedback", "generate_feedback_actions"}:
        return feedback_model_action(path, requested_id, action)
    if action == "upload_document":
        return upload_document(path, requested_id, request)

    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        number, state = latest_run(db, requested_id)
        if action == "new_run":
            return create_run(db)
        if action == "new_upload_run":
            return create_run(db, read_scope(request))
        if action == "new_launch_run":
            return create_run(db, launch.read_scope(request), mode="launch")
        if action == "new_feedback_run":
            parent = feedback_parent(db, state, request.get("productCaseId"))
            snapshot = feedback.snapshot_product(parent)
            scope = {"productName": snapshot["productName"], "productVersion": snapshot["productVersion"],
                     "productCaseId": snapshot["caseId"]}
            return create_run(db, scope, mode="feedback", product_snapshot=snapshot)
        if action in feedback.REVIEW_ACTIONS:
            if state.get("mode") != "feedback":
                raise RequestError("当前任务并非售后反馈项目。")
            feedback.REVIEW_ACTIONS[action](state, request, record, now)
        elif state.get("mode") == "feedback":
            raise RequestError("售后反馈只生成本机处理草稿，请使用售后审核操作。")
        elif action in launch.REVIEW_ACTIONS:
            if state.get("mode") != "launch":
                raise RequestError("当前任务并非新品项目。")
            launch.REVIEW_ACTIONS[action](state, request, record, now)
        elif action in ACTIONS:
            if state.get("mode") == "launch":
                raise RequestError("请使用新品审核操作。")
            ACTIONS[action](state, request)
        else:
            DELIVERY_ACTIONS[action](db, number, state, request)
        save_run(db, number, state)
        return state


def payload(state, is_current=True):
    mode = "local_ai_available" if os.environ.get("PRODUCT_KNOWLEDGE_OLLAMA_URL") else "deterministic_demo"
    if state.get("mode") in {"launch", "feedback"}:
        return {**state, "fixture": None, "modelMode": mode, "isCurrent": is_current}
    fixture = run_fixture(state)
    release = state.get("release") or {}
    contents = release.get("contents") or state.get("reviewContents")
    if contents:
        drafts = {
            channel: {**draft, "after": contents[channel]}
            for channel, draft in fixture["drafts"].items()
        }
        fixture = {**fixture, "drafts": drafts}
    return {"aiAnalysis": None, "mode": "legacy", "documents": {}, **state,
            "fixture": fixture, "modelMode": mode, "isCurrent": is_current}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, db_path, **kwargs):
        self.db_path = db_path
        super().__init__(*args, directory=str(ROOT / "web"), **kwargs)

    def parse_request(self):
        if not super().parse_request():
            return False
        port = self.server.server_port
        allowed = {"127.0.0.1", "localhost", f"127.0.0.1:{port}", f"localhost:{port}"}
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].strip().lower() not in allowed:
            self.send_error(HTTPStatus.FORBIDDEN, "Loopback host required")
            return False
        return True

    def send_json(self, body, status=HTTPStatus.OK):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/api/health":
            self.send_json({"ok": True, "service": "product-knowledge-demo"})
        elif url.path == "/api/demo":
            try:
                requested_id = parse_qs(url.query).get("caseId", [None])[0]
                state, is_current = read_run(self.db_path, requested_id, include_current=True)
                self.send_json(payload(state, is_current))
            except RequestError as exc:
                self.send_json({"error": str(exc)}, exc.status)
        elif url.path.startswith("/api/"):
            self.send_json({"error": "找不到请求的页面。"}, HTTPStatus.NOT_FOUND)
        else:
            super().do_GET()

    def list_directory(self, _path):
        self.send_error(HTTPStatus.NOT_FOUND)
        return None

    def read_request(self):
        if self.headers.get_content_type() != "application/json":
            raise RequestError("请发送 JSON 操作请求。", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > MAX_REQUEST:
                raise RequestError("单份资料不得超过 4 MiB。", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            if size <= 0:
                raise ValueError
            request = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RequestError("操作请求格式不正确。", HTTPStatus.BAD_REQUEST) from exc
        if not isinstance(request, dict):
            raise RequestError("操作请求格式不正确。", HTTPStatus.BAD_REQUEST)
        return request

    def do_POST(self):
        if urlsplit(self.path).path != "/api/actions":
            self.send_json({"error": "找不到请求的操作。"}, HTTPStatus.NOT_FOUND)
            return
        origin = self.headers.get("Origin")
        allowed_origins = {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }
        if origin is not None and origin not in allowed_origins:
            self.send_json({"error": "请从本机原型页面提交操作。"}, HTTPStatus.FORBIDDEN)
            return
        try:
            self.send_json(payload(apply_action(self.db_path, self.read_request())))
        except (RequestError, launch.LaunchError, feedback.FeedbackError) as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except sqlite3.Error:
            self.send_json({"error": "本地数据暂时不可用，请稍后重试。"}, HTTPStatus.SERVICE_UNAVAILABLE)


def main():
    parser = argparse.ArgumentParser(description="启动本机产品知识链演示")
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    db_path = args.db.expanduser().resolve()
    initialize(db_path)
    handler = partial(Handler, db_path=db_path)
    with ThreadingHTTPServer((args.host, args.port), handler) as server:
        print(f"产品知识链演示已启动 http://{args.host}:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
