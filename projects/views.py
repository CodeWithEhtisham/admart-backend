from typing import Any

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from projects.models import Project, SocialAccount
from projects.serializers import ProjectSerializer, SocialAccountSerializer

VALID_PLATFORMS = [choice[0] for choice in SocialAccount.PLATFORM_CHOICES]


def resolve_active_project_id(user) -> str | None:
    """Return the user's active project id.

    Prefers the explicit ``active_project`` pointer when it still exists and is
    owned by the user, otherwise falls back to the most-recently-accessed project.
    """
    if user.active_project_id:
        # active_project uses SET_NULL, so a stale pointer is already cleared, but
        # guard against ownership drift just in case.
        if Project.objects.filter(id=user.active_project_id, owner=user).exists():
            return str(user.active_project_id)

    most_recent = Project.objects.filter(owner=user).first()
    return str(most_recent.id) if most_recent else None


class OwnedProjectMixin:
    """Restrict querysets to projects owned by the authenticated user."""

    permission_classes = [IsAuthenticated]
    serializer_class = ProjectSerializer

    def get_queryset(self):
        return Project.objects.filter(owner=self.request.user)


class ProjectListCreateView(OwnedProjectMixin, generics.ListCreateAPIView):
    """List the user's projects or create a new one.

    The list is ordered by recency so ``projects[0]`` is the auto-detected active
    project when no explicit selection exists.
    """

    @extend_schema(
        summary="List the current user's projects",
        responses={200: ProjectSerializer(many=True)},
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return the user's projects plus the resolved active project id."""
        projects = self.get_queryset()
        return Response(
            {
                "projects": ProjectSerializer(projects, many=True).data,
                "activeProjectId": resolve_active_project_id(request.user),
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(summary="Create a project", responses={201: ProjectSerializer})
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create a project owned by the user and immediately make it active."""
        serializer = ProjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = serializer.save(owner=request.user)
        project.touch()

        request.user.active_project = project
        request.user.save(update_fields=["active_project", "updated_at"])

        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)


class ProjectDetailView(OwnedProjectMixin, generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, partially update, or delete a single owned project."""

    lookup_field = "id"

    @extend_schema(summary="Get a project")
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Update a project")
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @extend_schema(summary="Delete a project", responses={204: None})
    def delete(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().delete(request, *args, **kwargs)

    def put(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)


class ProjectActivateView(APIView):
    """Mark a project as the active / most-recently-accessed one."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Activate a project",
        request=None,
        responses={200: OpenApiResponse(description='{ "activeProjectId": "<id>" }')},
    )
    def post(self, request: Request, id: str, *args: Any, **kwargs: Any) -> Response:
        """Set the project's last_accessed_at and the user's active pointer."""
        project = get_object_or_404(Project, id=id, owner=request.user)
        project.touch()

        request.user.active_project = project
        request.user.save(update_fields=["active_project", "updated_at"])

        return Response({"activeProjectId": str(project.id)}, status=status.HTTP_200_OK)


class ProjectScopedSocialMixin:
    """Resolve and authorize the parent project for social-account endpoints."""

    permission_classes = [IsAuthenticated]
    serializer_class = SocialAccountSerializer

    def get_project(self, request: Request, project_id: str) -> Project:
        return get_object_or_404(Project, id=project_id, owner=request.user)


class ProjectSocialListView(ProjectScopedSocialMixin, APIView):
    """List social accounts connected within a project."""

    @extend_schema(summary="List a project's connected social accounts")
    def get(self, request: Request, project_id: str, *args: Any, **kwargs: Any) -> Response:
        project = self.get_project(request, project_id)
        accounts = project.social_accounts.all()
        return Response(SocialAccountSerializer(accounts, many=True).data, status=status.HTTP_200_OK)


class ProjectSocialConnectView(ProjectScopedSocialMixin, APIView):
    """Mock-connect a social platform within a project.

    In production this initiates an OAuth flow; for dev it creates/re-activates a
    SocialAccount immediately.
    """

    @extend_schema(
        summary="Connect a social platform to a project",
        request=None,
        responses={200: SocialAccountSerializer, 201: SocialAccountSerializer},
    )
    def post(self, request: Request, project_id: str, platform: str, *args: Any, **kwargs: Any) -> Response:
        project = self.get_project(request, project_id)
        if platform not in VALID_PLATFORMS:
            return Response(
                {"detail": f"Invalid platform. Choose from: {', '.join(VALID_PLATFORMS)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        account, created = SocialAccount.objects.get_or_create(
            project=project,
            platform=platform,
            defaults={
                "connected": True,
                "handle": f"@{(user.first_name or 'user').lower()}_{platform}",
                "display_name": f"{user.first_name} {user.last_name}".strip() or user.email,
            },
        )
        if not created and not account.connected:
            account.connected = True
            account.save(update_fields=["connected"])

        return Response(
            SocialAccountSerializer(account).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ProjectSocialDisconnectView(ProjectScopedSocialMixin, APIView):
    """Soft-disconnect a social platform within a project."""

    @extend_schema(summary="Disconnect a social platform from a project", responses={200: None})
    def delete(self, request: Request, project_id: str, platform: str, *args: Any, **kwargs: Any) -> Response:
        project = self.get_project(request, project_id)
        try:
            account = SocialAccount.objects.get(project=project, platform=platform)
        except SocialAccount.DoesNotExist:
            return Response(
                {"detail": f"No {platform} account connected."},
                status=status.HTTP_404_NOT_FOUND,
            )
        account.connected = False
        account.save(update_fields=["connected"])
        return Response({"message": f"{platform} disconnected successfully."}, status=status.HTTP_200_OK)
