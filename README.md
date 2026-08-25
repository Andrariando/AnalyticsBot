# 📊 Autonomous Business Analytics Operating System

An enterprise-grade autonomous Business Analytics platform that combines **consultant-level business framing and synthesis** with **deterministic Python computation, operations research optimization, statistical modeling, and state machine quality gates**.

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
        TG["Telegram Bot (aiogram / ptb)"]:::client
        API["FastAPI REST API (/api/projects)"]:::client
        UI["Future Next.js Dashboard"]:::client
    end

    subgraph GATEWAY["2. GATEWAY & ORCHESTRATION"]
        SM["Deterministic State Machine Engine"]:::core
        MEM["Project Memory Manager (Structured State)"]:::core
        ING["Secure File Ingestion Service"]:::core
    end

    subgraph AGENTS["3. COGNITIVE REASONING CORE"]
        SUP["Supervisor Agent (Principal Consultant)"]:::agent
        DS["Data Scientist Agent (Senior Applied DS & OR)"]:::agent
        CRIT["Critic Agent (VP Exec + Senior DS Manager)"]:::agent
    end

    subgraph TOOLS["4. DETERMINISTIC ANALYTICS RUNTIME"]
        PROF["Dataset Profiler & Hygiene Audits"]:::tool
        SC["Supply Chain Suite (ABC/XYZ/ADI/SS/ROP)"]:::tool
        OPT["Multi-DC Rebalance Optimization (LP)"]:::tool
        MOD["Predictive Modeling & Baselines (Forecast/RF)"]:::tool
        VIZ["Decision Visualizer (Pareto/WOS/Capacity)"]:::tool
        SAND["Sandboxed Python Subprocess Runtime"]:::tool
    end

    subgraph STORAGE["5. PERSISTENCE & ARTIFACT LAYER"]
        PG["PostgreSQL Database (Supabase / 14 Tables)"]:::db
        VEC["pgvector Knowledge Base (/learn Embeddings)"]:::db
        FS["Isolated Workspace Filesystem (projects/{id}/...)"]:::db
    end

    TG --> ING
    API --> ING
    UI --> ING
    ING --> FS
    ING --> SM

    SM --> SUP
    SUP --> MEM
    MEM <--> PG

    SUP --> DS
    SUP --> CRIT
    SUP --> PROF
    SUP --> SC

    DS --> SC
    DS --> OPT
    DS --> MOD
    DS --> VIZ
    DS --> SAND

    SAND --> FS
    VIZ --> FS
    OPT --> FS
    MOD --> PG
```

---

## ⚡ Deployment & 24/7 Operation Guide

### Is the Agent Online 24/7 or Only When My Laptop Runs?

| Deployment Mode | Availability | How It Works |
| :--- | :--- | :--- |
| **Mode 1: Local Laptop (Current)** | Only while laptop is awake and `python run_bot.py` is running | The bot runs on your local machine and polls Telegram. If you close your laptop, the bot pauses. |
| **Mode 2: 24/7 Cloud Deployment (Docker / VPS)** | **24/7 Continuous** | The container runs on a cloud server (e.g., Railway, Render, Fly.io, AWS EC2, or DigitalOcean). It remains online 24/7 without needing your laptop. |

> [!NOTE]
> **Zero Data Loss on Restart:**  
> Because the database is hosted in **Supabase PostgreSQL Cloud**, all user conversations, project state machine phases, uploaded metadata, decisions, and assumptions are permanently preserved. You can stop and restart your laptop anytime and resume exactly where you left off.

---

### How to Start the Agent

#### 1. Running the Telegram Bot Locally
```powershell
cd "c:\Users\Diandra Riando\OneDrive\Documents\Python Project\business_analytics_os"
python run_bot.py
```
*Open Telegram and message [@Analyst131Bot](https://t.me/Analyst131Bot).*

#### 2. Running the FastAPI REST API Server
```powershell
cd "c:\Users\Diandra Riando\OneDrive\Documents\Python Project\business_analytics_os"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
*API documentation available at `http://localhost:8000/docs`.*

#### 3. Running 24/7 with Docker Compose (Cloud or Home Server)
```bash
docker-compose up -d
```

---

## 🔄 End-to-End Analytical Pipeline Diagram

```mermaid
flowchart LR
    classDef step fill:#1E293B,stroke:#60A5FA,stroke-width:2px,color:#FFFFFF;
    classDef gate fill:#7F1D1D,stroke:#F87171,stroke-width:2px,color:#FFFFFF;
    classDef out fill:#064E3B,stroke:#34D399,stroke-width:2px,color:#FFFFFF;

    A["1. INGEST<br>CSV, XLSX, PDF, MD"]:::step --> B["2. PROFILE & CLEAN<br>Missingness, Grain, Flags"]:::step
    B --> C["3. SEGMENT<br>ABC / XYZ / ADI / CV²"]:::step
    C --> D["4. STOCKING POLICY<br>Dynamic SS, ROP, Target WOS"]:::step
    D --> E["5. OPTIMIZE<br>Lateral Rebalance & Disposition"]:::step
    E --> F["6. PREDICT<br>Forecast & Stockout Baselines"]:::step
    F --> G{"7. CRITIC GATE<br>Technical & Executive Audit"}:::gate
    G -- "PASS" --> H["8. DELIVER<br>Memo, Report, Action CSV, Notebook"]:::out
    G -- "CRITICAL (Max 3 Loops)" --> D
```

---

## 🧮 Mathematical Formulations Implemented

### 1. Velocity & Demand Intermittency Classification
- **ABC Dollar Volume:** Classified by Pareto cumulative dollar volume share ($A \le 80\%$, $B \le 95\%$, $C > 95\%$).
- **XYZ Demand Variability:** $CV = \frac{\sigma_D}{\bar{D}}$ ($X \le 0.5$, $Y \le 1.0$, $Z > 1.0$).
- **Syntetos-Boylan Intermittency Classification:**
  - **Average Demand Interval ($ADI$):** $ADI = \frac{N_{\text{total periods}}}{N_{\text{non-zero demand periods}}}$ (Cutoff threshold = 1.32).
  - **Squared Coefficient of Variation ($CV^2$):** $CV^2 = \left(\frac{\sigma_{\text{non-zero}}}{\mu_{\text{non-zero}}}\right)^2$ (Cutoff threshold = 0.49).
  - **Quadrants:**
    - **Smooth:** $ADI < 1.32, CV^2 < 0.49$ (regular demand, low variance)
    - **Erratic:** $ADI < 1.32, CV^2 \ge 0.49$ (regular demand, high variance)
    - **Intermittent:** $ADI \ge 1.32, CV^2 < 0.49$ (sporadic demand, low variance)
    - **Lumpy:** $ADI \ge 1.32, CV^2 \ge 0.49$ (sporadic demand, high variance)

### 2. Dynamic Stocking Policy & Buffer Sizing
- **Dynamic Safety Stock ($SS$):**
  $$SS = z \cdot \sqrt{L \cdot \sigma_D^2 + \bar{D}^2 \cdot \sigma_L^2}$$
  *(Where $z$ is the standard normal score corresponding to the SKU's target service level: $A=95\% \rightarrow z=1.645$, $B=90\% \rightarrow z=1.282$, $C=85\% \rightarrow z=1.036$)*.
- **Dynamic Reorder Point ($ROP$):**
  $$ROP = \bar{D} \cdot L + SS$$
- **Order-Up-To Level ($S$):**
  $$S = \bar{D} \cdot (L + R) + SS$$
  *(Where $R$ is the review cycle period in weeks)*.
- **Coverage (Weeks of Supply):**
  $$WOS = \frac{\text{On-Hand Inventory}}{\bar{D}_{\text{weekly}}}$$
- **Excess & Shortage Quantification:**
  $$\text{Excess} = \max(0, \text{On-Hand} - S), \quad \text{Shortage} = \max(0, ROP - (\text{On-Hand} + \text{On-Order}))$$

### 3. Lateral Multi-DC Network Rebalancing Optimization
- **Trigger Conditions:**
  - Origin DC $i$ is long ($\text{On-Hand}_i > S_i$) and Destination DC $j$ is short ($\text{On-Hand}_j < ROP_j$).
  - Origin DC remains safe post-transfer: $\text{On-Hand}_i - \text{Transfer} \ge SS_i$.
  - Transit days $T_{ij} < \text{Supplier Lead Time } L_j$.
  - Destination dedicated pallet capacity is not breached.
- **Economic Categorization:** Labeled strictly as `INVENTORY_REPOSITIONED` (not P&L savings).

---

## 📁 Repository Structure

```text
business_analytics_os/
├── .env.example               # Reference configuration template
├── .gitignore                 # Excludes secrets, cache, and project files
├── requirements.txt           # Python dependencies
├── README.md                  # System architecture and documentation
├── run_bot.py                 # Telegram Bot startup script
├── docker-compose.yml         # Container stack configuration
├── Dockerfile                 # Production Docker image definition
├── pytest.ini                 # Pytest runner configuration
├── app/
│   ├── config.py              # Pydantic Settings reading .env
│   ├── main.py                # FastAPI REST API server
│   ├── api/                   # REST API routes (/health, /projects, /artifacts)
│   ├── bot/                   # Telegram Bot handlers (/start, /learn, file upload, /status)
│   ├── core/                  # Deterministic State Machine & Project Memory
│   ├── agents/                # Cognitive Multi-Agent Reasoning Core
│   │   ├── base_agent.py      # Multi-turn tool execution loop
│   │   ├── supervisor.py      # Supervisor Agent (Principal Consultant)
│   │   ├── data_scientist.py  # Data Scientist Agent (Senior Applied DS & OR)
│   │   └── prompts/           # Specialized agent system prompts
│   ├── tools/                 # Deterministic Analytics & Modeling Tool Suite
│   │   ├── file_tools.py      # File ingestion & parsing
│   │   ├── profiling_tools.py # Dataset profiler & quality auditor
│   │   ├── runtime.py         # Sandboxed Python subprocess execution
│   │   ├── cleaning_tools.py  # Data hygiene & raw value preservation
│   │   ├── visualization_tools.py # Pareto, WOS Coverage, & Capacity charts
│   │   ├── supply_chain.py    # ABC/XYZ/ADI, Stocking Policy, Rebalance & Disposition
│   │   └── modeling.py        # Forecasting & Classification with Baselines
│   └── db/                    # SQLAlchemy async engine & Supabase models (14 tables)
└── tests/                     # Automated Pytest suite (21 tests)
```

---

## 🧪 Automated Tests

Run the full automated test suite:
```powershell
cd "c:\Users\Diandra Riando\OneDrive\Documents\Python Project\business_analytics_os"
python -m pytest
```
