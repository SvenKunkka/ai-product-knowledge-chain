# AI 产品知识链

[English](README.en.md) · [MIT 许可证](LICENSE)

面向硬件产品的本机 AI 工作流原型。把产品版本、资料原文、测试依据和审核记录串起来，让从新品定义到变更与售后反馈的每项处理都有出处。

## 能做什么

| 流程 | 从输入到结果 |
| --- | --- |
| 固件变更 | 上传规格书、测试报告、说明书和 FAQ，定位受影响段落，生成带引用的差异，补证后走审核与模拟发布 |
| 新品 | 上传决策纪要、PRD、规格书和验证依据，拆需求、关联规格、生成待执行用例；事实获批后生成宣讲、产品页面、说明书和 FAQ 草稿 |
| 售后反馈 | 关联已经发布的产品档案与 FAQ 快照，按 FAQ 缺口、资料错误、缺陷线索和待核实分类；逐条审核后生成本机处理草稿 |

每次审核和模拟发布绑定资料版本。档案版本和反馈披露的设备固件分开保存。内置固件示例使用虚构资料，可直接验证补证、审核和双渠道回读。

## 本机启动

需要 Python 3.9 或更新版本。服务端和网页本身无需安装项目依赖。

```bash
git clone https://github.com/SvenKunkka/ai-product-knowledge-chain.git
cd ai-product-knowledge-chain
python3 -B server.py
```

打开 [http://127.0.0.1:8768](http://127.0.0.1:8768/)。可通过 `--port` 指定端口，通过 `--db` 指定 SQLite 文件。macOS 也可使用 `start.command`。

### 启用上传分析

上传分析使用本机 Ollama 的 `llama3.2:latest`。准备该模型后，在一个终端运行 Ollama，在另一个终端启动应用。

```bash
# Ollama 终端
OLLAMA_HOST=127.0.0.1:11436 OLLAMA_NO_CLOUD=1 ollama serve

# 应用终端
PRODUCT_KNOWLEDGE_OLLAMA_URL=http://127.0.0.1:11436 python3 -B server.py
```

支持 DOCX、UTF-8 Markdown/TXT 和有文本层的 PDF，每份最多 4 MiB。PDF 解析需要本机可用的 `pdftotext`。AI 对较长资料选取候选段落，审核时可按引用回到原文核对。

这是单用户本机演练，审核角色与发布渠道均为模拟。上传原件和草稿以普通 SQLite 数据保存在本机，请使用虚构或脱敏资料。默认仅接受本机回环访问。
