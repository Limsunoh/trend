# CloudWatch 에이전트 로그 수집 (Docker / Gunicorn)

## 1. EC2에서 로그 위치 확인하는 명령어

### 현재 Docker 컨테이너 로그 (기본 json-file 드라이버)
```bash
# 컨테이너 ID 확인
docker ps --format '{{.ID}} {{.Names}}'

# 해당 컨테이너 로그 파일 경로 (호스트 기준)
# 형식: /var/lib/docker/containers/<컨테이너ID>/<컨테이너ID>-json.log
CONTAINER_ID=$(docker ps -q -f name=trend-web); echo "/var/lib/docker/containers/$CONTAINER_ID/${CONTAINER_ID}-json.log"

# 실제 로그 한 줄 보기
CONTAINER_ID=$(docker ps -q -f name=trend-web); sudo tail -n 1 /var/lib/docker/containers/$CONTAINER_ID/${CONTAINER_ID}-json.log
```
- **한계**: 컨테이너를 다시 만들면 ID가 바뀌어 경로가 달라지고, 내용이 JSON 한 줄 단위라 CloudWatch에서 보기 불편함.
- **권장**: 아래처럼 Gunicorn이 **파일**로 쓰게 하고, 그 파일을 수집하는 방식 사용.

### 우리가 쓰는 경로 (Gunicorn 파일 로그)
- 프로젝트 루트: `~/trend` (예: `/home/ubuntu/trend`)
- 로그 디렉터리: `~/trend/logs/`
- 파일:
  - `~/trend/logs/access.log` — Gunicorn 액세스 로그
  - `~/trend/logs/error.log` — Gunicorn 에러 로그

**EC2에서 확인:**
```bash
cd ~/trend
docker compose up -d
sleep 5
ls -la logs/
cat logs/access.log
tail -5 logs/error.log
```

---

## 2. 적용 순서

1. **docker-compose.yml**  
   - 이미 수정됨: `./logs:/app/logs` 볼륨 + Gunicorn `--access-logfile /app/logs/access.log --error-logfile /app/logs/error.log`

2. **EC2에서**  
   - 프로젝트 경로가 `/home/ubuntu/trend`가 아니면 아래 `값`의 `file_path`를 실제 경로에 맞게 수정.

3. **Parameter Store**  
   - 파라미터 `Trend-CloudWatch-Conf` 값에 아래 JSON 전체를 넣기.

---

## 3. Parameter Store 값 (전체 — 메트릭 + 로그, 4096자 이내)

EC2 프로젝트 경로가 **`/home/ubuntu/trend`** 일 때 사용. 다른 경로면 `file_path`만 수정.

```json
{
  "agent": {
    "metrics_collection_interval": 60,
    "run_as_user": "root"
  },
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/home/ubuntu/trend/logs/access.log",
            "log_group_name": "trend/web-access",
            "log_stream_name": "{instance_id}"
          },
          {
            "file_path": "/home/ubuntu/trend/logs/error.log",
            "log_group_name": "trend/web-error",
            "log_stream_name": "{instance_id}"
          }
        ]
      }
    }
  },
  "metrics": {
    "namespace": "CWAgent",
    "append_dimensions": {
      "InstanceId": "${aws:InstanceId}",
      "InstanceType": "${aws:InstanceType}",
      "ImageId": "${aws:ImageId}",
      "AutoScalingGroupName": "${aws:AutoScalingGroupName}"
    },
    "metrics_collected": {
      "cpu": {
        "measurement": ["cpu_usage_idle", "cpu_usage_user", "cpu_usage_system"],
        "metrics_collection_interval": 60,
        "totalcpu": false
      },
      "mem": {
        "measurement": ["mem_used_percent"],
        "metrics_collection_interval": 60
      },
      "disk": {
        "measurement": ["used_percent"],
        "metrics_collection_interval": 60,
        "resources": ["/"]
      },
      "net": {
        "measurement": ["bytes_sent", "bytes_recv", "packets_sent", "packets_recv"],
        "metrics_collection_interval": 60
      }
    }
  }
}
```

---

## 4. 프로젝트 경로가 다를 때

EC2에서 `pwd`로 프로젝트 경로 확인 후, `file_path`만 바꾸면 됨.

| 실제 경로 예시              | access.log file_path                          |
|----------------------------|-----------------------------------------------|
| `/home/ubuntu/trend`       | `/home/ubuntu/trend/logs/access.log`          |
| `/var/app/trend`           | `/var/app/trend/logs/access.log`             |

error.log도 같은 디렉터리만 맞추면 됨.
