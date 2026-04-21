# csm-set

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![uv](https://img.shields.io/badge/managed%20by-uv-purple)](https://docs.astral.sh/uv/)
[![Type Safety](https://img.shields.io/badge/type%20safety-mypy%20strict-green)](pyproject.toml)
[![Docker](https://img.shields.io/badge/docker-ready-blue)](Dockerfile)

โปรเจกต์นี้ทำกลยุทธ์ Cross-Sectional Momentum บนตลาดหุ้นไทย (SET)

โดยดึงข้อมูลผ่าน [tvkit](https://github.com/lumduan/tvkit) แล้วก็คำนวณ momentum signal → rank หุ้น → backtest → แสดงผลใน dashboard

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
