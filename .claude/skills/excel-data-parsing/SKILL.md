---
name: excel-data-parsing
description: Self_Port.xlsx, S&P500.xlsx, Index.xlsx의 시트와 컬럼을 정확한 이름으로 로드하는 스킬. .xlsx 파일을 읽거나, Bloomberg 티커 형식 컬럼을 다루거나, BEST_EPS/BEST_SALES/PX_LAST 시트를 사용하거나, SPX Index 영업일을 마스터 캘린더로 사용할 때 반드시 이 스킬을 사용한다.
---

# Excel Data Parsing for Self_Port

## 왜 이 스킬이 필요한가
이 프로젝트의 Excel 파일들은 사람이 입력한 시트명과 실제 시트명이 미묘하게 다르다. 사용자가 `EntryPrice`, `SPX_INDEX`라고 말해도 실제 파일은 `Entry_Price`, `SPX Index`이다. 이 차이를 무시하면 KeyError로 앱이 죽는다. 또한 컬럼 0이 `date`로 통일되어 있고 나머지 컬럼이 Bloomberg 티커(`AAPL US Equity` 형식)이므로, pandas 인덱싱 시 일관된 패턴이 필요하다.

## 파일별 표준 (반드시 준수)

### Self_Port.xlsx
경로: `C:\Users\westl\PycharmProjects\pythonProject\venv_vf_new\port\Self_Port.xlsx`

| 시트명 | 컬럼 | 용도 |
|---|---|---|
| `Sheet1` | Date, Ticker, Number, Entry_Price, Price | (다른 기능에서 사용 — 건드리지 말 것) |
| `Sheet2` | Date, Ticker, Number, Entry_Price, Price | **아린이 포트폴리오 — 이것을 사용** |
| `Universe` | Ticker, Ticker_Arin | **유니버스 분석 — Ticker_Arin 컬럼만 사용** |

```python
import pandas as pd
df = pd.read_excel(SELF_PORT_PATH, sheet_name="Sheet2", engine="openpyxl")
# 컬럼명 그대로: 'Entry_Price' (언더스코어 포함, EntryPrice 아님)
universe = pd.read_excel(SELF_PORT_PATH, sheet_name="Universe", engine="openpyxl")
tickers = universe["Ticker_Arin"].dropna().tolist()
```

### S&P500.xlsx
경로: `C:\Users\westl\PycharmProjects\pythonProject\S&P500.xlsx` (port 디렉토리 부모!)

18개 시트. 패턴이 통일되어 있다:
- 컬럼 0: `date`
- 컬럼 1~: Bloomberg 티커 (`AAPL US Equity`, `MSFT US Equity`, ...)
- 행 수: 약 4,479~4,503 (daily 2014~)

| 시트명 | 의미 |
|---|---|
| `BEST_EPS` | Forward EPS 컨센서스 추정치 |
| `BEST_SALES` | Forward Sales 컨센서스 추정치 |
| `PX_LAST` | 종가 (현재가 조회용) |
| `BEST_PE_RATIO`, `CUR_MKT_CAP`, ... | (이번 작업에서는 미사용) |

특수 시트:
- `SPX Index` (3 cols, long format): date, Ticker, SPX Index
- `Earnings_Date`: date + 65 tickers (0/1 플래그)

```python
def load_panel(path, sheet):
    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df  # columns = Bloomberg tickers
```

### Index.xlsx
경로: `C:\Users\westl\PycharmProjects\pythonProject\Index.xlsx`

| 시트명 | 컬럼 | 용도 |
|---|---|---|
| `SPX Index` (공백 포함!) | date, Ticker, SPX Index | **영업일 마스터** |
| `PX_LAST` | date + 인덱스명들 | (참고용) |

**경고**: 사용자가 `SPX_INDEX`라고 말해도 실제는 `SPX Index`. `pd.read_excel(..., sheet_name="SPX Index")`로 정확히 호출.

```python
spx = pd.read_excel(INDEX_PATH, sheet_name="SPX Index", engine="openpyxl")
spx["date"] = pd.to_datetime(spx["date"])
business_calendar = pd.DatetimeIndex(spx["date"].sort_values().unique())
```

## 캐싱 패턴 (필수)

Streamlit 앱에서 모든 로드 함수는 `@st.cache_data`로 감싼다. 파일 mtime을 인자로 넘겨 변경 시 자동 무효화:

```python
import os
import streamlit as st

def _file_mtime(path: str) -> float:
    return os.path.getmtime(path) if os.path.exists(path) else 0

@st.cache_data
def load_panel_cached(path: str, sheet: str, _mtime: float) -> pd.DataFrame:
    return load_panel(path, sheet)

# 호출 시
df = load_panel_cached(PATH, "BEST_EPS", _file_mtime(PATH))
```

`_mtime` 앞의 언더스코어가 아니라 일반 인자로 넣어 캐시 키에 포함되도록 한다.

## 에러 핸들링
- 시트명이 다를 때: `pd.ExcelFile(path).sheet_names`를 함께 메시지에 포함
- 티커가 컬럼에 없을 때: `df.get(ticker)` 또는 `if ticker in df.columns` 체크 후 빈 Series 반환
- date 파싱 실패: 명시적으로 `pd.to_datetime(..., errors="coerce")` 후 NaT 비율 확인
