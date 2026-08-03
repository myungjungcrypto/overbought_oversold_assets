# STATE — overbought_oversold_assets 자동 빌드 진행 상태

이 파일은 AUTOPILOT.md 프로토콜의 유일한 진행 기록이다. 편집 규칙(AUTOPILOT §4.4) 외의 방식으로 수정 금지.

## 메타
- 마지막 갱신: 2026-08-03 16:07 KST
- 현재 마일스톤: M1·M2 (병렬 구간 1)
- 다음 액션: 빌더 A(D-레인)·빌더 B(I/L/S-레인) 병렬 투입

## 노드 상태
| ID | 작업 | 상태 | 시도 | 커밋 | 비고 |
|----|------|------|------|------|------|
| B1 | 리포 스캐폴드 | DONE | 1 | 223370a | debian cryptography 충돌 → --ignore-installed로 해소 |
| B2 | 패키지+CLI 뼈대 | DONE | 0 | 1c7b56d | |
| B3 | 자산 config (28종) | DONE | 1 | 6bf6c8d | uv tool pytest에 의존성 없음 → python -m pytest로 통일 |
| B4 | CI workflow | DONE | 0 | - | |
| D1 | CSV 캐시 | DONE | 0 | - | |
| D2 | yfinance 페처 (4y) | DONE | 0 | - | |
| D3 | ccxt 페처 (페이지네이션) | DONE | 0 | - | |
| D4 | 테스트 픽스처 | DONE | 0 | - | |
| I1 | RSI | DONE | 0 | - | 단일 파일 레인 → I1-I5 묶음 커밋 |
| I2 | Stoch+W%R | DONE | 0 | - | 단일 파일 레인 → I1-I5 묶음 커밋 |
| I3 | %B+CCI+이격도20 | DONE | 0 | - | 단일 파일 레인 → I1-I5 묶음 커밋 |
| I4 | MFI | DONE | 0 | - | 단일 파일 레인 → I1-I5 묶음 커밋 |
| I5 | 주봉 리샘플 | DONE | 0 | - | 단일 파일 레인 → I1-I5 묶음 커밋 |
| I6 | 단기 온도 | DONE | 0 | - | score.py에 S1과 동거 → 묶음 커밋 |
| L1 | 이격도200 백분위+레인지 위치 | DONE | 0 | - | 단일 파일 레인 → L1-L3 묶음 커밋 |
| L2 | 1년 수익률 백분위+드로다운 | DONE | 0 | - | 단일 파일 레인 → L1-L3 묶음 커밋 |
| L3 | 장기 온도 | DONE | 0 | - | 단일 파일 레인 → L1-L3 묶음 커밋 |
| S1 | 최종 온도·5등급 | DONE | 0 | - | score.py에 I6과 동거 → 묶음 커밋 |
| P1 | 파이프라인+CLI | PENDING | 0 | - | |
| P2 | 라이브 스모크 (soft) | PENDING | 0 | - | |
| H1 | 히스토리+변화 감지 | PENDING | 0 | - | |
| R1 | 마크다운 리포트 (5섹션) | PENDING | 0 | - | |
| R2 | HTML 대시보드 | PENDING | 0 | - | |
| R3 | run 통합 | PENDING | 0 | - | |
| A1 | daily cron workflow | PENDING | 0 | - | |
| A2 | Pages 준비 | PENDING | 0 | - | |
| A3 | push+CI 확인 (soft) | PENDING | 0 | - | |
| K1 | 백테스트 코어 | PENDING | 0 | - | |
| K2 | 백테스트 리포트 | PENDING | 0 | - | |
| F1 | 텔레그램 스텁 | DONE | 0 | - | |
| F2 | README 완성 | PENDING | 0 | - | |
| F3 | 최종 자가 검수 | PENDING | 0 | - | |

## 인간 개입 대기 목록
(없음)

## 로그 (최신이 위, 최대 100줄 유지)
- 2026-08-03 16:39 KST [F1] DONE — 텔레그램 스텁(env 없으면 no-op), 테스트 3개
- 2026-08-03 16:39 KST [I6+S1] DONE — 서브점수 정규화·단기/최종 온도·5등급, 테스트 14개 (빌더 B). 검증자 V 공식 대조 PASS
- 2026-08-03 16:39 KST [L1-L3] DONE — 장기 온도(이격도200 백분위·레인지·1년수익률 백분위·드로다운), 테스트 18개 (빌더 B)
- 2026-08-03 16:39 KST [I1-I5] DONE — 오실레이터 7종+주봉 리샘플, 테스트 25개 (빌더 B). 파일 구조상 묶음 커밋
- 2026-08-03 16:39 KST [D4] DONE — 결정적 합성 픽스처 6종(HYPE 220봉 포함), 테스트 20개 (빌더 A)
- 2026-08-03 16:39 KST [D3] DONE — ccxt 폴백 체인+1000봉 페이지네이션, 테스트 7개 (빌더 A)
- 2026-08-03 16:39 KST [D2] DONE — yfinance 페처(4y, 백오프, kwargs 방어), 테스트 7개 (빌더 A)
- 2026-08-03 16:39 KST [D1] DONE — CSV 캐시(TTL·OO_SCAN_DATA_DIR), 테스트 7개 (빌더 A)
- 2026-08-03 16:07 KST [B4] DONE — ci.yml (ruff+pytest, 오프라인). M0 부트스트랩 수락 기준 전부 통과
- 2026-08-03 16:05 KST [B3] DONE — assets.yaml 28종+config 로더+테스트 7개. pytest는 python -m pytest로 실행해야 함(uv tool 격리 환경 이슈)
- 2026-08-03 16:00 KST [B2] DONE — oo_scan 패키지, argparse CLI(run/fetch/backtest 스텁), 테스트 3개 통과
- 2026-08-03 15:57 KST [B1] DONE — 스캐폴드 4파일, pip 설치(cryptography 충돌 1회 수리), ruff 통과. pandas 3.0.5/yfinance 1.5.2 확인

