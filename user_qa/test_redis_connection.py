import redis

try:
    r = redis.Redis(host='localhost', port=6379, db=0)
    result = r.ping()
    print(f"✅ Redis 연결 성공! 응답: {result}")
except redis.ConnectionError:
    print("❌ Redis 서버에 연결할 수 없습니다.")
    print("Redis 서버가 실행 중인지 확인하세요.")
except Exception as e:
    print(f"❌ 오류 발생: {e}")