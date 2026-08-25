# 📊 Autonomous Business Analytics Operating System

An enterprise-grade autonomous Business Analytics platform that combines **consultant-level business framing and synthesis** with **Google OR-Tools exact MILP optimization, Multi-Echelon Inventory Optimization (MEIO), dynamic Python code execution, interactive Jupyter Notebook creation, rolling checkpoint memory, and state machine quality gates**.

---

## 📖 Table of Contents
1. [User Guide: How to Use This Properly](#-user-guide-how-to-use-this-properly)
2. [Interactive Telegram Inline Keyboard Buttons](#-interactive-telegram-inline-keyboard-buttons)
3. [Dual Execution Engine (OR-Tools vs Custom Python Notebooks)](#-dual-execution-engine)
4. [Multi-Echelon MEIO Optimization](#-multi-echelon-inventory-optimization-meio)
5. [Rolling Checkpoint Summarization & Parallel Tasks](#-rolling-checkpoint-summarization--parallel-tasks)
6. [What to Expect (Outputs & Deliverables)](#-what-to-expect-outputs--deliverables)
7. [System Architecture Diagram](#-system-architecture-diagram)
8. [Mathematical Formulations Implemented](#-mathematical-formulations-implemented)
9. [Deployment & 24/7 Operation Guide](#-deployment--247-operation-guide)
10. [Automated Tests & Quality Verification](#-automated-tests--quality-verification)

---

## 🚀 User Guide: How to Use This Properly

The system operates like a senior consulting team and data science lab working together. Follow this 5-step workflow:

```mermaid
flowchart LR
    classDef step fill:#1E293B,stroke:#60A5FA,stroke-width:2px,color:#FFFFFF;
    classDef gate fill:#7F1D1D,stroke:#F87171,stroke-width:2px,color:#FFFFFF;
    classDef out fill:#064E3B,stroke:#34D399,stroke-width:2px,color:#FFFFFF;

    A["1. START PROJECT<br>/new <Title>"]:::step --> B["2. UPLOAD DATA<br>Attach CSV, Excel, PDF"]:::step
    B --> C["3. PROPOSAL GATE<br>Bot proposes plan & renders buttons"]:::gate
    C -->|Click Button or Text| D["4. BACKEND EXECUTION<br>OR-Tools MILP, MEIO, Custom Notebook"]:::step
    D --> E["5. CRITIC GATE<br>Technical & Business Audit"]:::gate
    E --> F["6. DELIVERABLES<br>Memo, Report, CSVs, Notebook"]:::out
```

---

## 📱 Interactive Telegram Interface & Proactive User Guidance

The Telegram bot acts as an interactive executive copilot that **actively guides the user at every phase of analysis**:

```text
┌────────────────────────────────────────────────────────┐
│  [✅ Approve & Run OR-Tools]   [📓 Build Python Notebook] │
│  [🌐 Multi-Echelon MEIO]      [📊 Render Decision Charts] │
└────────────────────────────────────────────────────────┘
```

- **`[✅ Approve & Run OR-Tools]`**: Instantly solves the exact Mixed-Integer Linear Program (MILP) for multi-DC lateral inventory rebalancing, dynamic stocking policies, and vendor returns.
- **`[📓 Build Python Notebook]`**: Commands the agent to dynamically write custom Python code, run exploratory data analysis, and compile a self-contained interactive Jupyter Notebook (`.ipynb`).
- **`[🌐 Multi-Echelon MEIO]`**: Computes Central Hub (CDC) vs Regional Spoke (RDC) buffer sizing and square-root risk pooling efficiency.
- **`[📊 Render Decision Charts]`**: Dispatches 300 DPI high-resolution Pareto velocity curves and warehouse pallet capacity charts directly to your chat.

### 💬 Proactive Communication & Resilient Messaging
- **Awaiting Input Prompts:** The bot never leaves users in the dark. After file ingestion, intermediate calculations, or recommendation proposals, it explicitly communicates:
  - What has been processed and stored in the workspace.
  - What decision, input, or next step is required from the stakeholder.
  - One-click buttons and textual examples to trigger the next action.
- **Safe Markdown & Error Fallback:** Integrated message sanitization and automatic fallback mechanisms ensure that complex dataset columns, formulas, and long reports are delivered seamlessly without entity parse errors.

---

## 🔬 Dual Execution Engine

```mermaid
graph TD
    classDef input fill:#1E293B,stroke:#38BDF8,stroke-width:2px,color:#FFFFFF;
    classDef opt fill:#064E3B,stroke:#34D399,stroke-width:2px,color:#FFFFFF;
    classDef py fill:#312E81,stroke:#818CF8,stroke-width:2px,color:#FFFFFF;
    classDef out fill:#451A03,stroke:#FBBF24,stroke-width:2px,color:#FFFFFF;

    REQ["User Request & Selected Action"]:::input

    REQ -->|Standard Supply Chain / OR| OPT_ENGINE["OPTION A: Google OR-Tools MILP & MEIO<br>• Syntetos-Boylan ADI/CV²<br>• Dynamic SS & ROP<br>• Exact Multi-DC Lateral MILP<br>• Multi-Echelon Buffer Sizing"]:::opt
    REQ -->|Custom Problem / Ad-hoc Analysis| PY_ENGINE["OPTION B: Autonomous Python Coder & Notebook Builder<br>• Dynamic Python script generation<br>• Sandboxed Subprocess Runtime<br>• Markdown explanations + Code cells<br>• Custom Charts & Simulations"]:::py

    OPT_ENGINE --> ARTIFACTS["Outputs & Deliverables<br>(.ipynb, .md, .csv, .png)"]:::out
    PY_ENGINE --> ARTIFACTS
```

### Option A: Google OR-Tools Exact MILP Rebalancing
Formulates lateral network inventory transfers as an exact Mixed-Integer Linear Program (MILP):
$$\min \sum_{i,j,k} \left( c_{ij} x_{ijk} - 1.5 \cdot \text{Cost}_k \cdot x_{ijk} \right)$$
Subject to:
1. **Source DC Remaining Inventory:** $\sum_j x_{ijk} \le \max(0, \text{On-Hand}_{ik} - SS_{ik})$
2. **Destination Shortage Relief:** $\sum_i x_{ijk} \le \max(0, ROP_{jk} - (\text{On-Hand}_{jk} + \text{On-Order}_{jk}))$
3. **Lead-Time Advantage:** $T_{ij} < \text{Supplier Lead Time } L_{jk}$

---

## 🌐 Multi-Echelon Inventory Optimization (MEIO)

When analyzing multi-tier distribution networks (e.g. Central Distribution Center $\to$ Regional Fulfillment Centers):
- **Guaranteed-Service Buffer Allocation:**
  - **Decentralized Model:** Each regional DC holds safety stock for the entire supplier lead time $L_{\text{supplier}}$.
  - **Multi-Echelon MEIO Model:** Central DC pools safety stock for net lead time $(L_{\text{supplier}} - L_{\text{internal}})$, and regional DCs hold echelon buffer for short internal transit $L_{\text{internal}}$.
- **Risk Pooling Gain:** Evaluates square-root variance pooling $\sqrt{\sum \sigma_i^2} < \sum \sigma_i$, unlocking **15%–35% working capital reduction** while maintaining target service levels.

---

## 🧠 Rolling Checkpoint Summarization & Parallel Tasks

1. **Rolling Checkpoint Summarization:**  
   To prevent linear LLM token growth in long-running projects (20+ turns), the system automatically compresses older conversation turns into structured memory checkpoints in `project_state`. Prompt token overhead remains flat and response latency stays fast.
2. **Parallel Subagent Task Runner:**  
   Executes independent analytical tasks (e.g. multi-SKU demand forecasting, velocity classification, and MEIO simulations) concurrently via async coroutines.

---

## 📦 What to Expect (Outputs & Deliverables)

Whenever an analysis is executed, you receive **4 distinct deliverable tiers**:

### 1. 💬 Telegram Real-Time Synthesis
- Executive markdown summary detailing financial impact (**Inventory Repositioned**, **Working Capital Released**, **Holding Cost Saved**, **Cash Recovered**).
- **Auto-Dispatched Photo Attachments:** 300 DPI decision charts delivered directly to Telegram.
- **Auto-Dispatched Document Attachments:** Line-item CSV action queues, technical markdown reports, and `.ipynb` Jupyter Notebooks delivered as files.

### 2. 📁 Project Workspace Files (`projects/{project_id}/`)
```text
projects/{project_id}/
├── raw/                                 # Untouched original input files
├── cleaned/                             # Sanitized datasets with raw/clean columns
├── analysis/
│   ├── sku_velocity_segmentation.csv   # ABC (Dollar/Unit), XYZ, ADI, CV², Demand Patterns
│   ├── stocking_policy_evaluation.csv  # Dynamic SS, ROP, Order-Up-To, Excess $, Shortage $
│   └── multi_echelon_meio_evaluation.csv # Hub-and-Spoke risk pooling & echelon buffers
├── charts/
│   ├── pareto_velocity_curve.png       # 300 DPI Cumulative Dollar vs Unit Volume
│   ├── inventory_coverage_vs_target.png# Current WOS vs Recommended Policy
│   └── dc_pallet_capacity_utilization.png # Dedicated vs Occupied Pallet Racks
└── outputs/
    ├── Executive_Strategy_Memo.md      # 1-page board-level briefing & 30-60-90 day roadmap
    ├── Technical_Analytics_Report.md   # Comprehensive technical report & critic audit
    ├── rebalance_action_queue.csv      # Operational transfer orders (OR-Tools MILP optimal)
    ├── disposition_action_queue.csv    # Vendor returns & scrap clearance
    └── custom_analysis.ipynb           # Custom Python notebook built by the agent
```

---

## 🏛️ System Architecture Diagram

```mermaid
graph TD
    classDef client fill:#1E293B,stroke:#38BDF8,stroke-width:2px,color:#FFFFFF;
    classDef core fill:#0F172A,stroke:#818CF8,stroke-width:2px,color:#FFFFFF;
    classDef agent fill:#1E1B4B,stroke:#C084FC,stroke-width:2px,color:#FFFFFF;
    classDef tool fill:#064E3B,stroke:#34D399,stroke-width:2px,color:#FFFFFF;
    classDef db fill:#451A03,stroke:#FBBF24,stroke-width:2px,color:#FFFFFF;

    subgraph CLIENT_LAYER["1. CLIENT & INTERFACE LAYER"]
        TG["Telegram Bot (@Analyst131Bot)<br>• Inline Keyboard Buttons<br>• Auto Photo & Document Dispatch"]:::client
        API["FastAPI REST API (/api/projects)"]:::client
    end

    subgraph GATEWAY["2. GATEWAY & ORCHESTRATION"]
        SM["Deterministic State Machine Engine"]:::core
        MEM["Project Memory Manager (Rolling Checkpoints)"]:::core
        ING["Secure File Ingestion Service"]:::core
    end

    subgraph AGENTS["3. COGNITIVE REASONING CORE"]
        SUP["Supervisor Agent (Principal Consultant)"]:::agent
        DS["Data Scientist Agent (Senior Applied DS & OR)"]:::agent
        CRIT["Critic Agent (VP Exec + Senior DS Manager)"]:::agent
        PAR["Parallel Subagent Task Runner"]:::agent
    end

    subgraph TOOLS["4. DETERMINISTIC ANALYTICS RUNTIME"]
        PROF["Dataset Profiler & Hygiene Audits"]:::tool
        SC["Supply Chain Suite (ABC/XYZ/ADI/SS/ROP)"]:::tool
        MILP["Google OR-Tools MILP Solver"]:::tool
        MEIO["Multi-Echelon Inventory Optimizer (MEIO)"]:::tool
        MOD["Predictive Modeling & Baselines (Forecast/RF)"]:::tool
        NB["Jupyter Notebook Builder (.ipynb)"]:::tool
        VIZ["Decision Visualizer (Pareto/WOS/Capacity)"]:::tool
        SAND["Sandboxed Python Subprocess Runtime"]:::tool
        REP["Executive Deliverables Generator"]:::tool
    end

    subgraph STORAGE["5. PERSISTENCE & ARTIFACT LAYER"]
        PG["PostgreSQL Database (Supabase / 14 Tables)"]:::db
        VEC["pgvector Knowledge Base (/learn Embeddings)"]:::db
        FS["Isolated Workspace Filesystem (projects/{id}/...)"]:::db
    end

    TG --> ING
    API --> ING
    ING --> FS
    ING --> SM

    SM --> SUP
    SUP --> MEM
    MEM <--> PG

    SUP --> DS
    SUP --> CRIT
    SUP --> PROF
    SUP --> SC
    SUP --> MILP
    SUP --> MEIO
    SUP --> NB
    SUP --> REP

    DS --> SC
    DS --> MILP
    DS --> MEIO
    DS --> MOD
    DS --> NB
    DS --> VIZ
    DS --> SAND

    SAND --> FS
    NB --> FS
    VIZ --> FS
    MILP --> FS
    MEIO --> FS
    MOD --> PG
    REP --> FS
```

---

## ⚡ Deployment & 24/7 Operation Guide

```powershell
cd "c:\Users\Diandra Riando\OneDrive\Documents\Python Project\business_analytics_os"
python run_bot.py
```

---

## 🧪 Automated Tests & Quality Verification

Run the full 27-test test suite:
```powershell
cd "c:\Users\Diandra Riando\OneDrive\Documents\Python Project\business_analytics_os"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"; python -m pytest -p asyncio tests/ -v
```

```text
============================= 27 passed in 21.37s =============================
```
