# csm-set

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![uv](https://img.shields.io/badge/managed%20by-uv-purple)](https://docs.astral.sh/uv/)
[![Type Safety](https://img.shields.io/badge/type%20safety-mypy%20strict-green)](pyproject.toml)
[![Docker](https://img.shields.io/badge/docker-ready-blue)](Dockerfile)

โปรเจกต์นี้ทำกลยุทธ์ Cross-Sectional Momentum บนตลาดหุ้นไทย (SET)

โดยดึงข้อมูลผ่าน [tvkit](https://github.com/lumduan/tvkit) แล้วก็คำนวณ momentum signal → rank หุ้น → backtest → แสดงผลใน dashboard

---

## สถานะการพัฒนา

| Phase | รายละเอียด | สถานะ |
|-------|-----------|-------|
| 0 | Project Bootstrap | `[x]` เสร็จแล้ว |
| **1** | **Data Pipeline** | **`[x]` เสร็จแล้ว** |
| 2 | Signal Research | `[ ]` ยังไม่เริ่ม |
| 3 | Backtesting | `[ ]` ยังไม่เริ่ม |
| 4 | Portfolio & Risk | `[ ]` ยังไม่เริ่ม |
| 5 | API | `[ ]` ยังไม่เริ่ม |
| 6 | Web Dashboard | `[ ]` ยังไม่เริ่ม |
| 7 | Docker & Public Distribution | `[ ]` ยังไม่เริ่ม |
| 8 | Hardening & Docs | `[ ]` ยังไม่เริ่ม |

**Phase 1 — Data Pipeline เสร็จสมบูรณ์แล้ว (2026-04-23)**

สิ่งที่ทำเสร็จใน Phase 1:
- `ParquetStore` — เก็บข้อมูล OHLCV เป็น parquet พร้อม round-trip ครบถ้วน
- `OHLCVLoader` — async wrapper ของ tvkit พร้อม retry, concurrency control, และ public mode guard
- `UniverseBuilder` — กรอง symbol และสร้าง dated universe snapshots ป้องกัน survivorship bias
- `PriceCleaner` — gap-fill, coverage drop, winsorise returns
- `scripts/fetch_history.py` — ดึงข้อมูลย้อนหลัง 20 ปีแบบ idempotent (704 symbols)
- `scripts/build_universe.py` — กรอง SecurityType + สร้าง snapshot รายเดือน
- `notebooks/01_data_exploration.ipynb` — ตรวจสอบคุณภาพข้อมูล — **ผ่านทุก 6 เกณฑ์**

ดู roadmap เต็มได้ที่ [docs/plans/ROADMAP.md](docs/plans/ROADMAP.md)

> **⚠️ Disclaimer**
> โปรเจกต์นี้จัดทำขึ้นเพื่อการศึกษาเท่านั้น ไม่ถือเป็นคำแนะนำการลงทุนในทุกกรณี
> ผลการทดสอบย้อนหลัง (backtest) ไม่ได้รับประกันผลตอบแทนในอนาคต
> ผู้พัฒนาไม่รับผิดชอบต่อความเสียหายหรือผลกำไรขาดทุนใดๆ ที่เกิดจากการนำโปรเจกต์นี้ไปใช้งาน


---

## โปรเจคนี้ทำอะไรบ้าง

- คำนวณ momentum signal แบบ Jegadeesh–Titman (12-1M, 6-1M, 3-1M)
- Backtest แบบ walk-forward พร้อมหักค่า transaction cost จริง
- ตรวจ market regime ด้วย 200-day SMA ของ SET index
- สร้างพอร์ตได้สามแบบ — equal weight / vol-target / min-variance
- ดูผลผ่าน dashboard (NiceGUI) และ REST API (FastAPI)

---

## วิธีนำไปใช้งาน

```bash
git clone https://github.com/lumduan/csm-set
cd csm-set
docker compose up
```

เปิด [http://localhost:8080](http://localhost:8080)


---


ข้อมูลดิบ (OHLCV) ไม่ถูก commit เข้า repo นี้ เพราะมีลิขสิทธิ์ของ ตลาดหลักทรัพย์ไทย ใน `results/` มีแค่ derived metrics พวก NAV, z-scores, quintiles เท่านั้น แต่หากท่านสนใจก็สามารถนำโปรเจคนี้ไปดึงข้อมูลผ่าน tvkit เองได้

---

## Stack

| | |
|---|---|
| ดึงข้อมูล | tvkit, pyarrow, pandas |
| Research | numpy, scipy, scikit-learn |
| API | FastAPI, uvicorn, APScheduler |
| UI | NiceGUI |
| Config | pydantic-settings |
| Tooling | uv, ruff, mypy, pytest |

---

## ถ้าอยากรัน pipeline เต็มๆ 

```bash
cp .env.example .env
# แก้ CSM_PUBLIC_MODE=false และใส่ tvkit credentials
```

จากนั้น:

```bash
uv sync --all-groups

# ดึงข้อมูลย้อนหลัง (ครั้งแรกใช้เวลาหน่อย)
uv run python scripts/fetch_history.py
uv run python scripts/build_universe.py

# export ผลลัพธ์ไปไว้ใน results/ แล้ว commit
uv run python scripts/export_results.py
git add results/
git commit -m "results: update $(date +%Y-%m-%d)"
git push
```

หรือถ้าอยากรันผ่าน Docker:

```bash
docker compose -f docker-compose.yml -f docker-compose.private.yml up
```

---

## Development

```bash
uv sync --all-groups
cp .env.example .env

# ก่อน commit ทุกครั้ง
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest tests/ -v

# รัน API + UI แยก
uv run uvicorn api.main:app --reload --port 8000
uv run python ui/main.py
```

---

## Docs

- [วิธีติดตั้ง](docs/getting-started/installation.md)
- [Docker setup](docs/guides/docker.md)
- [Architecture](docs/architecture/system-overview.md)
- [API Reference](docs/reference/index.md)

---

## แหล่งอ้างอิง

- Jegadeesh & Titman (1993). *Returns to Buying Winners and Selling Losers*
- Asness, Moskowitz & Pedersen (2013). *Value and Momentum Everywhere*
- Rouwenhorst (1999). *Local Return Factors in Emerging Stock Markets*

---

## License

MIT — ดูที่ [LICENSE](LICENSE)
