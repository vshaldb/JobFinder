# JobFinder 🔍

A high-performance command-line careers crawler, data normalizer, and interactive dashboard that fetches real-time job openings from corporate career portals across **Workday**, **Eightfold.ai**, **Greenhouse**, **iCIMS**, **Rippling**, **Ashby**, **Lever**, **Google**, **Meta**, **Apple**, and **Amazon**.

Includes an interactive web dashboard with multi-location filters, instant role searching, table merging, and a built-in application tracking system to mark and track applied jobs.

---

## Features

- **Multi-ATS Support**: Directly interfaces with candidate APIs across 11 major ATS platforms and career portals without headless browsers.
- **50+ Pre-Configured Companies**: Tech giants (Google, Microsoft, Meta, Apple, Amazon), semiconductor leaders, and AI hardware innovators pre-configured out of the box.
- **Smart Location Normalization**: Tech-hub normalization for Indian centers (Bengaluru, Hyderabad, Pune, Noida, Gurgaon, Chennai) and global sites.
- **Interactive Web Dashboard**: Auto-generated standalone HTML report (`job_data/index.html`) with zero CDN dependencies.
- **Merge All Tables View**: One-click toggle to merge all company tables into a unified view for sorting newest jobs across all companies.
- **Applied Jobs Tracking**:
  - Mark jobs as applied directly from the browser report or terminal.
  - Automatically replaces the **Apply ↗** link with a green **✓ Applied** badge.
  - State persists in `applied_jobs.json` and syncs live upon browser refresh.
  - **Hide Applied** toggle button to filter out applied roles.
- **Zero Third-Party Database**: Clean JSON storage with optional local development server.

---

## Supported ATS Platforms

| Platform | Protocol / API | Example Companies |
| :--- | :--- | :--- |
| **Google** | Embedded JSON Data Callback (`AF_initDataCallback`) | Google |
| **Microsoft (Eightfold)** | Eightfold PCSX Search API with Session Pre-warming | Microsoft |
| **Meta** | Relay GraphQL Candidate Portal API (`CareersJobSearchResultsV2DataQuery`) | Meta |
| **Apple** | Apple Jobs REST API with CSRF Token Authentication | Apple |
| **Amazon** | Amazon Jobs Search API (`search.json` with Software Development filtering) | Amazon |
| **Workday** | Candidate Experience Site (CXS) REST API | NVIDIA, Intel, Broadcom, Marvell, SiFive, KLA, Silicon Labs, Wolfspeed, Cadence, Analog Devices |
| **Eightfold.ai** | Talent Intelligence PCSX & Career APIs | Qualcomm, Micron Technology, Infineon, Applied Materials, Lam Research, STMicroelectronics, Autodesk, GlobalFoundries |
| **Greenhouse** | Public Job Board REST API | Astera Labs, Tenstorrent, SambaNova Systems, Graphcore, Baya Systems, Lightmatter, Etched |
| **iCIMS** | Jibe & TalentBrew Candidate APIs | ARM, AMD, Keysight Technologies |
| **Rippling** | Public Board & Job Detail API | TYLsemi |
| **Ashby** | AshbyHQ Posting API | Cerebras Systems, d-Matrix |
| **Lever** | Lever Postings JSON API | Nuvacore, Eliyan |

---

## Pre-Configured Companies (50 Companies)

<details>
<summary><strong>Click to view the full directory of pre-configured companies</strong></summary>

| Company | Platform | Focus Area | Primary India Sites |
| :--- | :--- | :--- | :--- |
| **Google** | Google | Tech / Cloud, Search, AI & Systems | Bengaluru, Hyderabad, Gurugram, Mumbai |
| **Microsoft** | Eightfold.ai | Tech / Cloud, OS, AI & Enterprise | Bengaluru, Hyderabad, Noida |
| **Meta** | Meta | Tech / Social, AI, Messaging & Hardware | Bengaluru, Gurgaon, Hyderabad, Mumbai |
| **Apple** | Apple | Tech / Hardware, OS, Services & Retail | Bengaluru, Hyderabad, Gurugram, Mumbai |
| **Amazon** | Amazon | Tech / Cloud (AWS), Software & Systems | Bengaluru, Hyderabad, Chennai, Delhi NCR |
| **ARM** | iCIMS | Semiconductor / CPU IP | Bengaluru, Noida |
| **AMD** | iCIMS | Semiconductor / GPU & CPU | Bengaluru, Hyderabad |
| **Keysight Technologies** | iCIMS | Semiconductor & Electronic Test | Gurgaon, Bengaluru |
| **NVIDIA** | Workday | Semiconductor / GPU & AI | Bengaluru, Pune, Hyderabad |
| **Intel** | Workday | Semiconductor / Processors | Bengaluru, Hyderabad |
| **Qualcomm** | Eightfold.ai | Semiconductor / Wireless SoC | Bengaluru, Hyderabad, Chennai, Noida |
| **Broadcom** | Workday | Semiconductor / Networking & Storage | Bengaluru, Pune, Hyderabad |
| **Marvell** | Workday | Semiconductor / Data Infrastructure | Bengaluru, Pune, Hyderabad |
| **SiFive** | Workday | Semiconductor / RISC-V Compute | Bengaluru, Hyderabad |
| **KLA Corporation** | Workday | Semiconductor / Metrology & Yield | Chennai |
| **Silicon Labs** | Workday | Semiconductor / Wireless IoT | Hyderabad |
| **Wolfspeed** | Workday | Semiconductor / SiC Power & RF | Gurgaon |
| **Analog Devices** | Workday | Semiconductor / Analog & Mixed-Signal | Bengaluru, Hyderabad |
| **NXP Semiconductors** | Workday | Semiconductor / Automotive & IoT | Bengaluru, Noida, Pune, Hyderabad |
| **Microchip Technology** | Workday | Semiconductor / Microcontrollers | Bengaluru, Hyderabad, Chennai |
| **Cadence Design Systems** | Workday | EDA & Semiconductor IP | Bengaluru, Noida, Pune, Hyderabad |
| **Micron Technology** | Eightfold.ai | Semiconductor / Memory & Storage | Hyderabad, Bengaluru, Sanand |
| **Infineon Technologies** | Eightfold.ai | Semiconductor / Power & Automotive | Bengaluru |
| **Applied Materials** | Eightfold.ai | Semiconductor Equipment | Bengaluru |
| **Lam Research** | Eightfold.ai | Semiconductor Equipment | Bengaluru |
| **STMicroelectronics** | Eightfold.ai | Semiconductor / Embedded & Power | Greater Noida, Bengaluru |
| **GlobalFoundries** | Eightfold.ai | Semiconductor Foundry | Bengaluru, Hyderabad |
| **Autodesk** | Eightfold.ai | Software / Design & EDA | Bengaluru, Pune |
| **Astera Labs** | Greenhouse | Semiconductor / AI Connectivity Silicon | Bengaluru, Ahmedabad |
| **Tenstorrent** | Greenhouse | Semiconductor / AI & RISC-V | Bengaluru |
| **SambaNova Systems** | Greenhouse | Semiconductor / Dataflow AI Chips | Bengaluru |
| **Graphcore** | Greenhouse | Semiconductor / IPU AI Accelerators | Bengaluru |
| **Baya Systems** | Greenhouse | Semiconductor / Fabric & Chiplets | Bengaluru |
| **Lightmatter** | Greenhouse | Semiconductor / Photonic Computing | Global |
| **Etched** | Greenhouse | Semiconductor / Transformer ASICs | Global |
| **InnoPhase IoT** | Greenhouse | Semiconductor / Low-Power Wireless | Bengaluru |
| **Cerebras Systems** | Ashby | Semiconductor / Wafer-Scale AI Systems | Bengaluru |
| **d-Matrix** | Ashby | Semiconductor / In-Memory Computing AI | Bengaluru |
| **TYLsemi** | Rippling | Semiconductor / Platform Silicon | Bengaluru |
| **Nuvacore** | Lever | Semiconductor / CPU Core Architecture | Bengaluru |
| **Eliyan** | Lever | Semiconductor / Chiplet Interconnect PHY | Global |
| **Samsung Semiconductor** | Workday | Semiconductor / Memory, Foundry & LSI | Bengaluru (SSIR Goldstone), Gurugram |
| **Salesforce** | Workday | Tech / Cloud | Bengaluru, Hyderabad |
| **Allegro MicroSystems** | Workday | Semiconductor / Magnetic Sensors & Power | Bengaluru |
| **Entegris** | Workday | Semiconductor Materials & Filtration | Bengaluru |
| **Altera** | Workday | Semiconductor / FPGA Solutions | Bengaluru |
| **Lattice Semiconductor** | Workday | Semiconductor / Low-Power FPGA | Bengaluru, Hyderabad |
| **Semtech** | Workday | Semiconductor / Analog & Mixed-Signal | Bengaluru, Pune |
| **Workday** | Workday | Cloud / Enterprise | Pune |
| **Procter & Gamble** | Workday | Consumer Goods / Tech | Hyderabad |

</details>

---

## Getting Started

### Prerequisites

- **Python 3.9+**
- **Git**

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/vshaldb/JobFinder.git
   cd JobFinder
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   # On Windows:
   # venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   *(Optional) To install JobFinder as a system CLI command:*
   ```bash
   pip install -e .
   ```

---

## How to Fetch Jobs

### 1. Fetch All Available Jobs (Default India Filter)
Fetches open positions across all 46 configured companies for India locations:
```bash
python cli.py fetch
```

### 2. Fetch All Available Jobs Globally (No Location Filter)
Fetches all open positions worldwide from all 46 companies:
```bash
python cli.py fetch --no-location
```

### 3. Filter by Specific Location
```bash
python cli.py fetch --location "Bangalore"
python cli.py fetch --location "Hyderabad"
```

### 4. Filter by Role Keyword
```bash
python cli.py fetch --keyword "verification"
python cli.py fetch --keyword "physical design"
python cli.py fetch --keyword "compiler"
```

### 5. Filter by Specific Companies
Specify one or more comma-separated companies:
```bash
python cli.py fetch --company "ARM,NVIDIA,Qualcomm,AMD"
python cli.py fetch --company "Cerebras Systems,Astera Labs,Tenstorrent"
```

### 6. Filter by ATS Platform
```bash
python cli.py fetch --ats workday
python cli.py fetch --ats greenhouse
python cli.py fetch --ats eightfold
python cli.py fetch --ats icims
python cli.py fetch --ats ashby
python cli.py fetch --ats lever
python cli.py fetch --ats rippling
python cli.py fetch --ats google
python cli.py fetch --ats meta
python cli.py fetch --ats apple
python cli.py fetch --ats amazon
```

### 7. Filter by Domain & Recency
```bash
# Fetch semiconductor roles posted within the last 7 days
python cli.py fetch --domain semiconductor --posted-within 7

# Limit jobs fetched per company for quick checks
python cli.py fetch --company "ARM,Astera Labs" --max-jobs 5

# High-speed parallel fetching (default: 8 worker threads)
python cli.py fetch --workers 10
# Or using the short flag
python cli.py fetch -w 12
# Run sequentially (single thread)
python cli.py fetch --workers 1
```

---

## Web Dashboard & Live Tracking

Every fetch automatically compiles an interactive HTML dashboard at:
```
job_data/index.html
```

### Viewing the Dashboard
You can open the report directly in your browser:
```bash
open job_data/index.html  # On macOS
# xdg-open job_data/index.html  # On Linux
# start job_data/index.html     # On Windows
```

### Launching the Live Server
For instant two-way synchronization between your browser and `applied_jobs.json`, run:
```bash
python cli.py serve
```
Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser:
- **Instant File Sync**: Marking a job as applied writes directly to `applied_jobs.json` on disk.
- **Refresh Sync**: Refreshing the browser automatically loads any changes made to `applied_jobs.json`.

---

## Applied Jobs Tracking

JobFinder includes a tracking system to remember which jobs you have already applied to.

### In the Web Dashboard
- **Mark Applied**: Click the **Mark** button on any job row. The cell changes into a green **✓ Applied** badge and updates `applied_jobs.json`.
- **Applied Status**: Any job found in `applied_jobs.json` automatically shows **✓ Applied** instead of the **Apply ↗** link.
- **Unmark**: An unmark (`✕`) button lets you revert a job back to open status if clicked by mistake.
- **Hide Applied Toggle**: Use the **Hide Applied** button in the action bar to toggle visibility of applied jobs.

### From the Command Line
```bash
# List all jobs marked as applied
python cli.py applied

# Filter applied jobs by company
python cli.py applied --company "ARM"

# Mark a job as applied
python cli.py apply --company "ARM" --job-id "2026-19327" --role "Director of Engineering"

# Remove a job from applied status
python cli.py unapply --company "ARM" --job-id "2026-19327"
```

---

## Managing Companies

### List Configured Companies
```bash
python cli.py companies
```

### Add a New Company Interactively
```bash
python cli.py add-company
```
Follow the interactive prompt to configure any company on Workday, Eightfold, Greenhouse, iCIMS, Rippling, Ashby, or Lever. The company will be saved to `companies.json`.

---

## Directory Structure

```
JobFinder/
├── cli.py                         # Unified CLI entrypoint (fetch, serve, applied, apply, companies)
├── companies.json                 # Company registry and ATS endpoint configs
├── requirements.txt               # Python package dependencies
├── setup.py                       # Package installation definition
├── applied_jobs.json              # Persistent user store of applied jobs (ignored by git)
├── applied_jobs.example.json      # Template showing applied jobs schema
├── .gitignore                     # Git ignore rules for data and environment files
├── jobfinder/
│   ├── __init__.py                # Package initialization
│   ├── applied.py                 # Applied jobs persistence engine
│   ├── server.py                  # Local HTTP server and applied REST API
│   ├── fetcher.py                 # Multi-threaded company fetch orchestrator
│   ├── config.py                  # Company configuration loader and filter logic
│   ├── output.py                  # JSON serializer and dashboard generator bridge
│   ├── report.py                  # HTML dashboard generator & template compiler
│   ├── workday.py                 # Workday CXS API client
│   ├── eightfold.py               # Eightfold.ai PCSX and Career API client
│   ├── greenhouse.py              # Greenhouse public job board client
│   ├── icims.py                   # iCIMS, Jibe, and TalentBrew client
│   ├── rippling.py                # Rippling ATS client
│   ├── ashby.py                   # AshbyHQ job board client
│   ├── lever.py                   # Lever postings client
│   └── templates/
│       └── template.html          # Interactive HTML/CSS/JS dashboard template
└── job_data/                      # Runtime generated files (re-created on run)
    ├── .gitkeep                   # Retains empty output directory in git
    ├── <Company>.json             # Per-company normalized job data
    ├── applied_jobs.js            # Client-side script mirror for offline viewing
    └── index.html                 # Rendered interactive web dashboard
```

---

## License

MIT License. Feel free to use, modify, and distribute.
