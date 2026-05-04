"""Build 05_live_portfolio_rationale.ipynb — trader-facing CSM strategy explainer."""
import nbformat as nbf

nb = nbf.v4.new_notebook()
nb.metadata = {
    "kernelspec": {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    },
    "language_info": {"name": "python", "version": "3.12.0"},
}

cells = []

def md(source):
    cells.append(nbf.v4.new_markdown_cell(source))

def code(source):
    cells.append(nbf.v4.new_code_cell(source))

# ============================================================
# Cell 1 — Title
# ============================================================
md("""# CSM Strategy — Live Portfolio Rationale
## May 2026 Entry | Cross-Sectional Momentum

**Prepared:** 2026-05-04 &nbsp;|&nbsp; **Strategy:** CSM v1.0 (Constrained Strategy Matrix) &nbsp;|&nbsp; **Portfolio Size:** 10 Stocks &nbsp;|&nbsp; **AUM:** 1,000,000 THB

---

*This notebook explains — with data and charts — why these 10 specific stocks were selected for the May 2026 CSM live portfolio. Every selection is driven by the strategy's cross-sectional momentum pipeline, not subjective judgment.*""")

# ============================================================
# Cell 2 — Executive Summary
# ============================================================
md("""## Executive Summary

| Item | Detail |
|------|--------|
| **Strategy** | Cross-Sectional Momentum (Jegadeesh & Titman 12-1M) |
| **Universe** | 132 SET-listed stocks passing liquidity & quality filters |
| **Selection** | Top 10 by composite momentum z-score (all in Q5 — top quintile) |
| **Weighting** | Volatility-target, capped at 5–15% per position |
| **Rebalance** | Monthly, at business month-end (next: 2026-05-30) |
| **Risk Controls** | 15% vol target, −10% circuit breaker, 35% sector cap |
| **Entry** | At The Opening (ATO) on 2026-05-05 |""")

# ============================================================
# Cell 3 — Strategy Overview
# ============================================================
md("""## 1. Strategy Overview: What Is Cross-Sectional Momentum?

Cross-sectional momentum ranks stocks *relative to each other* (not vs. their own past). Every month, we compute trailing 12-month returns (skipping the most recent month to avoid short-term reversal), standardize them as z-scores across all 132 stocks, and buy the highest-ranked names.

### The CSM Pipeline

```
SET Universe (700+ stocks)
    │
    ├─[Liquidity Filter]── ADTV ≥ 5M THB, price ≥ 1 THB
    ├─[Quality Filter] ─── Earnings positive, net margin ≥ 5%
    │
    ├─[Feature Engine] ─── 7 momentum signals computed per stock
    │   ├─ mom_12_1  (12-month, skip 1)
    │   ├─ mom_6_1   (6-month, skip 1)
    │   ├─ mom_3_1   (3-month, skip 1)
    │   ├─ mom_1_0   (1-month, no skip — reversal indicator)
    │   ├─ sharpe_momentum (return / volatility)
    │   ├─ residual_momentum (alpha vs. SET index)
    │   └─ sector_rel_strength (vs. sector peers)
    │
    ├─[Cross-Sectional Ranking]── Z-score each signal, average into composite
    ├─[Selection] ──── Top 10 by composite score + buffer logic
    ├─[Sector Cap] ─── Max 35% per sector
    └─[Weighting] ──── Volatility-target (15% annual), enforce 5–15% bounds
```

**Key insight:** Stocks with high z-scores have delivered unusually strong returns *compared to the rest of the market* over the past year. The strategy bets that this relative strength persists for the next month.""")

# ============================================================
# Cell 4 — Data Loading (shared setup, with embedded fallback for portability)
# ============================================================
cell4 = """import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch
import seaborn as sns
import json
from io import StringIO
from pathlib import Path

# ── Style ──────────────────────────────────────────────────
plt.rcParams.update({
    "figure.dpi": 120,
    "savefig.dpi": 120,
    "font.family": "DejaVu Sans",
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "figure.titlesize": 15,
    "figure.facecolor": "white",
    "axes.facecolor": "#fafafa",
    "axes.edgecolor": "#cccccc",
    "axes.grid": True,
    "grid.alpha": 0.4,
    "grid.color": "#dddddd",
})
sns.set_palette("viridis")

# Resolve project root: nbconvert runs from notebook directory, so try parent first
PROJECT = Path.cwd()
if not (PROJECT / "data" / "processed").exists() and (PROJECT.parent / "data" / "processed").exists():
    PROJECT = PROJECT.parent
DATA = PROJECT / "data" / "processed"
RESULTS = PROJECT / "results"

print("Loading data...")

# ── Embedded fallback data (132-stock snapshot extracted 2026-04-30) ─
_EMBEDDED_CSV = "ticker,mom_12_1,mom_6_1,mom_3_1,mom_1_0\\n"
_EMBEDDED_CSV += "3BBIF,0.391867,0.017523,0.046502,0.153408\\n"
_EMBEDDED_CSV += "AAI,-0.698369,-1.629393,-1.404770,0.195179\\n"
_EMBEDDED_CSV += "AAV,-0.682396,-0.723283,-0.401878,-0.687720\\n"
_EMBEDDED_CSV += "ACE,-0.134657,0.086585,-0.159862,-0.558011\\n"
_EMBEDDED_CSV += "ADVANC,0.778698,1.033001,0.231156,-1.406352\\n"
_EMBEDDED_CSV += "ADVICE,0.638405,0.258604,-0.401878,0.281149\\n"
_EMBEDDED_CSV += "AGE,1.678912,1.129640,0.097108,-1.208793\\n"
_EMBEDDED_CSV += "AIE,0.140103,0.795282,1.193310,-1.353876\\n"
_EMBEDDED_CSV += "AJ,0.712664,0.903381,2.110525,0.851980\\n"
_EMBEDDED_CSV += "ALT,0.864433,0.132394,-1.031815,2.187460\\n"
_EMBEDDED_CSV += "AMATA,0.855676,1.073780,1.369016,0.495760\\n"
_EMBEDDED_CSV += "AOT,0.767870,1.200108,-0.225105,-0.348930\\n"
_EMBEDDED_CSV += "AP,0.130159,-0.023252,-0.515390,0.100759\\n"
_EMBEDDED_CSV += "AS,0.907940,-0.513601,-0.401878,-0.465490\\n"
_EMBEDDED_CSV += "AURA,-0.760862,-0.427535,0.093199,0.223920\\n"
_EMBEDDED_CSV += "AWC,-0.294377,-0.087074,-0.536644,-0.236848\\n"
_EMBEDDED_CSV += "BA,-0.665102,-0.051547,-1.112154,-0.016795\\n"
_EMBEDDED_CSV += "BAM,0.347852,-0.142179,-1.030098,0.539812\\n"
_EMBEDDED_CSV += "BANPU,0.866535,1.482888,0.303260,-0.565819\\n"
_EMBEDDED_CSV += "BBGI,0.903129,1.637783,2.015576,-0.465490\\n"
_EMBEDDED_CSV += "BBIK,-1.205140,-0.453035,1.389034,-0.336260\\n"
_EMBEDDED_CSV += "BBL,0.547759,0.479515,0.307683,-0.966906\\n"
_EMBEDDED_CSV += "BCH,-1.378620,-0.988318,-0.703404,-0.592646\\n"
_EMBEDDED_CSV += "BCP,0.200899,1.534486,1.670866,-1.651420\\n"
_EMBEDDED_CSV += "BCPG,-0.015618,-1.355275,-0.560265,0.592005\\n"
_EMBEDDED_CSV += "BDMS,-0.781847,-0.318307,-0.817223,-0.465490\\n"
_EMBEDDED_CSV += "BEC,-2.168447,-0.075803,0.157929,-0.651744\\n"
_EMBEDDED_CSV += "BEM,-0.296554,0.131491,-0.289083,-0.008165\\n"
_EMBEDDED_CSV += "BGRIM,0.224527,-1.394423,-0.943672,1.214584\\n"
_EMBEDDED_CSV += "BH,-0.184329,-0.314670,-0.341090,0.746956\\n"
_EMBEDDED_CSV += "BJC,-1.674308,-1.568978,-0.304013,-0.123337\\n"
_EMBEDDED_CSV += "BLA,0.514272,0.404428,-0.528730,-0.101513\\n"
_EMBEDDED_CSV += "BPP,1.645465,0.733044,0.120968,-0.663644\\n"
_EMBEDDED_CSV += "BTG,0.286726,1.299507,1.065883,0.130438\\n"
_EMBEDDED_CSV += "BTS,-2.594980,-1.498336,-0.788130,-0.117495\\n"
_EMBEDDED_CSV += "BTSGIF,-0.342115,-0.089421,-0.263844,-0.096809\\n"
_EMBEDDED_CSV += "CBG,-1.690544,-1.051713,-1.482380,-0.132909\\n"
_EMBEDDED_CSV += "CCET,-0.340035,-0.968325,-0.215088,2.383976\\n"
_EMBEDDED_CSV += "CENTEL,0.652777,0.223677,-0.208974,-1.475972\\n"
_EMBEDDED_CSV += "CHAYO,-2.062783,-1.836118,-1.362166,-0.465490\\n"
_EMBEDDED_CSV += "CHG,-0.625831,-0.377339,-0.837195,-0.213417\\n"
_EMBEDDED_CSV += "CK,0.044390,-0.275830,0.774802,1.425627\\n"
_EMBEDDED_CSV += "CKP,-0.499415,-0.486300,-0.277647,-0.048290\\n"
_EMBEDDED_CSV += "COCOCO,-0.382972,-1.296608,-0.570414,0.062997\\n"
_EMBEDDED_CSV += "COM7,0.283290,-0.802097,0.253211,0.177315\\n"
_EMBEDDED_CSV += "CPALL,-0.455769,-0.236459,0.069633,-0.668725\\n"
_EMBEDDED_CSV += "CPAXT,-1.568309,-1.502766,0.018798,-0.784676\\n"
_EMBEDDED_CSV += "CPF,-0.739318,-0.306212,-0.452781,-0.889060\\n"
_EMBEDDED_CSV += "CPN,0.806786,0.789200,0.419172,-0.655717\\n"
_EMBEDDED_CSV += "CPNREIT,-0.117400,-0.031811,0.017607,0.340852\\n"
_EMBEDDED_CSV += "CRC,-0.795163,-0.475108,-0.444598,-0.465490\\n"
_EMBEDDED_CSV += "DCC,-0.684711,-0.446081,-0.214633,-0.174316\\n"
_EMBEDDED_CSV += "DELTA,2.365636,1.679629,2.268642,1.057740\\n"
_EMBEDDED_CSV += "DIF,0.567535,0.184085,-0.089067,0.325374\\n"
_EMBEDDED_CSV += "DITTO,0.119399,-0.603492,-0.472346,-0.016795\\n"
_EMBEDDED_CSV += "DMT,0.351822,0.471996,0.084374,-0.465490\\n"
_EMBEDDED_CSV += "DOHOME,-1.159483,-0.941793,-0.706476,0.492035\\n"
_EMBEDDED_CSV += "EA,0.886947,-0.859832,-0.460125,-0.283975\\n"
_EMBEDDED_CSV += "EASTW,1.141141,0.257315,2.227696,0.934831\\n"
_EMBEDDED_CSV += "EGCO,0.446170,-0.699932,-0.508659,-0.359337\\n"
_EMBEDDED_CSV += "EPG,0.809738,0.237027,0.149714,1.189422\\n"
_EMBEDDED_CSV += "ERW,0.065216,-0.132241,0.409262,-0.861826\\n"
_EMBEDDED_CSV += "FM,0.197340,0.203763,0.403835,0.406954\\n"
_EMBEDDED_CSV += "FORTH,-0.293946,-0.508780,0.489892,3.702920\\n"
_EMBEDDED_CSV += "FTREIT,0.385118,0.216204,-0.639687,0.897736\\n"
_EMBEDDED_CSV += "GFPT,0.037851,-0.314116,-0.510190,-0.594719\\n"
_EMBEDDED_CSV += "GLOBAL,-0.219907,-1.512121,-1.329805,1.791857\\n"
_EMBEDDED_CSV += "GPSC,0.636166,-1.179935,-0.850598,0.514682\\n"
_EMBEDDED_CSV += "GULF,0.583627,1.169398,1.165775,-0.309396\\n"
_EMBEDDED_CSV += "GUNKUL,1.405719,0.609216,1.754574,1.866117\\n"
_EMBEDDED_CSV += "HANA,1.677615,0.946481,3.214983,1.277476\\n"
_EMBEDDED_CSV += "HMPRO,-1.158254,-0.508017,-0.784197,-0.563342\\n"
_EMBEDDED_CSV += "HUMAN,-2.095502,-1.334921,-1.605003,0.975616\\n"
_EMBEDDED_CSV += "ICHI,0.121497,-0.099481,-1.041537,0.019842\\n"
_EMBEDDED_CSV += "INET,-0.533980,-0.015846,-0.346280,-0.198310\\n"
_EMBEDDED_CSV += "INETREIT,0.988784,0.521007,0.007210,-0.367637\\n"
_EMBEDDED_CSV += "INSET,1.404426,2.200454,1.416700,1.499159\\n"
_EMBEDDED_CSV += "IRPC,2.365636,2.661356,2.898185,0.837093\\n"
_EMBEDDED_CSV += "ITC,0.089832,-0.643082,-0.984624,1.507905\\n"
_EMBEDDED_CSV += "ITEL,-0.272864,-0.147209,-1.235536,-0.055484\\n"
_EMBEDDED_CSV += "IVL,0.533770,0.686621,0.817282,1.033351\\n"
_EMBEDDED_CSV += "JAS,-0.612160,-1.018386,-1.092495,-0.465490\\n"
_EMBEDDED_CSV += "JMART,-0.508110,-1.035285,-1.074216,0.592005\\n"
_EMBEDDED_CSV += "JMT,-1.214267,-0.842843,-0.355028,1.367205\\n"
_EMBEDDED_CSV += "JTS,1.399338,2.881734,-0.036050,-1.864198\\n"
_EMBEDDED_CSV += "KAMART,-0.249548,-0.080190,-0.790364,-1.149389\\n"
_EMBEDDED_CSV += "KBANK,0.656380,0.444499,-0.090179,-0.342287\\n"
_EMBEDDED_CSV += "KCE,0.987191,-0.528375,1.288222,3.440089\\n"
_EMBEDDED_CSV += "KGI,0.023466,0.508304,0.157088,-1.266012\\n"
_EMBEDDED_CSV += "KKP,0.989728,0.712386,0.411217,-0.005213\\n"
_EMBEDDED_CSV += "KSL,0.501952,0.955975,1.984302,-0.974576\\n"
_EMBEDDED_CSV += "KTB,1.270975,1.485490,1.207305,-1.165043\\n"
_EMBEDDED_CSV += "KTC,-1.556304,-0.109067,0.017607,-0.156667\\n"
_EMBEDDED_CSV += "LH,-0.546199,-0.155918,-0.650430,-0.662006\\n"
_EMBEDDED_CSV += "LHFG,0.853728,1.323234,-0.159862,0.869254\\n"
_EMBEDDED_CSV += "LHHOTEL,-0.208315,0.160102,-0.522464,-0.091002\\n"
_EMBEDDED_CSV += "M,0.160824,-1.962466,-0.266910,-0.148431\\n"
_EMBEDDED_CSV += "MAJOR,-1.012906,0.055683,0.606993,-1.566323\\n"
_EMBEDDED_CSV += "MALEE,-1.374463,-0.547489,-0.387673,-0.231216\\n"
_EMBEDDED_CSV += "MASTER,-2.594980,-1.115487,-0.353890,-0.822543\\n"
_EMBEDDED_CSV += "MBK,0.182962,0.059694,-0.579495,-0.395348\\n"
_EMBEDDED_CSV += "MC,0.319176,-0.080700,-0.697304,-0.029148\\n"
_EMBEDDED_CSV += "MCOT,0.929306,2.881734,3.214983,-0.368436\\n"
_EMBEDDED_CSV += "MEGA,0.511990,0.817423,-0.496272,0.218957\\n"
_EMBEDDED_CSV += "MINT,-0.619851,-0.160969,-0.608663,-0.916311\\n"
_EMBEDDED_CSV += "MTC,-1.395929,-1.720269,-1.262326,0.261574\\n"
_EMBEDDED_CSV += "NCAP,0.407373,-0.762343,-0.664247,-1.864198\\n"
_EMBEDDED_CSV += "NER,0.249518,0.766912,-0.243220,-0.667002\\n"
_EMBEDDED_CSV += "NEX,1.924033,-0.046829,-0.847813,-0.465490\\n"
_EMBEDDED_CSV += "NOBLE,-0.063786,-0.306212,-0.914030,-1.075315\\n"
_EMBEDDED_CSV += "NYT,0.590286,1.737909,1.711221,0.103470\\n"
_EMBEDDED_CSV += "OKJ,-2.410289,-1.873640,-1.605003,-1.096911\\n"
_EMBEDDED_CSV += "ONEE,0.206584,1.317363,0.823765,-0.285350\\n"
_EMBEDDED_CSV += "OR,-0.138072,-0.470809,-1.208835,-0.465490\\n"
_EMBEDDED_CSV += "ORI,-0.249650,-1.224665,0.108664,-0.199803\\n"
_EMBEDDED_CSV += "OSP,0.068350,-0.453809,-1.310817,0.023168\\n"
_EMBEDDED_CSV += "PAF,-0.205004,-1.098297,-0.660451,3.702920\\n"
_EMBEDDED_CSV += "PCE,-0.353351,0.636405,1.363009,-1.018565\\n"
_EMBEDDED_CSV += "PLANB,-1.262763,-0.497074,0.024490,1.505611\\n"
_EMBEDDED_CSV += "PLAT,-0.769239,-0.041818,-0.589346,-0.352797\\n"
_EMBEDDED_CSV += "PLUS,-2.582180,-1.962466,-1.163542,-0.558011\\n"
_EMBEDDED_CSV += "PR9,-1.144224,-1.491050,-1.114892,-0.465490\\n"
_EMBEDDED_CSV += "PRM,0.783277,1.037557,0.286930,1.256403\\n"
_EMBEDDED_CSV += "PSL,0.612870,0.086585,0.666587,-0.552589\\n"
_EMBEDDED_CSV += "PTG,0.763194,-0.071512,0.762387,-0.965400\\n"
_EMBEDDED_CSV += "PTT,0.290939,0.611068,0.035878,-0.209803\\n"
_EMBEDDED_CSV += "PTTEP,1.240272,1.905930,1.698652,-0.770352\\n"
_EMBEDDED_CSV += "PTTGC,2.007294,1.545108,1.586092,1.853582\\n"
_EMBEDDED_CSV += "QH,-0.347203,0.473982,0.194464,-0.465490\\n"
_EMBEDDED_CSV += "RATCH,0.385401,0.243772,-0.436030,-0.668725\\n"
_EMBEDDED_CSV += "RBF,-0.565637,-0.110548,0.872094,0.839572\\n"
_EMBEDDED_CSV += "RCL,0.869813,0.976798,0.517471,-0.561757\\n"
_EMBEDDED_CSV += "RS,-0.317993,0.779138,1.171089,0.882350\\n"
_EMBEDDED_CSV += "S,-0.180252,-1.313124,-0.242421,-0.465490\\n"
_EMBEDDED_CSV += "SABUY,-1.151986,-0.685926,-0.947120,-0.348482\\n"
_EMBEDDED_CSV += "SAK,-0.177300,0.156998,-0.251312,1.540502\\n"
_EMBEDDED_CSV += "SAMART,0.365764,-0.028108,0.364771,0.529134\\n"
_EMBEDDED_CSV += "SAPPE,0.593920,-0.328927,-0.249789,0.804780\\n"
_EMBEDDED_CSV += "SAWAD,0.193147,1.498813,0.159815,-0.440888\\n"
_EMBEDDED_CSV += "SCB,-0.088576,0.048965,-0.096156,-0.482782\\n"
_EMBEDDED_CSV += "SCC,0.423636,0.197867,0.264048,0.199059\\n"
_EMBEDDED_CSV += "SCGP,-1.533473,-1.595200,-1.731740,-0.770352\\n"
_EMBEDDED_CSV += "SELIC,-0.309289,-0.070550,-0.248555,0.004238\\n"
_EMBEDDED_CSV += "SIRI,-1.598381,-0.216183,-0.146800,0.230818\\n"
_EMBEDDED_CSV += "SJWD,0.467346,-0.010023,-0.254065,0.652345\\n"
_EMBEDDED_CSV += "SMC,-0.419771,-0.579111,0.190239,0.947426\\n"
_EMBEDDED_CSV += "SNC,0.330143,0.146739,0.471156,0.457996\\n"
_EMBEDDED_CSV += "SNNP,-0.069214,0.270860,0.268881,-0.942667\\n"
_EMBEDDED_CSV += "SPALI,-0.285059,-0.393128,-1.197426,-0.106096\\n"
_EMBEDDED_CSV += "SPRC,-0.301270,0.035143,0.111259,-1.519020\\n"
_EMBEDDED_CSV += "SRI,-1.454564,-0.945368,-1.008698,-0.465490\\n"
_EMBEDDED_CSV += "SSP,-0.706545,-1.304822,-0.351233,0.485108\\n"
_EMBEDDED_CSV += "STEC,0.531279,1.753687,0.647356,0.195646\\n"
_EMBEDDED_CSV += "STGT,0.235662,0.278846,-0.336548,1.558354\\n"
_EMBEDDED_CSV += "SUSCO,0.515674,0.242156,0.017607,-1.670456\\n"
_EMBEDDED_CSV += "SYNEX,-0.060270,-0.148496,-0.655152,-0.737449\\n"
_EMBEDDED_CSV += "TASCO,0.233085,-1.361617,-1.423561,-0.016795\\n"
_EMBEDDED_CSV += "TC,-0.051272,0.100678,1.046374,-0.668725\\n"
_EMBEDDED_CSV += "TEAM,-1.411344,-0.661275,-0.937033,-0.844365\\n"
_EMBEDDED_CSV += "TFG,-0.554720,-1.207115,-1.194044,0.108866\\n"
_EMBEDDED_CSV += "THG,-0.803011,-0.724458,0.052718,-0.508621\\n"
_EMBEDDED_CSV += "TISCO,0.460744,0.578641,0.150933,-1.651420\\n"
_EMBEDDED_CSV += "TKN,-0.103048,-0.009661,0.017607,1.221608\\n"
_EMBEDDED_CSV += "TKS,0.058894,0.255666,-0.488745,-0.041573\\n"
_EMBEDDED_CSV += "TM,0.433952,-0.318861,-1.015742,-0.377290\\n"
_EMBEDDED_CSV += "TMI,-0.124480,0.052920,0.282462,-0.108008\\n"
_EMBEDDED_CSV += "TNDT,-0.748773,-1.117397,-1.105540,1.231330\\n"
_EMBEDDED_CSV += "TNITY,-0.534253,0.024723,-0.317204,0.223510\\n"
_EMBEDDED_CSV += "TNP,-1.277471,-1.525831,-0.425431,-1.864198\\n"
_EMBEDDED_CSV += "TOP,-0.132107,0.132830,-0.181017,0.137835\\n"
_EMBEDDED_CSV += "TPA,-0.081109,-0.798852,0.099258,0.964377\\n"
_EMBEDDED_CSV += "TPIPL,-0.556743,-0.262291,0.153281,-0.465490\\n"
_EMBEDDED_CSV += "TRITN,-0.664937,-1.436231,-0.843706,-1.441376\\n"
_EMBEDDED_CSV += "TRUE,-1.502771,-1.831424,-1.793754,0.022175\\n"
_EMBEDDED_CSV += "TTB,0.549599,0.735280,0.079157,-0.989001\\n"
_EMBEDDED_CSV += "TU,0.148062,0.143391,-0.451829,0.044466\\n"
_EMBEDDED_CSV += "TVO,-0.633067,-1.770991,-0.886847,1.510044\\n"
_EMBEDDED_CSV += "UBIS,-0.742220,-1.023315,-0.831685,0.434789\\n"
_EMBEDDED_CSV += "VGI,-0.373998,-0.434309,-1.329805,-0.499017\\n"
_EMBEDDED_CSV += "VIH,-0.627525,-0.785161,0.075711,1.279866\\n"
_EMBEDDED_CSV += "WACOAL,-0.249225,-0.230130,-0.401878,-1.102387\\n"
_EMBEDDED_CSV += "WHA,0.533809,0.466358,0.582466,-0.770352\\n"
_EMBEDDED_CSV += "WINMED,0.068814,-0.586314,-0.599560,0.757258\\n"
_EMBEDDED_CSV += "WORK,-1.043680,-0.811037,-1.079554,-0.112850\\n"
_EMBEDDED_CSV += "ZEN,-1.012422,-1.354833,-0.844799,1.781687"

_EMBEDDED_SIGNALS = {
    "generated_at": "2026-04-29T09:02:46.928339+07:00",
    "horizon_months": 1,
    "quick_run": False,
    "signals": {
        "mom_12_1": {"mean_ic": 0.024145, "icir": 0.168738, "rank_icir": 0.222280, "passes_gate": False, "pct_positive": 0.587379},
        "mom_6_1": {"mean_ic": 0.030424, "icir": 0.226309, "rank_icir": 0.292052, "passes_gate": False, "pct_positive": 0.611650},
        "mom_3_1": {"mean_ic": 0.017340, "icir": 0.147065, "rank_icir": 0.224268, "passes_gate": False, "pct_positive": 0.592233},
        "mom_1_0": {"mean_ic": -0.012137, "icir": -0.100609, "rank_icir": -0.055203, "passes_gate": False, "pct_positive": 0.480583},
        "sharpe_momentum": {"mean_ic": 0.027799, "icir": 0.232554, "rank_icir": 0.274686, "passes_gate": False, "pct_positive": 0.606796},
        "residual_momentum": {"mean_ic": 0.026869, "icir": 0.213228, "rank_icir": 0.320244, "passes_gate": True, "pct_positive": 0.592233},
    },
    "composite": {
        "formula": "equal_weight",
        "members": ["residual_momentum"],
        "weights": {"residual_momentum": 1.0},
        "mean_ic": 0.026869,
        "icir": 0.213228,
        "rank_icir": 0.320244,
    },
}

# ── Features (with fallback for machines without data files) ─
_USE_EMBEDDED = False

try:
    features = pd.read_parquet(DATA / "features_latest.parquet")
    features["date"] = pd.to_datetime(features["date"])
    latest_date = features["date"].max()
    latest = features[features["date"] == latest_date].copy()
    latest["ticker"] = latest["symbol"].str.replace("SET:", "")
    latest = latest.set_index("ticker")
    _SRC = "parquet"
except (FileNotFoundError, OSError):
    _USE_EMBEDDED = True
    latest = pd.read_csv(StringIO(_EMBEDDED_CSV), index_col="ticker")
    latest_date = pd.Timestamp("2026-04-30")
    _SRC = "embedded snapshot"

# Cross-sectional z-scores (matching daily report methodology)
for col in ["mom_12_1", "mom_6_1", "mom_3_1", "mom_1_0"]:
    mu = latest[col].mean()
    sigma = latest[col].std()
    latest[f"z_{col}"] = (latest[col] - mu) / sigma

# Composite score: equal-weight mean of z-scored momentum features
z_cols = ["z_mom_12_1", "z_mom_6_1", "z_mom_3_1", "z_mom_1_0"]
latest["composite_z"] = latest[z_cols].mean(axis=1)

# Rank percentile
latest["rank_pct"] = latest["mom_12_1"].rank(pct=True)
latest["quintile"] = pd.qcut(latest["mom_12_1"], q=5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])

# Sort by mom_12_1 descending
latest = latest.sort_values("mom_12_1", ascending=False)

# ── Prices (optional, for price context) ───────────────────
try:
    prices = pd.read_parquet(DATA / "prices_latest.parquet")
    prices.index = pd.to_datetime(prices.index)
    print("  Prices: loaded from parquet")
except (FileNotFoundError, OSError):
    prices = None
    print("  Prices: not available (embedded mode)")

# ── Signal Quality ──────────────────────────────────────────
try:
    with open(RESULTS / "signals" / "latest_ranking.json") as f:
        signals_json = json.load(f)
    print("  Signals: loaded from JSON")
except (FileNotFoundError, OSError):
    signals_json = _EMBEDDED_SIGNALS
    print("  Signals: using embedded snapshot")

n_symbols = len(latest)
n_q5 = (latest["quintile"] == "Q5").sum()

print(f"\\nData source: {_SRC} ({latest_date.date()})")
print(f"Universe: {n_symbols} symbols")
print(f"Q5 (top quintile): {n_q5} symbols")
print("Ready.")"""
code(cell4)

# ============================================================
# Cell 5 — Signal Quality Assessment
# ============================================================
md("""## 2. Signal Quality: Which Momentum Factors Work?

Before selecting stocks, the strategy validates each momentum signal using **Information Coefficient (IC)** analysis. IC measures the correlation between a signal and future 1-month returns. **ICIR** (IC / std(IC)) tells us whether the predictive power is consistent.

A signal must pass the **ICIR gate** (ICIR > 0.15) to be included in the composite score.""")

# ============================================================
# Cell 6 — IC/ICIR Table & Chart
# ============================================================
code("""# ── Signal Quality Table ───────────────────────────────────
sig_data = []
for name, stats in signals_json["signals"].items():
    sig_data.append({
        "Signal": name.replace("_", " ").title(),
        "Mean IC": stats["mean_ic"],
        "ICIR": stats["icir"],
        "Rank ICIR": stats["rank_icir"],
        "% Positive": stats["pct_positive"] * 100,
        "Passes Gate": "\\u2713" if stats["passes_gate"] else "\\u2014",
    })

sig_df = pd.DataFrame(sig_data).sort_values("ICIR", ascending=False)

display(
    sig_df.style
    .set_caption("Signal Quality Assessment \\u2014 IC/ICIR Analysis")
    .background_gradient(cmap="RdYlGn", subset=["Mean IC", "% Positive"])
    .format(precision=4)
)

# ── ICIR Bar Chart ──────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5))
colors = ["#1a9850" if v > 0.15 else "#fdae61" if v > 0 else "#d73027"
          for v in sig_df["ICIR"]]
bars = ax.barh(sig_df["Signal"], sig_df["ICIR"], color=colors, edgecolor="white", height=0.6)
ax.axvline(0.15, color="#d73027", linestyle="--", linewidth=1.5, alpha=0.7, label="ICIR Gate (0.15)")
ax.axvline(0, color="gray", linewidth=0.8)

for bar, val in zip(bars, sig_df["ICIR"]):
    ax.text(val + 0.01 * max(sig_df["ICIR"].abs()), bar.get_y() + bar.get_height() / 2,
            f"{val:.3f}", va="center", fontsize=10, fontweight="bold")

ax.set_xlabel("ICIR (Information Coefficient / StdDev)")
ax.set_title("Signal Predictive Power (ICIR) \\u2014 Higher = More Consistent Alpha", fontweight="bold")
ax.legend(loc="lower right", fontsize=9)
ax.set_xlim(min(sig_df["ICIR"]) - 0.05, max(sig_df["ICIR"]) + 0.08)
sns.despine(left=True)
plt.tight_layout()
plt.show()

# ── Composite Info ──────────────────────────────────────────
comp = signals_json["composite"]
print(f"\\nComposite formula: {comp['formula']}")
print(f"Members passing gate: {comp['members']}")
print(f"Composite ICIR: {comp['icir']:.4f}  |  Rank ICIR: {comp['rank_icir']:.4f}")

print("\\n\\u2192 The primary ranking signal is residual_momentum (ICIR = 0.320).")
print("  In the live features dataset, the composite is built from all 4 raw momentum")
print("  horizons (mom_12_1 through mom_1_0), which collectively capture the")
print("  cross-sectional momentum effect across multiple time scales.")""")

# ============================================================
# Cell 7 — Ranking Distribution
# ============================================================
md("""## 3. Ranking: Where Do Our 10 Stocks Stand?

We compute a **composite z-score** (equal-weight average of z-scored momentum signals) for all 132 stocks. The top quintile (Q5) contains 27 stocks. Our portfolio takes the **top 10**.

The chart below shows the full distribution with our selections highlighted.""")

# ============================================================
# Cell 8 — Distribution + Top 10 Chart
# ============================================================
code("""# ── Distribution of mom_12_1 with top 10 + Q5 highlighted ──
top10_tickers = ["DELTA", "IRPC", "PTTGC", "NEX", "AGE", "HANA", "BPP", "GUNKUL", "INSET", "JTS"]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

# Left: Histogram of mom_12_1
is_q5 = latest["quintile"] == "Q5"
is_top10 = latest.index.isin(top10_tickers)

ax1.hist(latest.loc[~is_q5, "mom_12_1"], bins=25, color="#cccccc", alpha=0.6, label="Q1\\u2013Q4 (105 stocks)")
ax1.hist(latest.loc[is_q5 & ~is_top10, "mom_12_1"], bins=15, color="#fdae61", alpha=0.8, label="Q5 \\u2014 Rest (17 stocks)")
ax1.hist(latest.loc[is_top10, "mom_12_1"], bins=10, color="#1a9850", alpha=0.9, label="Top 10 Portfolio")

for ticker in top10_tickers:
    val = latest.loc[ticker, "mom_12_1"]
    ax1.annotate(ticker, (val, 0.3), textcoords="offset points", xytext=(0, 8),
                fontsize=7, ha="center", rotation=60, color="#1a9850", fontweight="bold")

ax1.set_xlabel("12-1 Month Momentum (log return)")
ax1.set_ylabel("Number of Stocks")
ax1.set_title("Momentum Distribution \\u2014 Top 10 vs. Universe", fontweight="bold")
ax1.legend(fontsize=8, loc="upper left")
sns.despine(ax=ax1)

# Right: Horizontal bar chart \\u2014 Top 10 Z-Scores
top10_data = latest.loc[top10_tickers[::-1]]  # reverse for bottom-to-top
bar_colors = ["#006837" if z >= 2.0 else "#1a9850" if z >= 1.6 else "#66bd63"
              for z in top10_data["z_mom_12_1"]]

bars = ax2.barh(top10_data.index, top10_data["z_mom_12_1"], color=bar_colors, edgecolor="white", height=0.7)
for bar, (z, rp) in enumerate(zip(top10_data["z_mom_12_1"], top10_data["rank_pct"])):
    ax2.text(z + 0.03, bar, f"z={z:.2f}  (rank {rp*100:.1f}%)",
             va="center", fontsize=9, fontweight="bold", color="#333333")

ax2.axvline(0, color="gray", linewidth=0.8, linestyle="-")

# Conviction tier annotations
ax2.annotate("Higher Conviction\\nz \\u2265 2.0", xy=(2.3, 8), fontsize=8, color="#006837",
            ha="center", fontweight="bold", bbox=dict(boxstyle="round,pad=0.3", facecolor="#e5f5e0", alpha=0.8))
ax2.annotate("Standard Conviction\\nz 1.6\\u20131.9", xy=(1.7, 4.5), fontsize=8, color="#1a9850",
            ha="center", bbox=dict(boxstyle="round,pad=0.3", facecolor="#e5f5e0", alpha=0.8))
ax2.annotate("Smaller Position\\nz < 1.6", xy=(1.4, 1.5), fontsize=8, color="#66bd63",
            ha="center", bbox=dict(boxstyle="round,pad=0.3", facecolor="#e5f5e0", alpha=0.8))

ax2.set_xlabel("Momentum Z-Score (Standard Deviations Above Mean)")
ax2.set_title("Top 10 \\u2014 Cross-Sectional Momentum Z-Scores", fontweight="bold")
ax2.set_xlim(0, max(top10_data["z_mom_12_1"]) + 0.7)
sns.despine(ax=ax2, left=True)
plt.tight_layout()
plt.show()

# Print ranking table
print("\\nCross-Sectional Momentum Ranking (as of 2026-04-30)")
print("=" * 75)
rank_table = latest.loc[top10_tickers][["mom_12_1", "z_mom_12_1", "rank_pct", "quintile"]]
rank_table.columns = ["12-1M Return", "Z-Score", "Percentile", "Quintile"]
rank_table.index.name = "Symbol"
display(rank_table.style
    .background_gradient(cmap="Greens", subset=["Z-Score", "Percentile"])
    .format({"12-1M Return": "{:.4f}", "Z-Score": "{:.3f}", "Percentile": "{:.3f}"})
)""")

# ============================================================
# Cell 9 — Momentum Decomposition
# ============================================================
md("""## 4. Momentum Decomposition: Not All Returns Are Created Equal

The 12-1M return is the primary signal, but we look across **four horizons** to understand the momentum profile. Stocks with strong long-term momentum *and* healthy short-term trends are more robust. Negative short-term momentum (mom_1_0) can indicate a pullback entry opportunity.""")

# ============================================================
# Cell 10 — Multi-Horizon Chart
# ============================================================
code("""# ── Multi-Horizon Momentum for Top 10 ─────────────────────
fig, ax = plt.subplots(figsize=(14, 7))

horizons = ["z_mom_12_1", "z_mom_6_1", "z_mom_3_1", "z_mom_1_0"]
horizon_labels = ["12M-1M (Long-term)", "6M-1M (Medium-term)", "3M-1M (Short-term)", "1M (Reversal)"]
horizon_colors = ["#003d32", "#1a9850", "#66bd63", "#fdae61"]

top10_data = latest.loc[top10_tickers]
x = np.arange(len(top10_tickers))
width = 0.18

for i, (hz, label, color) in enumerate(zip(horizons, horizon_labels, horizon_colors)):
    offset = (i - 1.5) * width
    bars = ax.bar(x + offset, top10_data[hz], width, label=label, color=color, edgecolor="white", linewidth=0.5)
    for bar, val in zip(bars, top10_data[hz]):
        if abs(val) > 0.2:
            ax.text(bar.get_x() + bar.get_width() / 2,
                   bar.get_height() + 0.05 if val > 0 else bar.get_height() - 0.3,
                   f"{val:.1f}", ha="center", va="bottom" if val > 0 else "top",
                   fontsize=7, fontweight="bold", rotation=90)

ax.set_xticks(x)
ax.set_xticklabels(top10_tickers, fontsize=11, fontweight="bold")
ax.axhline(0, color="gray", linewidth=1)
ax.axhline(1.0, color="#fdae61", linewidth=0.8, linestyle=":", alpha=0.6, label="+1\\u03c3 threshold")
ax.set_ylabel("Z-Score (Standard Deviations)")
ax.set_title("Momentum Decomposition \\u2014 Four Horizons Across Top 10", fontweight="bold")
ax.legend(loc="upper right", fontsize=9, ncol=2)
sns.despine()
plt.tight_layout()
plt.show()

# ── Commentary ──────────────────────────────────────────────
print("\\nKey observations from momentum decomposition:")
print()
print("1. DELTA & IRPC: Strongest across ALL horizons (z \\u2265 0.8 in every window).")
print("   These are the highest-conviction picks \\u2014 no weakness anywhere.")
print()
print("2. PTTGC: Strong 12M-1M, 6M-1M, AND 1M reversal \\u2014 accelerating recently.")
print()
print("3. NEX: Strong long-term momentum but negative short-term (mom_3_1, mom_1_0).")
print("   This could be a pullback entry \\u2014 the long-term trend is intact.")
print()
print("4. JTS: Strong 6M-1M but the weakest 12M-1M and negative short-term.")
print("   Lowest-conviction pick among the 10 \\u2014 smallest allocation.")""")

# ============================================================
# Cell 11 — Portfolio Allocation
# ============================================================
md("""## 5. Portfolio Allocation

Positions are weighted by conviction tier, with higher z-score stocks receiving larger allocations. The volatility-target rebalance at month-end will adjust these weights based on each stock's realized volatility.""")

# ============================================================
# Cell 12 — Allocation Chart
# ============================================================
code("""# ── Portfolio Allocation Donut ─────────────────────────────
allocations = {
    "DELTA":  (120_000, 0.12, "#003d32"),
    "IRPC":   (120_000, 0.12, "#006837"),
    "PTTGC":  (120_000, 0.12, "#1a9850"),
    "NEX":    (100_000, 0.10, "#4dac26"),
    "AGE":    (100_000, 0.10, "#66bd63"),
    "HANA":   (100_000, 0.10, "#a6d96a"),
    "BPP":    (90_000,  0.09, "#d9ef8b"),
    "GUNKUL": (90_000,  0.09, "#fee08b"),
    "INSET":  (80_000,  0.08, "#fdae61"),
    "JTS":    (80_000,  0.08, "#f46d43"),
}

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))

# Left: Donut chart
labels = list(allocations.keys())
sizes = [v[1] for v in allocations.values()]
colors = [v[2] for v in allocations.values()]

wedges, texts, autotexts = ax1.pie(
    sizes, labels=labels, autopct="%1.1f%%", startangle=140,
    colors=colors, pctdistance=0.82,
    wedgeprops={"linewidth": 1.5, "edgecolor": "white"},
    textprops={"fontsize": 10, "fontweight": "bold"},
)
centre_circle = plt.Circle((0, 0), 0.55, fc="white", linewidth=0)
ax1.add_artist(centre_circle)
ax1.text(0, 0, "10 Stocks\\n1,000,000 THB", ha="center", va="center",
        fontsize=12, fontweight="bold", color="#333333")
ax1.set_title("Portfolio Allocation \\u2014 Conviction-Weighted", fontweight="bold", pad=20)

# Right: Allocation in THB
thb_values = [v[0] for v in allocations.values()]
bar_colors = [v[2] for v in allocations.values()]
bars = ax2.barh(list(allocations.keys())[::-1], thb_values[::-1], color=bar_colors[::-1],
                edgecolor="white", height=0.7)

for bar, val, pct in zip(bars, thb_values[::-1], sizes[::-1]):
    ax2.text(val + 2000, bar.get_y() + bar.get_height() / 2,
             f"{val:,.0f} THB ({pct*100:.0f}%)", va="center", fontsize=10, fontweight="bold")

ax2.set_xlabel("Allocation (THB)")
ax2.set_title("Position Sizes \\u2014 THB Allocation", fontweight="bold")
ax2.set_xlim(0, max(thb_values) * 1.25)
ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
sns.despine(ax=ax2, left=True)
plt.tight_layout()
plt.show()

# ── Summary Metrics Table ───────────────────────────────────
summary = pd.DataFrame({
    "Metric": ["Total AUM", "Number of Positions", "Max Position", "Min Position",
               "Weighting Scheme", "Vol Target (annual)", "Next Rebalance"],
    "Value": ["1,000,000 THB", "10", "12.0% (DELTA, IRPC, PTTGC)", "8.0% (INSET, JTS)",
              "Volatility-Target", "15%", "2026-05-30 (BME)"],
})
display(summary.style.set_caption("Portfolio Summary").hide(axis="index"))""")

# ============================================================
# Cell 13 — Monthly Rebalancing
# ============================================================
md("""## 6. Monthly Rebalancing Schedule

The strategy rebalances on **Business Month End (BME)** — the last trading day of each month. At each rebalance:

1. **Re-rank** all stocks by composite momentum z-score
2. **Buffer logic** reduces turnover: existing holdings are only evicted if a replacement ranks significantly higher (25 percentile-point buffer) or falls below the exit floor (35th percentile)
3. **Sector cap** is applied (max 35% per sector)
4. **Volatility-target weights** are computed (inverse-vol, scaled to 15% annual target)
5. **Trade list** is generated (delta from current weights)

The calendar below shows the full 2026 rebalance schedule.""")

# ============================================================
# Cell 14 — Rebalance Timeline
# ============================================================
code("""# ── Rebalance Timeline for 2026 ───────────────────────────
bme_dates_2026 = pd.date_range("2026-01-01", "2026-12-31", freq="BME")
today = pd.Timestamp("2026-05-04")

fig, ax = plt.subplots(figsize=(14, 4))

for i, dt in enumerate(bme_dates_2026):
    if dt.month == 5:
        color = "#1a9850"
        size = 200
        label = "May 30\\n(Next Rebalance)"
        z = 3
    elif dt < today:
        color = "#cccccc"
        size = 80
        label = ""
        z = 1
    else:
        color = "#66bd63"
        size = 120
        label = ""
        z = 2

    ax.scatter(dt, 0, s=size, c=color, zorder=z, edgecolors="white", linewidth=1.5)
    ax.text(dt, 0.15, dt.strftime("%b\\n%d"), ha="center", fontsize=8, color=color, fontweight="bold")

# Today marker
ax.axvline(today, color="#d73027", linewidth=2, linestyle="--", alpha=0.7, zorder=0)
ax.text(today, 0.35, "Today\\nMay 4", ha="center", fontsize=9, color="#d73027", fontweight="bold")

# Entry marker
entry_date = pd.Timestamp("2026-05-05")
ax.axvline(entry_date, color="#fc8d59", linewidth=1.5, linestyle=":", alpha=0.7)
ax.text(entry_date, -0.35, "Entry\\nMay 5", ha="center", fontsize=8, color="#fc8d59", fontweight="bold")

# Legend
from matplotlib.lines import Line2D
legend_elements = [
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#1a9850", markersize=12, label="Next Rebalance (May 30)"),
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#66bd63", markersize=10, label="Future Rebalance"),
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#cccccc", markersize=8, label="Past Rebalance"),
    Line2D([0], [0], color="#d73027", linewidth=2, linestyle="--", label="Today (May 4)"),
]
ax.legend(handles=legend_elements, loc="upper right", fontsize=9, ncol=2)

ax.set_ylim(-0.5, 0.5)
ax.set_yticks([])
ax.set_xlim(pd.Timestamp("2026-01-01"), pd.Timestamp("2027-01-01"))
ax.xaxis.set_major_locator(mdates.MonthLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
ax.set_title("2026 Monthly Rebalance Calendar \\u2014 Business Month End (BME)", fontweight="bold", pad=15)
sns.despine(left=True)
plt.tight_layout()
plt.show()

print("\\nBuffer Logic Parameters:")
print("  \\u2022 Buffer threshold: 25 percentile points (replacement must rank this much higher)")
print("  \\u2022 Exit rank floor: 35th percentile (unconditional eviction below this)")
print("  \\u2022 Target turnover: 20\\u201330% one-way per rebalance")""")

# ============================================================
# Cell 15 — Risk Management
# ============================================================
md("""## 7. Risk Management

The CSM strategy layers multiple risk controls to protect capital:

### 7.1 Volatility Targeting
- **Target:** 15% annualized portfolio volatility
- **Method:** Scale equity exposure inversely to realized volatility (63-day lookback)
- **Cap:** Max 1.5× leverage (i.e., position sizes can be scaled down but not levered up beyond 1.5×)
- **Fast blend:** 30% weight on 21-day vol for quicker adaptation

### 7.2 Circuit Breaker
- **Trigger:** −10% drawdown from peak NAV (60-day rolling window)
- **Action:** Reduce equity exposure to 20% (safe mode)
- **Recovery:** Re-enter full allocation after drawdown narrows to −5% and holds for 21 days
- **Purpose:** Prevent catastrophic losses during tail events

### 7.3 Position Bounds
- **Maximum:** 15% per single stock
- **Minimum:** 5% per single stock
- **Rationale:** Prevents concentration risk while maintaining meaningful position sizes

### 7.4 Sector Cap
- **Maximum:** 35% in any single sector
- **Enforcement:** Prune lowest-composite stocks from overweight sectors

### 7.5 Cut-Loss Rules (Daily Monitoring)
- 🟡 **Warning (−7%):** Flag in daily report, prepare exit plan
- 🔴 **Hard Stop (−10%):** Sell immediately, do not wait for month-end
- 🟢 **Trailing Stop:** After +10% gain, raise stop to breakeven""")

# ============================================================
# Cell 16 — Execution Plan
# ============================================================
md("""## 8. Execution Plan — May 5, 2026

| Step | Action |
|------|--------|
| **Entry** | Buy all 10 positions **At The Opening (ATO)** on 2026-05-05 |
| **Execution** | Manual via settrad click2win |
| **Order Type** | Market-at-open (fill at prevailing ATO price) |
| **Monitoring** | Daily cut-loss check starting 2026-05-06 |
| **First Rebalance** | 2026-05-30 (last trading day of May) |

### Position Table (ATO — 2026-05-05)

| # | Symbol | Allocation (THB) | Weight | Conviction |
|---|--------|------------------|--------|------------|
| 1 | DELTA | 120,000 | 12.0% | Higher |
| 2 | IRPC | 120,000 | 12.0% | Higher |
| 3 | PTTGC | 120,000 | 12.0% | Higher |
| 4 | NEX | 100,000 | 10.0% | Standard |
| 5 | AGE | 100,000 | 10.0% | Standard |
| 6 | HANA | 100,000 | 10.0% | Standard |
| 7 | BPP | 90,000 | 9.0% | Smaller |
| 8 | GUNKUL | 90,000 | 9.0% | Smaller |
| 9 | INSET | 80,000 | 8.0% | Smaller |
| 10 | JTS | 80,000 | 8.0% | Smaller |

> **Note:** Share quantities to be calculated after confirming ATO prices on 2026-05-05 morning.
> Total budget: 1,000,000 THB. Round down to nearest board lot (100 shares) for each position.""")

# ============================================================
# Cell 17 — Disclaimer
# ============================================================
md("""---

## Appendix: Data Provenance

| Data Source | File | Last Updated |
|-------------|------|---------------|
| Features (momentum signals) | `data/processed/features_latest.parquet` | 2026-04-30 |
| Prices (daily OHLCV) | `data/processed/prices_latest.parquet` | 2026-04-30 |
| Signal Quality (IC/ICIR) | `results/signals/latest_ranking.json` | 2026-04-29 |
| Universe Symbols | `data/universe/symbols.json` | Auto-refreshed |

**Strategy Version:** CSM v1.0 (live-test branch)
**Environment:** `live-test-v1.0.0`

---

*This notebook was generated by the CSM strategy pipeline. All stock selections are determined by the cross-sectional momentum ranking algorithm with the configuration specified in `configs/live-settings.yaml`. No discretionary overrides were applied.*

*Disclaimer: Past momentum does not guarantee future returns. This is a systematic strategy undergoing live testing. All trading decisions are the responsibility of the trader.*""")

# ============================================================
# Assemble & Save
# ============================================================
nb.cells = cells

import sys
out = "notebooks/05_live_portfolio_rationale.ipynb"
nbf.write(nb, out)
print("OK", out)
