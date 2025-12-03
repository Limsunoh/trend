#!/usr/bin/env python
"""
PostgreSQL 연결 테스트 스크립트

이 스크립트를 실행하여 PostgreSQL 연결 정보를 확인할 수 있습니다.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트 디렉토리
BASE_DIR = Path(__file__).resolve().parent

# .env 파일 경로
env_path = BASE_DIR / '.env'

# .env 파일 존재 여부 확인
if env_path.exists():
    print(f"✓ .env 파일 발견: {env_path}")
    load_dotenv(env_path)
else:
    print(f"⚠ .env 파일을 찾을 수 없습니다: {env_path}")
    print("현재 디렉토리에서 .env 파일을 찾는 중...")
    load_dotenv()  # 기본 경로에서 시도

# 환경 변수에서 데이터베이스 정보 읽기
db_name = os.getenv('DB_NAME', 'trend_db')
db_user = os.getenv('DB_USER', 'postgres')
db_password = os.getenv('DB_PASSWORD', '')
db_host = os.getenv('DB_HOST', 'localhost')
db_port = os.getenv('DB_PORT', '5432')

print("=" * 50)
print("PostgreSQL 연결 정보 확인")
print("=" * 50)
print(f"DB_NAME: {db_name}")
print(f"DB_USER: {db_user}")
print(f"DB_HOST: {db_host}")
print(f"DB_PORT: {db_port}")
print(f"DB_PASSWORD: {'*' * len(db_password) if db_password else '(설정되지 않음)'}")

# 환경 변수 직접 확인
print("\n환경 변수 직접 확인:")
print(f"  os.getenv('DB_PASSWORD'): {os.getenv('DB_PASSWORD', '(없음)')}")
print("=" * 50)

# psycopg2로 연결 테스트
try:
    import psycopg2
    
    print("\n연결 테스트 중...")
    conn = psycopg2.connect(
        dbname=db_name,
        user=db_user,
        password=db_password,
        host=db_host,
        port=db_port
    )
    
    # 커서 생성
    cur = conn.cursor()
    
    # 현재 데이터베이스 확인
    cur.execute("SELECT current_database();")
    current_db = cur.fetchone()[0]
    print(f"✓ 연결 성공! 현재 데이터베이스: {current_db}")
    
    # PostgreSQL 버전 확인
    cur.execute("SELECT version();")
    version = cur.fetchone()[0]
    print(f"✓ PostgreSQL 버전: {version.split(',')[0]}")
    
    # 사용 가능한 데이터베이스 목록
    cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
    databases = [row[0] for row in cur.fetchall()]
    print(f"\n사용 가능한 데이터베이스 목록:")
    for db in databases:
        marker = " ← 현재" if db == current_db else ""
        print(f"  - {db}{marker}")
    
    # 사용자 목록
    cur.execute("SELECT usename FROM pg_user;")
    users = [row[0] for row in cur.fetchall()]
    print(f"\n사용 가능한 사용자 목록:")
    for user in users:
        marker = " ← 현재" if user == db_user else ""
        print(f"  - {user}{marker}")
    
    cur.close()
    conn.close()
    
    print("\n✓ 모든 테스트 통과!")
    print("\n.env 파일 설정이 올바릅니다.")
    
except ImportError:
    print("\n✗ psycopg2가 설치되지 않았습니다.")
    print("다음 명령어로 설치하세요: pip install psycopg2-binary")
    sys.exit(1)
    
except psycopg2.OperationalError as e:
    print(f"\n✗ 연결 실패: {str(e)}")
    print("\n가능한 원인:")
    print("1. PostgreSQL이 실행 중이 아닙니다.")
    print("2. .env 파일의 DB_PASSWORD가 잘못되었습니다.")
    print("3. 데이터베이스가 존재하지 않습니다.")
    print("\n해결 방법:")
    print("1. PostgreSQL 서비스가 실행 중인지 확인")
    print("2. pgAdmin에서 데이터베이스와 사용자 확인")
    print("3. 다음 SQL로 데이터베이스 생성:")
    print(f"   CREATE DATABASE {db_name};")
    sys.exit(1)
    
except Exception as e:
    print(f"\n✗ 오류 발생: {str(e)}")
    sys.exit(1)

