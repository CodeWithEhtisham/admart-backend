from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from admin_panel.services import expire_subscription_if_due


class AdmartJWTAuthentication(JWTAuthentication):
    """SimpleJWT bearer auth that also expires lapsed paid plans on each request.

    Invalid or expired tokens are treated as anonymous (not a hard 401) so
    AllowAny endpoints such as login keep working with a stale stored token.
    """

    def authenticate(self, request):
        try:
            result = super().authenticate(request)
        except AuthenticationFailed:
            return None
        if result is None:
            return None
        user, token = result
        return (expire_subscription_if_due(user), token)
