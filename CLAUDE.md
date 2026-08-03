# CLAUDE.md

이 저장소는 **AUTOPILOT.md 프로토콜로 자율 빌드**된다. 어떤 작업이든 시작 전에 반드시 `AUTOPILOT.md`와 `STATE.md`를 읽어라. 진행 기록은 STATE.md에만 남긴다.

## 자주 쓰는 명령

```bash
ruff check .                                                  # 린트
pytest -q                                                     # 전체 테스트 (오프라인)
OO_SCAN_DATA_DIR=tests/fixtures python -m oo_scan run --offline   # 픽스처로 전체 파이프라인 실행
python -m oo_scan run --no-write                              # 라이브 스캔 (파일 미기록)
```

## 컨벤션

- 코드·식별자·커밋 접두어는 영어, 주석·docstring·리포트 문자열은 한국어
- ruff line-length 100, 공개 함수에는 타입힌트 필수
- 테스트는 네트워크 금지 (monkeypatch + `tests/fixtures/`만 사용)
- 새 의존성 추가 금지 (불가피하면 STATE.md 로그에 사유 기록)
- 커밋 제목: `<노드ID>: <한글 요약>` — 노드당 1커밋, STATE.md 갱신 동봉

**AUTOPILOT.md와 CLAUDE.md는 수정하지 않는다.**
