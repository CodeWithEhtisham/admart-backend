import logging
from typing import Any
from django.contrib.auth import get_user_model
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from users.serializers import (
    AuthResponseSerializer,
    CustomTokenObtainPairSerializer,
    ForgotPasswordSerializer,
    GoogleAuthSerializer,
    MessageSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()
signer = TimestampSigner()


class RegisterView(APIView):
    """View to handle user registration.

    On successful registration, creates a user with 5 free credits and returns JWT tokens.
    """

    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    @extend_schema(
        summary="Register a new user",
        request=RegisterSerializer,
        responses={
            201: AuthResponseSerializer,
        },
    )
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Handle user registration and generate tokens."""
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)

            return Response(
                {
                    "accessToken": str(refresh.access_token),
                    "refreshToken": str(refresh),
                    "user": UserSerializer(user).data,
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CustomTokenObtainPairView(TokenObtainPairView):
    """Custom Login View returning camelCase tokens and user profile."""

    serializer_class = CustomTokenObtainPairSerializer

    @extend_schema(
        summary="Login with email and password",
        responses={
            200: AuthResponseSerializer,
        },
    )
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().post(request, *args, **kwargs)


class MeView(generics.RetrieveUpdateAPIView):
    """View to retrieve or update the authenticated user's profile."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self) -> Any:
        return self.request.user

    @extend_schema(summary="Get current user details")
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Update current user details")
    def put(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().put(request, *args, **kwargs)

    @extend_schema(summary="Partially update current user details")
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().patch(request, *args, **kwargs)


class ForgotPasswordView(APIView):
    """View to initiate password reset."""

    permission_classes = [AllowAny]
    serializer_class = ForgotPasswordSerializer

    @extend_schema(
        summary="Forgot password request",
        request=ForgotPasswordSerializer,
        responses={
            200: MessageSerializer,
        },
    )
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Find user, generate secure signed token, and simulate email delivery."""
        serializer = ForgotPasswordSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data["email"]
            try:
                user = User.objects.get(email=email)
                # Generate signed token valid for 1 hour (3600 seconds)
                token = signer.sign(str(user.id))

                # Simulate sending email by printing details to the terminal/logs
                reset_link = f"http://localhost:5173/auth/reset-password?token={token}"
                logger.info(f"--- Password Reset Requested ---")
                logger.info(f"User: {user.email}")
                logger.info(f"Reset Link: {reset_link}")
                logger.info(f"--------------------------------")

            except User.DoesNotExist:
                # Silently succeed to prevent user enumeration
                pass

            return Response(
                {"message": "If the email is registered, a password reset link has been sent."},
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResetPasswordView(APIView):
    """View to reset password using signed token."""

    permission_classes = [AllowAny]
    serializer_class = ResetPasswordSerializer

    @extend_schema(
        summary="Reset password using token",
        request=ResetPasswordSerializer,
        responses={
            200: MessageSerializer,
            400: MessageSerializer,
        },
    )
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Unsign and verify the token, then set user's password."""
        serializer = ResetPasswordSerializer(data=request.data)
        if serializer.is_valid():
            token = serializer.validated_data["token"]
            new_password = serializer.validated_data["newPassword"]

            try:
                # Verify signature and expiration (max age = 1 hour)
                user_id = signer.unsign(token, max_age=3600)
                user = User.objects.get(id=user_id)
                user.set_password(new_password)
                user.save()

                return Response(
                    {"message": "Password has been reset successfully."},
                    status=status.HTTP_200_OK,
                )

            except (SignatureExpired, BadSignature, User.DoesNotExist):
                return Response(
                    {"non_field_errors": ["The reset link is invalid or has expired."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class GoogleAuthView(APIView):
    """View to exchange Google OAuth 2.0 auth code for user details and tokens."""

    permission_classes = [AllowAny]
    serializer_class = GoogleAuthSerializer

    @extend_schema(
        summary="Google OAuth Callback Exchange",
        request=GoogleAuthSerializer,
        responses={
            200: AuthResponseSerializer,
        },
    )
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Verify auth code and log in / register Google User."""
        serializer = GoogleAuthSerializer(data=request.data)
        if serializer.is_valid():
            # In a real environment, you would exchange the code with Google's API:
            #   requests.post("https://oauth2.googleapis.com/token", data={code, client_id, ...})
            # For demonstration/testing, we perform a mock validation/creation:
            code = serializer.validated_data["code"]
            email = f"google_user_{code[:6]}@example.com"

            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": "Google",
                    "last_name": "User",
                    "google_id": f"google-oauth-{code[:12]}",
                    "avatar_url": "https://lh3.googleusercontent.com/a/default-avatar",
                    "plan": "free",
                    "credits_total": 5,
                    "credits_remaining": 5,
                },
            )

            refresh = RefreshToken.for_user(user)

            return Response(
                {
                    "accessToken": str(refresh.access_token),
                    "refreshToken": str(refresh),
                    "user": UserSerializer(user).data,
                },
                status=status.HTTP_200_OK,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LogoutView(APIView):
    """View to handle user logout by invalidating token."""

    permission_classes = [AllowAny]

    @extend_schema(
        summary="Logout User",
        request=None,
        responses={
            200: MessageSerializer,
        },
    )
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Handle logout (accepts optional refresh token for simplejwt blacklisting)."""
        # If client passes refreshToken in body, try to blacklist it:
        refresh_token = request.data.get("refreshToken")
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception:
                # Fail gracefully if blacklist is not enabled/supported
                pass

        return Response({"message": "Logged out successfully."}, status=status.HTTP_200_OK)

