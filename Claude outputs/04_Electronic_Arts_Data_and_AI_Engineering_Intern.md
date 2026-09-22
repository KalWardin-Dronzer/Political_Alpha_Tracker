# VIVEK KUMAR
+91-7870145339 | vivek.kumar240043@gmail.com | linkedin.com/in/vivek-kumar | github.com/KalWardin-Dronzer

> **Target:** Data and AI Engineering Intern, Electronic Arts (Hyderabad) · **CV family:** `ENG` · **Match score: 89**

---

Quantitative Economics & Data Science student who builds and ships production data and ML systems — containerised, tested, CI/CD-automated and cloud-deployed. Experience with ETL pipelines across heterogeneous live sources, hybrid retrieval systems for LLMs, and low-latency API services.

## EDUCATION

**Birla Institute of Technology, Mesra** — Integrated M.Sc. in Quantitative Economics and Data Science `2022 – 2027`
Coursework: Algorithms for Big Data, Statistical Machine Learning, Data Structures & Algorithms

## ENGINEERING PROJECTS

**Long-Form Memory System for LLMs** — *Neurohack, IIT Guwahati — 26th nationally* — `FastAPI, SQLite, Embeddings, NLP`
- Architected a scalable long-term memory system for LLMs handling **1,000+ conversation turns** without prompt growth or performance degradation.
- Engineered a **hybrid retrieval pipeline** combining semantic embeddings (cosine similarity) with lexical **BM25** ranking via SQLite **FTS5**, achieving **sub-100ms retrieval latency**.
- Split the request path into a **synchronous low-latency retrieval path** and an **asynchronous background extraction worker**, keeping per-turn latency independent of extraction cost.
- Implemented conflict resolution with supersession lineage so a newer record deprecates its predecessor, preventing contradictory context injection.
- Exposed the system as a **FastAPI** service with a reproducible benchmark suite measuring long-range recall and conflict-handling accuracy.

**Production Data Pipeline & ML Deployment Platform** — `Python, PostgreSQL, Docker, GitHub Actions, AWS EC2`
- Designed and deployed a fully automated **ETL pipeline** ingesting data from **5+ heterogeneous live sources daily**, applying **data validation and quality checks** across 126+ tracked entities with robust error handling.
- Operationalised the solution with **Docker**, Git-based **CI/CD** (5 scheduled **GitHub Actions** production workflows), **PostgreSQL** and **AWS EC2** deployment; maintained a **pytest** suite across 10+ test modules.
- Engineered a fuzzy **entity-resolution** layer (RapidFuzz, 88%+ match threshold) to reconcile inconsistently-named records across sources, mapping a dynamic universe of 130+ connected nodes.
- Built an interactive **Streamlit** dashboard with **Gemini GenAI** integration, letting non-technical stakeholders self-serve natural-language queries against the underlying database.
- Structured the codebase into separate `data`, `signals`, `research`, `execution` and `pipeline` layers with a shared configuration module, so components are independently testable and deployable.

**Remaining-Useful-Life Prediction on NASA C-MAPSS** — `Python, Deep Learning, Sensor Time-Series`
- Built and benchmarked an RUL prediction model on multivariate degradation telemetry against published literature results, with per-unit diagnostic error analysis.

## TECHNICAL SKILLS

**Languages:** Python, SQL, R
**ML & MLOps:** Scikit-learn, XGBoost, TensorFlow, Model Deployment, Model Monitoring, Reproducibility, Inference Latency
**Data Engineering:** ETL/ELT, Data Pipelines, Data Ingestion, Data Quality & Validation, PostgreSQL, SQLite, Schema Design, Web Scraping, API Integration, Batch Processing
**Infrastructure:** Docker, CI/CD (GitHub Actions), AWS EC2, Linux, Git, pytest, Cron Scheduling
**GenAI:** LLMs, RAG, Embeddings, Semantic Search, Hybrid Retrieval, BM25, FastAPI, Gemini API

---
### Tailoring notes — delete before sending
- **P3 leads here, not the alpha tracker.** The memory system is your most engineering-shaped project and it opens with a national ranking.
- **The infra bullets are the point of this version.** Docker + GitHub Actions + pytest + EC2 + FastAPI is real deployment evidence. Most student applicants for this req will have a notebook.
- **Publication is off this CV.** It does not help an engineering screen and it costs you a line. Mention it in the interview if research comes up.
- **Prepare for the orchestration question.** You run cron and GitHub Actions, not **Airflow**. The honest answer: "scheduled workflows were the right weight for this system; I have not run Airflow, but I understand the DAG model." Do not claim it.
- **Other gaps they may probe:** Kubernetes, MLflow, Kafka, Spark. You have none. Pick one — MLflow is the cheapest — and have a real opinion on it.
