# Streamlit Cloud 배포 가이드 — 핸드폰에서 보는 법

이 가이드는 한 번만 따라하면 되고, 그 다음부터는 [`daily_run.bat`](daily_run.bat)
한 번만 더블클릭하면 핸드폰에서도 자동 갱신된 대시보드를 볼 수 있어요.

---

## 1️⃣ Streamlit Cloud 앱 만들기 (1회)

1. https://share.streamlit.io 접속 → GitHub 계정으로 로그인
2. 우측 상단 **"New app"** → **"From existing repo"**
3. 입력:
   | 필드 | 값 |
   |---|---|
   | Repository | `dnflsfud/portfolio-dashboard` |
   | Branch | `claude/interesting-einstein-9b6bc8` |
   | Main file path | `Self_port_cloud.py` |
   | Python version | 3.11 (또는 3.12) |
4. **"Advanced settings"** → 아무것도 안 건드려도 됨 (`requirements.txt` 자동 인식)
5. **"Deploy"** 클릭 → 처음 빌드는 약 3~5분
6. 완료되면 URL이 발급됨. 예: `https://aerin-portfolio.streamlit.app`

> **Private 옵션**: 보유 종목/거래 데이터가 노출되는 게 싫으면 GitHub repo를
> **Private**로 바꾸세요. Streamlit Cloud는 private repo도 그대로 지원합니다.
> 단 **Free tier에서 private repo는 1개만 허용**돼요.

---

## 2️⃣ 핸드폰에 홈 화면 아이콘으로 추가

배포 URL을 받았으면:

**iPhone (Safari)**:
1. URL 입력 후 페이지 로드
2. 하단 공유 버튼 (네모+화살표) 탭
3. **"홈 화면에 추가"**
4. 이름을 "🎀 아린이"로 지정

**Android (Chrome)**:
1. URL 입력 후 페이지 로드
2. 우측 상단 ⋮ 메뉴
3. **"홈 화면에 추가"** 또는 **"앱 설치"**

이제 핸드폰 홈 화면에서 아이콘 한 번 탭하면 PWA처럼 열립니다.

---

## 3️⃣ 매일의 흐름 — `daily_run.bat` 한 번 더블클릭

```
[daily_run.bat 실행]
    ├─ 0. 부모 Self_Port.xlsx → repo Self_Port.xlsx 동기화
    ├─ 1. 마스터 변경 자동 감지
    │     ├─ S&P500.xlsx / Index.xlsx 둘 다 옛날 → update_px_last.py (yfinance만, ~30초)
    │     └─ 둘 중 하나 새로 갱신됨   → sync_filtered_from_masters.py (~1분, 풀 빌드)
    ├─ 2. git add / commit / push  ← 자동
    │     └─ Streamlit Cloud가 push 감지 → 약 1~2분 후 새 데이터로 자동 재배포
    ├─ 3. 로컬 브라우저 (localhost:8501) 자동 오픈
    └─ 4. 로컬 Streamlit 시작 (Ctrl+C로 종료)
```

핸드폰에서는 push 후 1~2분 기다렸다가 새로고침하면 최신 데이터가 떠요.
앱 배포 페이지의 "Manage app" → "Logs"에서 빌드 진행상황을 볼 수 있어요.

---

## 4️⃣ 자주 묻는 질문

### Q1. Self_Port.xlsx 거래를 추가했는데 Cloud에 반영이 안 돼요
- 부모(`port/Self_Port.xlsx`) 또는 repo(`worktree/Self_Port.xlsx`) 중 어디를 편집하셨나요?
- `daily_run.bat`은 **부모 → repo** 방향으로 자동 복사하니, 부모 파일 편집 후 bat 실행이 표준 흐름이에요.
- bat을 실행하지 않고 repo 파일을 직접 편집했다면, 콘솔에서 `git add Self_Port.xlsx && git commit -m "tx" && git push` 수동 실행

### Q2. Cloud는 떴는데 데이터가 비어 보여요
- Cloud의 Logs에서 `FileNotFoundError` 검색해 보세요. 보통 `Self_Port.xlsx`이나 `data/S&P500_filtered.xlsx`이 없거나 LFS 인증 문제예요.
- LFS 파일이 안 받아지는 경우: Streamlit Cloud Settings → "Git LFS" 옵션이 켜져 있는지 확인 (기본 켜짐)

### Q3. 마스터 dump를 갱신하면 어떻게 되나요?
- `C:\...\pythonProject\S&P500.xlsx` 또는 `Index.xlsx`만 덮어쓰세요.
- 다음 `daily_run.bat` 실행 시 mtime 비교로 자동 감지 → 풀 sync → push.

### Q4. yfinance가 차단되거나 느려요
- 회사망에서 자주 막혀요. `daily_run.bat` 안에 `set "NO_PUSH=1"`을 임시로 넣고 yfinance 부분만 우회 가능.
- 또는 `_workspace\update_px_last.py`만 별도 실행해 retry.

### Q5. Streamlit Cloud의 무료 사용량 한도는?
- Public repo: 무제한. Private repo: 1개. 컴퓨팅 자원: ~1GB RAM, 자동 sleep (사용 안 하면 잠시 후 잠듦).
- 핸드폰에서 처음 접속하면 약 10초 wake-up 후 화면이 떠요.

### Q6. 보유 종목이 노출되는 게 싫어요
- repo를 **Private**으로 변경 (GitHub Settings → Danger zone → Change visibility)
- 그러면 Cloud에서도 GitHub OAuth로 인증된 본인만 볼 수 있어요
- 핸드폰에서도 처음 한 번은 Streamlit/GitHub 로그인 필요

---

## 5️⃣ 검증 체크리스트

- [ ] Streamlit Cloud에서 새 앱 생성 완료 (URL 발급됨)
- [ ] PC 브라우저에서 URL 접속 → 데이터 정상 표시
- [ ] 핸드폰에서 URL 접속 → 데이터 정상 표시
- [ ] 핸드폰에서 홈 화면 아이콘 추가
- [ ] `daily_run.bat` 한 번 실행 → 콘솔에 "pushed" 메시지 확인
- [ ] 1~2분 후 핸드폰 앱 새로고침 → 최신 시간 데이터로 갱신되는지 확인

---

## 부록 — 수동으로 push만 하고 싶을 때

```bat
cd C:\...\interesting-einstein-9b6bc8
git add Self_Port.xlsx data/S&P500_filtered.xlsx
git commit -m "data: manual refresh"
git push origin claude/interesting-einstein-9b6bc8
```

또는 `daily_run.bat`을 `set NO_PUSH=` (빈값) 으로만 두고 (= 푸시 활성화) 실행해도 됩니다.
