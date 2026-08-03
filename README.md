# overbought_oversold_assets — 광기·소외 온도계

크립토·주가지수(선진국+신흥국)·금리·원자재·환율 **28개 크로스에셋**의 광기↔소외 온도를
매일 아침 측정해 한국어 리포트로 발행하는, 자산배분 관점의 모니터링 시스템.

> 자율 빌드 진행 중 — 상세 사용법은 빌드 완료 시 채워진다. 설계 전문은 `AUTOPILOT.md`, 진행 상태는 `STATE.md` 참조.

## GitHub Pages 대시보드 활성화 (1회, 사람 작업)

1. 이 브랜치를 `main`에 머지한다 (일일 크론은 기본 브랜치에서만 동작).
2. GitHub 저장소 **Settings → Pages → Build and deployment**에서
   Source를 **Deploy from a branch**, Branch를 **main / `/docs`** 로 설정한다.
3. 몇 분 뒤 `https://<계정>.github.io/overbought_oversold_assets/` 에서 온도계 대시보드를 볼 수 있다.
4. Pages를 켜지 않아도 리포트는 항상 `reports/`·`docs/`에 커밋된다 (저장소에서 직접 열람 가능).
   Actions 푸시가 거부되면 **Settings → Actions → General → Workflow permissions**에서
   "Read and write permissions"를 허용한다.
