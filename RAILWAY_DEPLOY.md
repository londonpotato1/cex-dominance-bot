# Railway 배포 가이드

## 배포 방식
**단일 서비스**: Streamlit (web) + collector_daemon (백그라운드 스레드)

## 필수 환경변수

### Railway Dashboard에서 설정:
```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 자동 설정 (Railway가 제공):
- `PORT` - Streamlit 포트
- `RAILWAY_ENVIRONMENT` - Railway 환경 감지 (데몬 자동 시작 트리거)

## 선택 환경변수

### Volume 사용 시 (권장):
```
DATABASE_URL=/data/ddari.db
HEALTH_PATH=/data/health.json
```

### Volume 미사용 시:
기본 경로 사용 (프로젝트 루트)
- DB: `./ddari.db`
- Health: `./health.json`

> **주의**: Volume 없이 배포하면 재배포 시 데이터 초기화됨

## Volume 설정 (선택)

1. Railway Dashboard → Service → Settings → Volumes
2. Mount Path: `/data`
3. 환경변수 추가:
   - `DATABASE_URL=/data/ddari.db`
   - `HEALTH_PATH=/data/health.json`

## Procfile
```
web: streamlit run app.py --server.port=$PORT --server.address=0.0.0.0
```

## 배포 순서

1. GitHub 연결 (또는 `railway up`)
2. 환경변수 설정
3. (선택) Volume 생성 및 마운트
4. Deploy

## 로컬 테스트

```bash
# 데몬 포함 실행
DAEMON_ENABLED=true streamlit run app.py

# 데몬 없이 실행 (기본)
streamlit run app.py
```

## 확인 사항

- [ ] Telegram 봇 토큰/Chat ID 설정
- [ ] Volume 마운트 (데이터 영속화 필요 시)
- [ ] 배포 후 `/status` 명령어로 봇 동작 확인
