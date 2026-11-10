# AI Product Knowledge Chain

[简体中文](README.md) · [MIT License](LICENSE)

A local AI workflow prototype for hardware product teams. It connects product versions, source documents, test evidence, and reviews so that launch, firmware, and support decisions can be traced to their sources.

## Workflows

| Workflow | Inputs and outputs |
| --- | --- |
| Firmware changes | Upload specifications, test reports, manuals, and FAQs. Identify affected passages, draft cited revisions, and run evidence review and simulated publication. |
| New product launches | Upload decisions, a PRD, specifications, and verification references. Extract requirements, link specifications, and draft pending test cases. Approved facts feed launch briefs, product pages, manuals, and FAQs. |
| Support feedback | Connect feedback to a released product record and FAQ snapshot. Review suggested classifications, then generate local FAQ edits, documentation corrections, or product investigation tasks. |

Review and simulated publication are tied to document versions. Product record versions and firmware reported in a support case are tracked separately. The built-in fictional firmware case can demonstrate evidence review and simulated publication without a model.

## Run locally

Requires Python 3.9 or later. The web app and server use the Python standard library and bundled web assets.

```bash
git clone https://github.com/SvenKunkka/ai-product-knowledge-chain.git
cd ai-product-knowledge-chain
python3 -B server.py
```

Open [http://127.0.0.1:8768](http://127.0.0.1:8768/). Use `--port` to change the port and `--db` to choose the SQLite file. On macOS, `start.command` provides an alternative launcher.

### Enable document analysis

Document analysis uses the local Ollama model `llama3.2:latest`. After preparing the model, start Ollama and the application in separate terminals.

```bash
# Ollama terminal
OLLAMA_HOST=127.0.0.1:11436 OLLAMA_NO_CLOUD=1 ollama serve

# Application terminal
PRODUCT_KNOWLEDGE_OLLAMA_URL=http://127.0.0.1:11436 python3 -B server.py
```

Uploads accept DOCX, UTF-8 Markdown/TXT, and text-layer PDFs up to 4 MiB each. PDF extraction requires `pdftotext`. For longer documents, analysis selects candidate passages and exposes their source lines for human review.

This is a single-user loopback prototype with simulated review roles and publication channels. Uploaded originals and drafts are stored in a local SQLite database. Use fictional or redacted materials.
