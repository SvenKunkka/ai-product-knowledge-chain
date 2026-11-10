"""Fictional fixture shared by every independent demo run."""

FIXTURE = {
    "product": {
        "name": "北辰 M2 无线鼠标",
        "sku": "BC-M2-24G",
        "hardware": "R1",
        "region": "中国大陆 · 简体中文",
    },
    "change": {
        "title": "2.4 GHz 接收器配对长按时间调整",
        "oldFirmware": "1.4.2",
        "newFirmware": "1.5.0",
        "before": "长按底部配对键 3 秒，蓝色指示灯快闪后松开。",
        "after": "长按底部配对键 5 秒，蓝色指示灯快闪后松开。",
        "decisionId": "DEC-M2-014",
        "decisionReason": "降低移动鼠标时误触底部配对键引发重新配对的概率。",
        "specId": "SPEC-M2-24G-03",
        "caseId": "TC-M2-PAIR-05",
        "expected": "R1 硬件在 2.4 GHz 模式下，长按 3 秒不进入配对，长按 5 秒进入配对，蓝色指示灯快闪。",
    },
    "report": {
        "id": "TR-M2-015-R1",
        "title": "2.4 GHz 配对长按阈值验证",
        "firmware": "1.5.0",
        "result": "通过",
        "summary": "R1 样机 3 台，每台验证 10 次。长按 3 秒未触发配对，长按 5 秒均触发配对，蓝色指示灯快闪。",
        "source": "演示报告 TR-M2-015-R1 · 第 2 节 · 对应用例 TC-M2-PAIR-05",
    },
    "drafts": {
        "manual": {
            "before": "将鼠标切换至 2.4 GHz 模式。长按底部配对键 3 秒，蓝色指示灯快闪后松开。",
            "after": "适用于 R1 硬件及固件 1.5.0。将鼠标切换至 2.4 GHz 模式，长按底部配对键 5 秒，蓝色指示灯快闪后松开。",
            "source": "说明书 · 2.4 GHz 接收器配对 · 第 4 节",
        },
        "faq": {
            "before": "如果 2.4 GHz 接收器未连接，请长按鼠标底部配对键 3 秒，等待蓝色指示灯快闪。",
            "after": "先确认鼠标的固件版本。R1 硬件运行 1.5.0 时，请在 2.4 GHz 模式下长按底部配对键 5 秒。运行 1.4.2 时仍按 3 秒操作。",
            "source": "FAQ · 2.4 GHz 接收器无法连接 · FAQ-M2-007",
        },
    },
    "impact": [
        {"title": "配对操作规格", "detail": "仅 R1 硬件的固件 1.5.0 将长按阈值从 3 秒改为 5 秒。", "kind": "spec"},
        {"title": "阈值复测", "detail": "用例 TC-M2-PAIR-05 需验证短按阈值和配对指示灯。", "kind": "test"},
        {"title": "说明书 · 2.4 GHz 配对", "detail": "更新操作步骤，并标明适用固件。", "kind": "manual"},
        {"title": "售后 FAQ · 接收器无法连接", "detail": "先识别固件版本，再提供对应的操作时长。", "kind": "faq"},
        {"title": "蓝牙配对与旧固件", "detail": "不在这次变更的适用范围。", "kind": "unaffected"},
    ],
}
