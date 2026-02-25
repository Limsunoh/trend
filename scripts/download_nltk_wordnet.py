"""
NLTK를 import하지 않고 wordnet만 다운로드.
(import nltk 시 wordnet이 바로 로드되어 실패하는 경우용)
"""

import os
import sys
import urllib.request
import zipfile

# 현재 사용 중인 Python(venv)의 prefix에 nltk_data 생성
data_dir = os.path.join(sys.prefix, "nltk_data", "corpora")
os.makedirs(data_dir, exist_ok=True)

url = "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/wordnet.zip"
zip_path = os.path.join(data_dir, "wordnet.zip")

print("Downloading wordnet...")
urllib.request.urlretrieve(url, zip_path)

print("Extracting...")
with zipfile.ZipFile(zip_path, "r") as z:
    z.extractall(data_dir)

os.remove(zip_path)
print("Done. wordnet at:", os.path.join(data_dir, "wordnet"))
