---
name: self-port-streamlit-orchestrator
description: Self_Port Streamlit 앱에 아린이 포트폴리오 모니터와 유니버스 분석 탭을 추가하는 4명 에이전트 팀을 조율하는 오케스트레이터. data-engineer, portfolio-monitor-builder, universe-analyst-builder, qa-validator를 파이프라인 + 병렬 + 점진적 QA로 운용한다. Self_Port.xlsx, S&P500.xlsx, Index.xlsx를 다루는 모든 통합 작업에 사용한다.
---

# Self_Port Streamlit Orchestrator

## 왜 이 오케스트레이터가 필요한가
4개 에이전트가 단일 산출물(`Self_port.py` 통합)에 수렴해야 한다. data-engineer가 만든 인터페이스를 두 빌더가 동시에 의존하고, qa-validator가 각 단계마다 끼어들어야 한다. 이 조율을 사람이 매번 하면 비싼다 — 한 번의 오케스트레이터 호출로 끝낸다.

## 실행 모드: 에이전트 팀 (TeamCreate)

이유:
- data-engineer 산출이 두 빌더의 입력
- 두 빌더는 병렬 가능
- qa-validator가 매 체크포인트마다 개입
- 빌더 간 메시지 교환 필요(공통 헬퍼 발견 시 합의)

## 워크플로우

### Phase 1: 데이터 기반 (직렬)
```
[data-engineer]
  ├─ port/lib/__init__.py 생성
  ├─ port/lib/data_loader.py 작성
  │     load_self_port_holdings, load_universe_tickers,
  │     load_sp500_panel, load_spx_index, load_px_last
  ├─ port/lib/calendar_utils.py 작성
  │     get_business_calendar, reindex_to_business_days, last_n_years
  ├─ port/lib/live_price.py 작성 (Yahoo Finance 폴백)
  │     bloomberg_to_yahoo, fetch_yahoo_latest, yfinance_available
  └─ 인터페이스(함수 시그니처 + 반환 shape) 발표
       SendMessage to: portfolio-monitor-builder, universe-analyst-builder

[qa-validator] ← incremental QA #1
  └─ CP-1 체크 실행 (data-quality-qa 스킬 참조)
       산출: port/_workspace/qa_report_phase1.md
```

### Phase 2: 두 탭 병렬
```
[portfolio-monitor-builder]              [universe-analyst-builder]
  ├─ port/lib/tab_portfolio_monitor.py     ├─ port/lib/tab_universe_analyst.py
  │     render_portfolio_monitor_tab()     │     render_universe_analyst_tab()
  │     + 내부 헬퍼                         │     + 내부 헬퍼
  └─ "완료" SendMessage                     └─ "완료" SendMessage

[qa-validator] ← incremental QA #2, #3
  ├─ CP-2 체크 (portfolio_monitor)
  └─ CP-3 체크 (universe_analyst)
       산출: port/_workspace/qa_report_phase2.md
```

### Phase 3: 통합
```
[portfolio-monitor-builder + universe-analyst-builder + data-engineer]
  └─ port/Self_port.py 수정
       1) import 추가
       2) st.tabs 라벨 리스트 끝에 두 새 라벨 추가
       3) tabs[-2], tabs[-1]에서 render_*_tab() 호출

[qa-validator] ← incremental QA #4
  └─ CP-4 체크: streamlit run, 두 탭 렌더링 확인
       산출: port/_workspace/qa_report_phase3.md
```

## 데이터 전달

| 산출물 | 위치 | 책임 |
|---|---|---|
| 데이터 로더 | `port/lib/data_loader.py` | data-engineer |
| 영업일 헬퍼 | `port/lib/calendar_utils.py` | data-engineer |
| 포트폴리오 탭 | `port/lib/tab_portfolio_monitor.py` | portfolio-monitor-builder |
| 유니버스 탭 | `port/lib/tab_universe_analyst.py` | universe-analyst-builder |
| 통합 진입 | `port/Self_port.py` (수정) | 세 빌더 협업 |
| QA 리포트 | `port/_workspace/qa_report_phase{N}.md` | qa-validator |
| 인터페이스 합의 | `port/_workspace/00_data_engineer_interface.md` | data-engineer |

## 에이전트 팀 구성 호출 패턴

```python
TeamCreate(
    team_name="self-port-builders",
    members=[
        {"agent": "data-engineer", "model": "opus"},
        {"agent": "portfolio-monitor-builder", "model": "opus"},
        {"agent": "universe-analyst-builder", "model": "opus"},
        {"agent": "qa-validator", "model": "opus"},
    ],
)

TaskCreate(tasks=[
    {"id": "p1-loader", "assignee": "data-engineer", ...},
    {"id": "p1-qa", "assignee": "qa-validator", "deps": ["p1-loader"]},
    {"id": "p2-portfolio", "assignee": "portfolio-monitor-builder", "deps": ["p1-loader"]},
    {"id": "p2-universe", "assignee": "universe-analyst-builder", "deps": ["p1-loader"]},
    {"id": "p2-qa", "assignee": "qa-validator", "deps": ["p2-portfolio", "p2-universe"]},
    {"id": "p3-integrate", "assignees": ["portfolio-monitor-builder", "universe-analyst-builder", "data-engineer"], "deps": ["p2-qa"]},
    {"id": "p3-qa", "assignee": "qa-validator", "deps": ["p3-integrate"]},
])
```

## 에러 핸들링

| 에러 유형 | 1차 대응 | 2차 대응 |
|---|---|---|
| 파일 누락 (xlsx) | data-engineer가 명확한 메시지로 raise | 사용자에게 경로 확인 요청 |
| 시트명 불일치 | data-engineer가 `pd.ExcelFile.sheet_names`를 메시지에 포함 | 정확한 시트명 plan에 기록 후 재시도 |
| 티커 매칭 실패 | 빌더가 graceful 제외 + 경고 로그 | 누락 티커 리스트 사용자에게 보고 |
| 캐시 stale | `st.cache_data.clear()` + rerun | 파일 mtime 캐시 키 적용 |
| Streamlit 실행 실패 | 환경(패키지 누락) vs 코드 문제 구분 | 환경이면 `pip install`, 코드면 빌더에게 회귀 |

원칙: 1회 재시도 후 재실패 시 해당 결과 없이 진행하며 보고서에 누락 명시.

## 검증 시나리오

### 정상 흐름
1. `streamlit run port/Self_port.py`
2. 기존 7개 탭이 모두 정상
3. 끝에 "🎀 아린이 포트폴리오", "🔍 유니버스 분석" 두 탭이 추가됨
4. 아린이 포트폴리오: Sheet2 보유 종목의 카드/차트/월별 탭 렌더링
5. 유니버스 분석: Ticker_Arin 다중 선택 → EPS/Sales 시계열 + 모멘텀 테이블

### 에러/경계 흐름
1. Self_Port.xlsx Sheet2 빈 상태 → "보유 종목이 없어요" 메시지
2. Universe 시트의 티커가 BEST_EPS 컬럼에 없음 → "(데이터 없음)" 라벨, 차트 정상
3. SPX Index 시트 비어 있음 → 폴백 메시지
4. 사용자가 종목 0개 선택 → "1개 이상 선택해 주세요" 안내

### 회귀 케이스
- Self_Port.xlsx에 새 행 추가 후 새로고침 버튼 → 카드 즉시 갱신
- BEST_EPS의 마지막 영업일 데이터가 NaN → 모멘텀이 NaN 표시되지만 차트는 직전 값까지 그림
- 일별 수익률 합과 누적 수익률 차이 < 1e-5 (부동소수 허용)

## 절대 하지 말 것

- `.claude/commands/`에 슬래시 커맨드 생성
- 기존 7개 탭 코드 수정
- xlsx 파일 자체 수정 (읽기 전용)
- Self_port.py 안에 데이터 로딩 로직 직접 작성 (lib/로 분리)

## 테스트 시나리오

**시나리오 A — 정상 부팅**
- 입력: 모든 xlsx 파일 정상 위치
- 기대: 4개 단계 통과, qa_report_phase{1,2,3}.md 생성, 9개 탭 정상

**시나리오 B — 시트명 변경**
- 입력: Index.xlsx의 SPX Index 시트가 SPX_Index로 잘못 변경됨
- 기대: data-engineer가 명확한 KeyError + 시트 목록 보고, Phase 1에서 멈춤
