import redis

r = redis.Redis(host='121.148.185.46', port=6379)
print(r.ping())

