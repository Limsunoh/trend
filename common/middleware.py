"""
공통 미들웨어 (보안 헤더 등)
"""


class SecurityHeadersMiddleware:
    """
    Referrer-Policy 등 Django 기본에 없는 보안 헤더 추가.
    X-Content-Type-Options, X-Frame-Options, X-XSS-Protection은 settings로 적용됨.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response
