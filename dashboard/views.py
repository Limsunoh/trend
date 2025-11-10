from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(['GET'])
def dashboard_overview(request):
    """대시보드 전체 개요"""
    # TODO: 대시보드 개요 데이터 반환
    return Response({'message': 'Not implemented yet'})


@api_view(['GET'])
def trending_keywords(request):
    """인기 키워드 목록"""
    # TODO: 인기 키워드 목록 반환
    return Response({'message': 'Not implemented yet'})


@api_view(['GET'])
def trending_topics(request):
    """인기 토픽 목록"""
    # TODO: 인기 토픽 목록 반환
    return Response({'message': 'Not implemented yet'})


@api_view(['GET'])
def realtime_stats(request):
    """실시간 통계"""
    # TODO: 실시간 통계 데이터 반환
    return Response({'message': 'Not implemented yet'})


@api_view(['GET'])
def keyword_detail(request, keyword_id):
    """키워드 상세 정보"""
    # TODO: 키워드 상세 정보 반환
    return Response({'message': 'Not implemented yet'})


@api_view(['GET'])
def topic_detail(request, topic_id):
    """토픽 상세 정보"""
    # TODO: 토픽 상세 정보 반환
    return Response({'message': 'Not implemented yet'})
