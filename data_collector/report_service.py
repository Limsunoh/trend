"""
수집 세션 리포트 생성 서비스

CollectionSession 데이터를 기반으로 JSON 및 마크다운 리포트를 생성합니다.
"""
import json
import os
import logging
from datetime import datetime
from typing import Dict, Optional
from django.conf import settings
from django.utils import timezone
from .models import CollectionSession, DataCollectionJob

logger = logging.getLogger(__name__)


class CollectionReportService:
    """수집 세션 리포트 생성 서비스"""
    
    def __init__(self):
        """리포트 디렉토리 초기화"""
        self.reports_dir = os.path.join(settings.BASE_DIR, 'reports')
        os.makedirs(self.reports_dir, exist_ok=True)
        self.json_dir = os.path.join(self.reports_dir, 'json')
        self.markdown_dir = os.path.join(self.reports_dir, 'markdown')
        os.makedirs(self.json_dir, exist_ok=True)
        os.makedirs(self.markdown_dir, exist_ok=True)
    
    def generate_json_report(self, session: CollectionSession) -> str:
        """
        JSON 리포트 생성
        
        Args:
            session: CollectionSession 인스턴스
            
        Returns:
            생성된 JSON 파일 경로
        """
        try:
            # 세션 기본 정보
            report_data = session.get_summary()
            
            # DataCollectionJob 상세 정보 추가
            jobs = DataCollectionJob.objects.filter(
                started_at__gte=session.started_at
            ).order_by('-started_at')
            
            jobs_data = []
            for job in jobs:
                jobs_data.append({
                    'source': str(job.source) if job.source else None,
                    'status': job.status,
                    'started_at': job.started_at.isoformat() if job.started_at else None,
                    'completed_at': job.completed_at.isoformat() if job.completed_at else None,
                    'items_collected': job.items_collected,
                    'error_message': job.error_message,
                })
            
            report_data['jobs'] = jobs_data
            report_data['jobs_count'] = len(jobs_data)
            
            # 파일명: session_{id}_{timestamp}.json
            timestamp = session.started_at.strftime('%Y%m%d_%H%M%S')
            filename = f'session_{session.id}_{timestamp}.json'
            filepath = os.path.join(self.json_dir, filename)
            
            # JSON 파일 저장
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"JSON 리포트 생성 완료: {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"JSON 리포트 생성 실패: {str(e)}", exc_info=True)
            raise
    
    def generate_markdown_report(self, session: CollectionSession) -> str:
        """
        마크다운 리포트 생성
        
        Args:
            session: CollectionSession 인스턴스
            
        Returns:
            생성된 마크다운 파일 경로
        """
        try:
            # 파일명: session_{id}_{timestamp}.md
            timestamp = session.started_at.strftime('%Y%m%d_%H%M%S')
            filename = f'session_{session.id}_{timestamp}.md'
            filepath = os.path.join(self.markdown_dir, filename)
            
            # 마크다운 내용 생성
            md_content = self._create_markdown_content(session)
            
            # 파일 저장
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(md_content)
            
            logger.info(f"마크다운 리포트 생성 완료: {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"마크다운 리포트 생성 실패: {str(e)}", exc_info=True)
            raise
    
    def _create_markdown_content(self, session: CollectionSession) -> str:
        """마크다운 리포트 내용 생성"""
        lines = []
        
        # 헤더
        lines.append(f"# 수집 세션 리포트 #{session.id}")
        lines.append("")
        
        # 기본 정보
        lines.append("## 기본 정보")
        lines.append("")
        lines.append(f"- **세션 ID**: {session.id}")
        lines.append(f"- **시작 시간**: {session.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
        if session.completed_at:
            lines.append(f"- **종료 시간**: {session.completed_at.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"- **상태**: {session.get_status_display()}")
        if session.duration_seconds:
            duration_min = session.duration_seconds / 60
            lines.append(f"- **소요 시간**: {session.duration_seconds:.1f}초 ({duration_min:.1f}분)")
        lines.append("")
        
        # 소스 통계
        lines.append("## 소스 통계")
        lines.append("")
        lines.append(f"- **전체 소스 수**: {session.total_sources}개")
        lines.append(f"- **성공한 소스**: {session.successful_sources}개")
        lines.append(f"- **실패한 소스**: {session.failed_sources}개")
        if session.total_sources > 0:
            success_rate = (session.successful_sources / session.total_sources) * 100
            lines.append(f"- **성공률**: {success_rate:.1f}%")
        lines.append("")
        
        # 기사 통계
        lines.append("## 기사 통계")
        lines.append("")
        lines.append(f"- **수집된 기사**: {session.total_articles_collected}개")
        lines.append(f"- **건너뛴 기사**: {session.total_articles_skipped}개")
        lines.append(f"- **오류 발생 기사**: {session.total_articles_error}개")
        total_processed = (
            session.total_articles_collected + 
            session.total_articles_skipped + 
            session.total_articles_error
        )
        if total_processed > 0:
            lines.append(f"- **처리된 기사 총합**: {total_processed}개")
        lines.append("")
        
        # 작업 상세 정보
        jobs = DataCollectionJob.objects.filter(
            started_at__gte=session.started_at
        ).order_by('-started_at')
        
        if jobs.exists():
            lines.append("## 작업 상세")
            lines.append("")
            lines.append("| 소스 | 상태 | 수집 개수 | 시작 시간 | 완료 시간 |")
            lines.append("|------|------|----------|----------|----------|")
            
            for job in jobs:
                source_name = str(job.source) if job.source else 'Unknown'
                status = job.get_status_display()
                items = job.items_collected
                started = job.started_at.strftime('%Y-%m-%d %H:%M:%S') if job.started_at else '-'
                completed = job.completed_at.strftime('%Y-%m-%d %H:%M:%S') if job.completed_at else '-'
                lines.append(f"| {source_name} | {status} | {items} | {started} | {completed} |")
            
            lines.append("")
        
        # 실패한 작업
        failed_jobs = jobs.filter(status='failed')
        if failed_jobs.exists():
            lines.append("## 실패한 작업")
            lines.append("")
            for job in failed_jobs:
                source_name = str(job.source) if job.source else 'Unknown'
                lines.append(f"### {source_name}")
                if job.error_message:
                    lines.append(f"**오류**: {job.error_message}")
                lines.append("")
        
        # 리포트 생성 시간
        lines.append("---")
        lines.append(f"*리포트 생성 시간: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        
        return "\n".join(lines)
    
    def generate_all_reports(self, session: CollectionSession) -> Dict[str, str]:
        """
        JSON 및 마크다운 리포트 모두 생성
        
        Args:
            session: CollectionSession 인스턴스
            
        Returns:
            {'json_path': ..., 'markdown_path': ...}
        """
        json_path = self.generate_json_report(session)
        markdown_path = self.generate_markdown_report(session)
        
        return {
            'json_path': json_path,
            'markdown_path': markdown_path
        }
