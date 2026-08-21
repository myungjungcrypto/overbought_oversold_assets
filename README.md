# overbought_oversold_assets — 광기·소외 온도계

크립토·주가지수(선진국+신흥국)·채권·부동산·금리·원자재·환율 **35개 크로스에셋**의
광기↔소외 온도를 매일 아침 07:30 KST에 측정해 한국어 리포트와 대시보드로 자동 발행하는,
**자산배분 관점의 모니터링 시스템**이다.

목적은 단타 신호가 아니다. 과열된 시장에서 물러나고 **소외된 자산에서 형성되는 기회를
남보다 먼저 인지**하기 위해, "무엇이 뜨겁고 무엇이 버려져 있는가"를 10분 안에 읽히는
형태로 매일 정리한다.

- 매일 리포트: [`reports/latest.md`](reports/latest.md) · 대시보드: [`docs/index.html`](docs/index.html) (Pages 활성화 시 웹 열람)
- 백테스트: [`reports/backtest.md`](reports/backtest.md) — "소외 진입 시 매수" 가설의 자산별 성과
- 설계 전문: [`AUTOPILOT.md`](AUTOPILOT.md) · 빌드 진행 기록: [`STATE.md`](STATE.md)

## 온도는 어떻게 측정하나 (지표)

온도는 **-100(깊은 소외) ~ +100(광기)** 스케일이고, 두 시야를 합성한다
(최종 = 0.4×단기 + 0.6×장기 — 자산배분 관점이라 장기 비중이 크다).

**단기 온도** — 지금 과열/침체 (일봉 0.6 + 주봉 0.4):
RSI(14) · Stochastic Slow · Bollinger %B · Williams %R · CCI · 20일 이격도 · MFI(볼륨 있는 자산만)

**장기 온도** — 구조적 광기/소외 (이 시스템의 핵심):
- 200일선 이격도의 **자기 역사 3년 대비 백분위** (자산군마다 변동성이 달라도 비교 가능)
- **52주 / 3년 가격 레인지 내 위치** (바닥권 0% ↔ 천장권 100%)
- **1년 수익률의 3년 대비 백분위** (장기 모멘텀이 역사적으로 얼마나 차가운가)
- 표시 전용: 3년 고점 대비 드로다운 %와 **소외 지속 기간**

| 최종 온도 | 등급 |
|---|---|
| ≥ +60 | 광기 |
| +30 ~ +60 | 과열 |
| −30 ~ +30 | 중립 |
| −60 ~ −30 | 소외 |
| ≤ −60 | 깊은 소외 |

정확한 공식은 `AUTOPILOT.md` 부록 A 참조. 상장 이력이 짧은 자산(HYPE 등)은 계산 가능한
지표만으로 재정규화하고, 60봉 미만이면 "데이터 부족"으로 표기한다.

## 자산 유니버스 (35종)

`config/assets.yaml` 한 파일이 전부다 — **항목을 추가/삭제하면 그대로 반영된다.**

| 자산군 | 구성 |
|---|---|
| 크립토 | BTC · ETH · SOL · BNB · HYPE (ccxt, 거래소 폴백 체인) |
| 주요 지수 | S&P500 · 나스닥 · 코스피 · 코스닥 · 닛케이225 · 항셍 · 필라델피아 반도체(SOX) · 러셀2000 · 유로스톡스50 |
| 신흥국 지수 ETF | EEM(신흥국 전체) · MCHI(중국) · INDA(인도) · EWZ(브라질) · VNM(베트남) · EWT(대만) |
| 채권 | TLT(미국 장기채) · HYG(하이일드) |
| 부동산 | VNQ(미국 리츠) |
| 금리 | 미국 10년물 · 30년물 |
| 원자재 | 금 · 은 · 구리 · WTI 원유 · 천연가스 · DBA(농산물) |
| 환율 | 달러인덱스 · 달러/엔 · 달러/원 |
| 변동성 | VIX |

전부 공개 데이터(ccxt 거래소 공개 API + yfinance)라 **API 키가 하나도 필요 없다.**

## 설치

```bash
git clone https://github.com/myungjungcrypto/overbought_oversold_assets.git
cd overbought_oversold_assets
pip install -r requirements.txt
```

Python 3.11+ 필요.

## 사용법

```bash
python -m oo_scan run                      # 전 자산 스캔 → 리포트·히스토리·대시보드 기록
python -m oo_scan run --no-write           # 파일 기록 없이 콘솔 표만
python -m oo_scan run --assets BTC,KOSPI   # 일부 자산만
python -m oo_scan run --offline            # 네트워크 없이 로컬 캐시/데이터만
python -m oo_scan fetch                    # 데이터만 받아 캐시에 저장
python -m oo_scan backtest --offline       # 소외 매수 가설 백테스트 리포트
```

- 캐시는 `data/cache/`(TTL 12시간), 데이터 디렉토리는 환경변수 `OO_SCAN_DATA_DIR`로 교체 가능.
- 리포트 구성(§10분 독서): ① 전체 온도계(랭킹·Δ전일) ② 소외 존(왜, 얼마나 오래) ③ 광기 존
  ④ 변화 감지(🔵 소외 탈출 = 기회 형성 / 🔴 과열 진입 = 경고) ⑤ 자산별 상세 부록.

### 매일 자동 발행 (하루 3회)

`.github/workflows/daily.yml` 크론이 **매일 3회(KST 07:30 / 12:00 / 18:30)** 스캔·백테스트를
돌리고 결과를 `[skip ci]` 커밋으로 저장소에 남긴다 — 각각 미국장 마감, 한국 오전장,
아시아 마감을 반영하는 시점이다. 같은 날짜의 실행은 리포트와 히스토리를 덮어쓰며,
Δ전일 컬럼은 항상 "어제 마지막 기록 대비"로 비교된다. 수동 실행은 Actions 탭의
workflow_dispatch. (Actions 크론은 최대 1시간가량 지연될 수 있다.)

## GitHub Pages 대시보드 활성화 (1회, 사람 작업)

1. 이 브랜치를 `main`에 머지한다 (일일 크론은 기본 브랜치에서만 동작).
2. GitHub 저장소 **Settings → Pages → Build and deployment**에서
   Source를 **Deploy from a branch**, Branch를 **main / `/docs`** 로 설정한다.
3. 몇 분 뒤 `https://myungjungcrypto.github.io/overbought_oversold_assets/` 에서 대시보드를 볼 수 있다.
4. Pages를 켜지 않아도 리포트는 항상 `reports/`·`docs/`에 커밋된다 (저장소에서 직접 열람 가능).
   Actions 푸시가 거부되면 **Settings → Actions → General → Workflow permissions**에서
   "Read and write permissions"를 허용한다.

## 백테스트 — "소외 매수"는 실제로 유리했나

`python -m oo_scan backtest`는 과거 전 구간의 온도 시계열을 재계산해서,
**소외/깊은 소외/과열 구간 진입일** 이후 21/63/126거래일 수익률을
같은 자산의 무조건부 평균(단순 보유)과 비교한다. 적중률(소외 진입 후 상승 비율,
과열 진입 후 하락 비율)과 표본 수를 함께 표기하며, 표본 5개 미만은 "표본 부족"으로
통계 주장을 하지 않는다. 결과: `reports/backtest.md` / `docs/backtest.html`.

## 부록: 텔레그램 알림 (선택)

기본 상태에서는 아무 것도 전송하지 않는다. 매일 리포트를 텔레그램으로도 받고 싶으면:

1. [@BotFather](https://t.me/BotFather)로 봇을 만들어 토큰을 받고, 봇과 대화를 시작한 뒤 chat_id를 확인한다.
2. 저장소 **Settings → Secrets and variables → Actions**에 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`를 등록한다.
3. `daily.yml`의 report 스텝 뒤에 다음을 추가한다:

```yaml
      - name: Telegram notify
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          python -c "from pathlib import Path; from oo_scan.telegram_stub import send_message; send_message(Path('reports/latest.md').read_text(encoding='utf-8')[:3500])"
```

토큰이 없으면 `send_message`는 조용히 no-op이므로 시스템은 텔레그램 없이 완전 동작한다.

## 개발

```bash
ruff check .                                                      # 린트
python -m pytest -q                                               # 전체 테스트 (오프라인, 네트워크 불필요)
OO_SCAN_DATA_DIR=tests/fixtures python -m oo_scan run --offline   # 픽스처로 전체 파이프라인
```

테스트는 전부 오프라인(합성 픽스처 + monkeypatch)이고, 라이브 네트워크는 daily 크론에서만 쓴다.
빌드 이력·노드 그래프·수리 기록은 `STATE.md`와 `AUTOPILOT.md`에 있다.

---

**면책**: 본 저장소의 리포트·점수·백테스트는 투자 자문이 아니며, 정보 제공 목적이다.
데이터 소스(거래소 공개 API·야후 파이낸스)의 오류·지연 가능성이 있고, 과거 성과는
미래 수익을 보장하지 않는다. 투자 판단과 책임은 전적으로 본인에게 있다.
