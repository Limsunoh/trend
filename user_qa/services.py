"""
벡터DB 및 RAG 서비스
"""


class VectorDBService:
    """벡터DB 관리 서비스"""
    
    def __init__(self):
        # TODO: 벡터DB 초기화 (Chroma, Pinecone 등)
        pass
    
    def add_document(self, content, metadata=None):
        """문서를 벡터DB에 추가"""
        # TODO: 문서 임베딩 생성 및 벡터DB 저장
        pass
    
    def search(self, query, top_k=5):
        """유사 문서 검색"""
        # TODO: 쿼리 임베딩 생성 및 유사 문서 검색
        pass
    
    def delete_document(self, embedding_id):
        """벡터DB에서 문서 삭제"""
        # TODO: 벡터DB에서 문서 삭제
        pass


class RAGService:
    """RAG 질의응답 서비스"""
    
    def __init__(self):
        # TODO: LLM 및 VectorDBService 초기화
        self.vector_db = VectorDBService()
        pass
    
    def query(self, query_text, top_k=5, include_sources=True):
        """RAG 질의응답"""
        # TODO: 
        # 1. 벡터DB에서 유사 문서 검색
        # 2. 검색된 문서를 컨텍스트로 LLM에 전달
        # 3. LLM 답변 생성
        # 4. 결과 반환
        pass

