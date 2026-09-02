"""Ads account connect + simple boost."""

import logging
import secrets

from django.conf import settings
from django.core import signing
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from content.models import LibraryAsset
from projects import ads_oauth
from projects.media_policy import ADS_PROVIDERS, validate_ads_placements
from projects.models import AdAccount, AdBoostJob, Project
from projects.serializers import AdAccountSerializer, AdBoostJobSerializer
from projects.views import ProjectScopedSocialMixin

logger = logging.getLogger(__name__)

ADS_STATE_SALT = "ads-oauth-state"
ADS_STATE_MAX_AGE = 600


class ProjectAdAccountListView(ProjectScopedSocialMixin, APIView):
    def get(self, request: Request, project_id: str, *args, **kwargs) -> Response:
        project = self.get_project(request, project_id)
        accounts = project.ad_accounts.all()
        return Response(AdAccountSerializer(accounts, many=True).data)


class AdsConnectUrlView(ProjectScopedSocialMixin, APIView):
    def get(self, request: Request, project_id: str, provider: str, *args, **kwargs) -> Response:
        project = self.get_project(request, project_id)
        if provider not in ADS_PROVIDERS:
            return Response({"message": "Unsupported ads provider"}, status=status.HTTP_400_BAD_REQUEST)
        ads_provider = ads_oauth.ADS_PROVIDERS.get(provider)
        if ads_provider is None:
            return Response({"message": f"{provider} ads is not available yet."}, status=status.HTTP_501_NOT_IMPLEMENTED)
        state = signing.dumps(
            {
                "projectId": str(project.id),
                "provider": provider,
                "userId": str(request.user.id),
                "nonce": secrets.token_urlsafe(8),
            },
            salt=ADS_STATE_SALT,
        )
        return Response({"authUrl": ads_provider.build_auth_url(state), "state": state})


class AdsDisconnectView(ProjectScopedSocialMixin, APIView):
    def delete(self, request: Request, project_id: str, provider: str, *args, **kwargs) -> Response:
        project = self.get_project(request, project_id)
        account = get_object_or_404(AdAccount, project=project, provider=provider)
        account.connected = False
        account.save(update_fields=["connected", "updated_at"])
        return Response({"message": f"{provider} ads disconnected."})


class AdsCallbackView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def _redirect(self, provider: str, *, ok: bool) -> HttpResponseRedirect:
        base = settings.FRONTEND_URL.rstrip("/")
        flag = f"adsConnected={provider}" if ok else f"adsError={provider}"
        return HttpResponseRedirect(f"{base}/social?{flag}")

    def get(self, request: Request, provider: str, *args, **kwargs) -> HttpResponseRedirect:
        code = request.query_params.get("code", "")
        state = request.query_params.get("state", "")
        if request.query_params.get("error") or not code or not state:
            return self._redirect(provider, ok=False)
        try:
            payload = signing.loads(state, salt=ADS_STATE_SALT, max_age=ADS_STATE_MAX_AGE)
        except signing.BadSignature:
            return self._redirect(provider, ok=False)
        if payload.get("provider") != provider:
            return self._redirect(provider, ok=False)
        ads_provider = ads_oauth.ADS_PROVIDERS.get(provider)
        if ads_provider is None:
            return self._redirect(provider, ok=False)
        project = Project.objects.filter(id=payload.get("projectId"), owner_id=payload.get("userId")).first()
        if project is None:
            return self._redirect(provider, ok=False)
        try:
            tokens = ads_provider.exchange_code(code)
            profile = ads_provider.fetch_profile(tokens["access_token"])
        except Exception:  # noqa: BLE001
            logger.exception("Ads OAuth failed for %s", provider)
            return self._redirect(provider, ok=False)
        if not profile.get("externalId"):
            ids = tokens.get("advertiser_ids") or []
            if ids:
                profile["externalId"] = str(ids[0])
        account, _ = AdAccount.objects.get_or_create(project=project, provider=provider)
        account.connected = True
        account.external_id = profile.get("externalId") or account.external_id
        account.display_name = profile.get("displayName") or account.display_name
        account.handle = profile.get("handle") or account.handle
        account.store_tokens(
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            expires_in=tokens.get("expires_in"),
            scope=tokens.get("scope", ""),
        )
        account.save()
        return self._redirect(provider, ok=True)


class ProjectAdBoostView(ProjectScopedSocialMixin, APIView):
    """POST /api/projects/:id/ads/boost"""

    def post(self, request: Request, project_id: str, *args, **kwargs) -> Response:
        project = self.get_project(request, project_id)
        provider = (request.data.get("provider") or "").strip()
        kind = (request.data.get("kind") or "").strip()
        placements = request.data.get("placements") or []
        if isinstance(placements, str):
            placements = [p.strip() for p in placements.split(",") if p.strip()]
        title = (request.data.get("title") or "").strip()
        source_url = (request.data.get("sourceUrl") or "").strip()
        budget = str(request.data.get("budget") or "").strip()
        start_date = request.data.get("startDate") or None
        end_date = request.data.get("endDate") or None
        asset_id = request.data.get("assetId") or None

        asset = None
        if asset_id:
            asset = LibraryAsset.objects.filter(id=asset_id, project=project).first()
            if asset is None:
                return Response({"message": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)
            kind = kind or asset.media_type
            source_url = source_url or asset.source_url
            title = title or asset.title

        error = validate_ads_placements(kind, provider, placements)
        if error:
            return Response({"message": error}, status=status.HTTP_400_BAD_REQUEST)
        if not source_url:
            return Response({"message": "sourceUrl or assetId is required."}, status=status.HTTP_400_BAD_REQUEST)

        account = AdAccount.objects.filter(project=project, provider=provider, connected=True).first()
        if account is None:
            return Response(
                {"message": f"Connect {provider} ads first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if provider == "google":
            from projects.models import SocialAccount

            if not SocialAccount.objects.filter(
                project=project, platform="youtube", connected=True
            ).exists():
                return Response(
                    {"message": "Connect YouTube first. Google Ads runs on a video hosted on your channel."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        job = AdBoostJob.objects.create(
            project=project,
            user=request.user,
            ad_account=account,
            library_asset=asset,
            kind=kind,
            source_url=source_url,
            title=title,
            placements=placements,
            budget=budget,
            start_date=start_date or None,
            end_date=end_date or None,
            status="running",
        )
        try:
            result = ads_oauth.create_boost(
                account, kind=kind, source_url=source_url, title=title, placements=placements, budget=budget
            )
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = str(exc)
            job.save(update_fields=["status", "error", "updated_at"])
            return Response(AdBoostJobSerializer(job).data, status=status.HTTP_400_BAD_REQUEST)

        job.status = "succeeded"
        job.external_id = result.get("externalId") or ""
        job.save(update_fields=["status", "external_id", "updated_at"])
        return Response(AdBoostJobSerializer(job).data, status=status.HTTP_201_CREATED)
