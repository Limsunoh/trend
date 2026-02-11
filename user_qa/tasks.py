from celery import shared_task


@shared_task
def convert_collected_data_to_vector():
    """수집된 데이터를 벡터로 변환"""
    # TODO:
    # 1. NewsArticle, SocialMediaPost 조회
    # 2. 각 문서를 임베딩으로 변환
    # 3. 벡터DB에 저장
    # 4. VectorDocument 모델에 메타데이터 저장
    pass


@shared_task
def update_vector_document(document_id, document_type):
    """특정 문서를 벡터DB에 업데이트"""
    # TODO: 특정 문서만 벡터DB에 업데이트
    pass


@shared_task
def delete_vector_document(embedding_id):
    """벡터DB에서 문서 삭제"""
    # TODO: 벡터DB에서 문서 삭제
    pass
