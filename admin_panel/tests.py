from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from django.test import override_settings
from rest_framework.test import APITestCase

from admin_panel.models import CreditAdjustment, Payment, Subscription
from content.models import ImageJob
from projects.models import Project

User = get_user_model()


class AdminAuthTests(APITestCase):
    """Non-staff and anonymous users must be blocked from admin endpoints."""

    def setUp(self) -> None:
        self.customer = User.objects.create_user(
            email="customer@example.com", password="Password123!"
        )
        self.staff = User.objects.create_user(
            email="staff@example.com", password="Password123!", is_staff=True
        )
        self.superuser = User.objects.create_user(
            email="owner@example.com", password="Password123!", is_superuser=True, is_staff=True
        )
        self.stats_url = reverse("admin_stats")
        self.users_url = reverse("admin_users")

    def test_anonymous_blocked(self) -> None:
        response = self.client.get(self.stats_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_blocked(self) -> None:
        self.client.force_authenticate(user=self.customer)
        response = self.client.get(self.stats_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_read_stats(self) -> None:
        self.client.force_authenticate(user=self.staff)
        response = self.client.get(self.stats_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("totals", response.data)
        self.assertIn("charts", response.data)

    def test_staff_cannot_change_plan(self) -> None:
        self.client.force_authenticate(user=self.staff)
        response = self.client.post(
            reverse("admin_user_plan", args=[self.customer.id]),
            {"plan": "pro"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AdminUserTests(APITestCase):
    """Customer listing, detail, plan change, credits, support fields."""

    def setUp(self) -> None:
        self.customer = User.objects.create_user(
            email="customer@example.com", password="Password123!", first_name="Ada"
        )
        self.project = Project.objects.create(owner=self.customer, name="Brand A")
        self.superuser = User.objects.create_user(
            email="owner@example.com", password="Password123!", is_superuser=True, is_staff=True
        )
        self.staff = User.objects.create_user(
            email="staff@example.com", password="Password123!", is_staff=True
        )
        self.client.force_authenticate(user=self.superuser)

    def test_list_users_includes_counts(self) -> None:
        response = self.client.get(reverse("admin_users"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 3)  # superuser + staff + customer
        item = next(u for u in response.data["items"] if u["email"] == "customer@example.com")
        self.assertEqual(item["projectCount"], 1)
        self.assertIn("subscription", item)

    def test_search_filters_users(self) -> None:
        response = self.client.get(reverse("admin_users"), {"search": "customer"})
        self.assertEqual(response.data["total"], 1)
        self.assertEqual(response.data["items"][0]["email"], "customer@example.com")

    def test_detail_includes_payments_and_adjustments(self) -> None:
        Payment.objects.create(user=self.customer, amount=9.0, status="paid")
        CreditAdjustment.objects.create(
            user=self.customer, performed_by=self.superuser, amount=5, reason="grant"
        )
        response = self.client.get(reverse("admin_user_detail", args=[self.customer.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["payments"]), 1)
        self.assertEqual(len(response.data["creditAdjustments"]), 1)

    def test_plan_change_resets_credits(self) -> None:
        response = self.client.post(
            reverse("admin_user_plan", args=[self.customer.id]),
            {"plan": "plus", "creditsMode": "reset"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.plan, "plus")
        self.assertEqual(float(self.customer.credits_total), 35)
        self.assertTrue(
            Subscription.objects.filter(user=self.customer, plan="plus", status="active").exists()
        )
        self.assertTrue(
            CreditAdjustment.objects.filter(user=self.customer, reason="plan_change").exists()
        )

    def test_plan_change_requires_valid_plan(self) -> None:
        response = self.client.post(
            reverse("admin_user_plan", args=[self.customer.id]),
            {"plan": "platinum"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_credit_grant_updates_balance_and_logs(self) -> None:
        response = self.client.post(
            reverse("admin_user_credits", args=[self.customer.id]),
            {"amount": 10, "reason": "grant", "notes": "thanks"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertEqual(float(self.customer.credits_remaining), 60)
        self.assertTrue(
            CreditAdjustment.objects.filter(user=self.customer, amount=10).exists()
        )

    def test_staff_support_fields(self) -> None:
        self.client.force_authenticate(user=self.staff)
        response = self.client.patch(
            reverse("admin_user_detail", args=[self.customer.id]),
            {"isActive": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)

    def test_delete_superuser_only(self) -> None:
        self.client.force_authenticate(user=self.staff)
        response = self.client.delete(reverse("admin_user_detail", args=[self.customer.id]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(user=self.superuser)
        response = self.client.delete(reverse("admin_user_detail", args=[self.customer.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(User.objects.filter(pk=self.customer.id).exists())

    def test_create_user_manually(self) -> None:
        response = self.client.post(
            reverse("admin_users"),
            {"email": "new@example.com", "firstName": "New", "plan": "basic"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="new@example.com")
        self.assertEqual(user.plan, "basic")
        self.assertTrue(Subscription.objects.filter(user=user, status="active").exists())


class AdminPaymentTests(APITestCase):
    """Payments listing and manual entry."""

    def setUp(self) -> None:
        self.customer = User.objects.create_user(email="customer@example.com", password="Password123!")
        self.superuser = User.objects.create_user(
            email="owner@example.com", password="Password123!", is_superuser=True, is_staff=True
        )
        self.staff = User.objects.create_user(
            email="staff@example.com", password="Password123!", is_staff=True
        )
        self.url = reverse("admin_payments")

    def test_staff_lists_payments(self) -> None:
        Payment.objects.create(user=self.customer, amount=9.0, status="paid")
        self.client.force_authenticate(user=self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(response.data["items"][0]["email"], "customer@example.com")

    def test_staff_cannot_create_payment(self) -> None:
        self.client.force_authenticate(user=self.staff)
        response = self.client.post(
            self.url,
            {"email": "customer@example.com", "amount": 29.0, "status": "paid"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_creates_manual_payment(self) -> None:
        self.client.force_authenticate(user=self.superuser)
        response = self.client.post(
            self.url,
            {"email": "customer@example.com", "amount": 29.0, "status": "paid"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Payment.objects.filter(user=self.customer).count(), 1)


class AdminPaymentReviewTests(APITestCase):
    """Approve/reject flow for client-submitted EasyPaisa payments."""

    def setUp(self) -> None:
        self.customer = User.objects.create_user(
            email="customer@example.com",
            password="Password123!",
            plan="free",
            credits_total=10,
            credits_used=0,
            credits_remaining=10,
        )
        self.superuser = User.objects.create_user(
            email="owner@example.com", password="Password123!", is_superuser=True, is_staff=True
        )
        self.staff = User.objects.create_user(
            email="staff@example.com", password="Password123!", is_staff=True
        )
        self.payment = Payment.objects.create(
            user=self.customer,
            plan="plus",
            amount=7999,
            currency="PKR",
            method="easypaisa",
            status="pending",
        )
        self.review_url = reverse("admin_payment_review", args=[self.payment.id])

    def test_staff_cannot_review(self) -> None:
        self.client.force_authenticate(user=self.staff)
        response = self.client.post(
            self.review_url, {"decision": "approve"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_cannot_review(self) -> None:
        response = self.client.post(
            self.review_url, {"decision": "approve"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_approve_grants_credits_on_top(self) -> None:
        self.client.force_authenticate(user=self.superuser)
        response = self.client.post(
            self.review_url, {"decision": "approve"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "paid")

        self.payment.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")
        self.assertEqual(self.payment.reviewed_by, self.superuser)
        self.assertEqual(self.customer.plan, "plus")
        # Plus grants 35 monthly credits added on top of the existing 10.
        self.assertEqual(self.customer.credits_total, 45)
        self.assertEqual(self.customer.credits_remaining, 45)
        self.assertIsNotNone(self.customer.credits_reset_at)
        self.assertTrue(
            Subscription.objects.filter(user=self.customer, plan="plus", status="active").exists()
        )
        adjustment = CreditAdjustment.objects.filter(user=self.customer, reason="payment").latest("created_at")
        self.assertEqual(adjustment.amount, 35)
        self.assertEqual(adjustment.performed_by, self.superuser)

    def test_approve_twice_is_rejected(self) -> None:
        self.client.force_authenticate(user=self.superuser)
        first = self.client.post(self.review_url, {"decision": "approve"}, format="json")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        second = self.client.post(self.review_url, {"decision": "approve"}, format="json")
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.credits_total, 45)

    def test_reject_stores_reason_no_credits(self) -> None:
        self.client.force_authenticate(user=self.superuser)
        response = self.client.post(
            self.review_url,
            {"decision": "reject", "reason": "Payment not received"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(self.payment.status, "failed")
        self.assertEqual(self.payment.notes, "Payment not received")
        self.assertEqual(self.customer.plan, "free")
        self.assertEqual(self.customer.credits_total, 10)
        self.assertFalse(CreditAdjustment.objects.filter(user=self.customer).exists())

    def test_review_rejects_unknown_decision(self) -> None:
        self.client.force_authenticate(user=self.superuser)
        response = self.client.post(
            self.review_url, {"decision": "maybe"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "pending")

    def test_review_after_reject_is_rejected(self) -> None:
        self.client.force_authenticate(user=self.superuser)
        self.client.post(self.review_url, {"decision": "reject"}, format="json")
        response = self.client.post(self.review_url, {"decision": "approve"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.plan, "free")

    def test_approve_topup_grants_credits_without_changing_plan(self) -> None:
        self.customer.plan = "basic"
        self.customer.credits_total = Decimal("8")
        self.customer.credits_remaining = Decimal("2")
        self.customer.save()

        topup_payment = Payment.objects.create(
            user=self.customer,
            payment_type="topup",
            pack="pack_medium",
            amount=4199,
            currency="PKR",
            method="easypaisa",
            status="pending",
        )
        url = reverse("admin_payment_review", args=[topup_payment.id])
        self.client.force_authenticate(user=self.superuser)
        response = self.client.post(url, {"decision": "approve"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        topup_payment.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(topup_payment.status, "paid")
        self.assertEqual(self.customer.plan, "basic")
        self.assertEqual(self.customer.credits_total, Decimal("23"))
        self.assertEqual(self.customer.credits_remaining, Decimal("17"))
        self.assertTrue(
            CreditAdjustment.objects.filter(user=self.customer, reason="topup").exists()
        )

    def test_list_includes_review_fields(self) -> None:
        self.client.force_authenticate(user=self.staff)
        response = self.client.get(reverse("admin_payments"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.data["items"][0]
        self.assertEqual(item["plan"], "plus")
        self.assertEqual(item["currentPlan"], "free")
        self.assertIn("screenshotUrl", item)
        self.assertIn("reviewedAt", item)


class AdminStatsTests(APITestCase):
    """Stats aggregates reflect real data (users, jobs, payments, subscriptions)."""

    def setUp(self) -> None:
        self.staff = User.objects.create_user(
            email="staff@example.com", password="Password123!", is_staff=True
        )
        self.customer = User.objects.create_user(
            email="customer@example.com", password="Password123!", plan="pro"
        )
        self.project = Project.objects.create(owner=self.customer, name="Brand")
        Subscription.objects.create(user=self.customer, plan="pro", status="active")
        Payment.objects.create(user=self.customer, amount=79.0, status="paid")
        ImageJob.objects.create(
            project=self.project, user=self.customer, capability="textToImage",
            model="fal-ai/flux/dev", status="succeeded", credits_used=1.5,
        )
        self.client.force_authenticate(user=self.staff)

    def test_stats_totals(self) -> None:
        response = self.client.get(reverse("admin_stats"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["totals"]["totalCustomers"], 2)
        self.assertEqual(data["plans"]["distribution"].get("pro"), 1)
        self.assertEqual(data["plans"]["paidCustomers"], 1)
        self.assertEqual(data["jobs"]["combined"]["total"], 1)
        self.assertEqual(data["jobs"]["combined"]["successRate"], 100)
        self.assertEqual(float(data["revenue"]["mrrUsd"]), 79.0)
        self.assertEqual(data["revenue"]["revenueThisMonth"], {"USD": 79.0})
        self.assertEqual(len(data["charts"]["signups"]), 30)
        self.assertEqual(data["charts"]["signups"][-1]["value"], 2)  # staff + customer today

    def test_usage_breakdown(self) -> None:
        response = self.client.get(reverse("admin_usage"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["image"]["byStatus"]["total"], 1)
        emails = {u["email"] for u in response.data["topConsumers"]}
        self.assertIn("customer@example.com", emails)

    def test_revenue_summary(self) -> None:
        response = self.client.get(reverse("admin_revenue"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["totalRevenue"], {"USD": 79.0})
        self.assertEqual(response.data["subscriptionCounts"].get("pro"), 1)

    def test_revenue_split_by_currency_and_paid_plan(self) -> None:
        # Customer is now on Pro, but this payment bought Basic; top-ups aren't plan revenue.
        Payment.objects.create(
            user=self.customer, payment_type="subscription", plan="basic",
            amount=2499, currency="PKR", status="paid",
        )
        Payment.objects.create(
            user=self.customer, payment_type="topup", pack="pack_small",
            amount=1699, currency="PKR", status="paid",
        )
        data = self.client.get(reverse("admin_revenue")).data
        self.assertEqual(data["totalRevenue"], {"USD": 79.0, "PKR": 4198.0})
        by_plan = {item["plan"]: item["totals"] for item in data["byPlan"]}
        self.assertEqual(by_plan, {"basic": {"PKR": 2499.0}})

    def test_plans_endpoint(self) -> None:
        response = self.client.get(reverse("admin_plans"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = {item["id"]: item for item in response.data["items"]}
        self.assertEqual(items["pro"]["subscriberCount"], 1)


class AdminSettingsTests(APITestCase):
    """Settings read (staff) and edit (superuser)."""

    def setUp(self) -> None:
        self.customer = User.objects.create_user(email="customer@example.com", password="Password123!")
        self.superuser = User.objects.create_user(
            email="owner@example.com", password="Password123!", is_superuser=True, is_staff=True
        )
        self.staff = User.objects.create_user(
            email="staff@example.com", password="Password123!", is_staff=True
        )
        self.url = reverse("admin_settings")

    def test_staff_reads_settings_and_platforms(self) -> None:
        self.client.force_authenticate(user=self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["defaultFreeCredits"], "0")
        self.assertIn("youtube", response.data["platforms"])
        self.assertIn("tiktok", response.data["platforms"])

    def test_staff_cannot_edit_settings(self) -> None:
        self.client.force_authenticate(user=self.staff)
        response = self.client.put(self.url, {"defaultFreeCredits": "100"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_edits_settings(self) -> None:
        self.client.force_authenticate(user=self.superuser)
        response = self.client.put(
            self.url,
            {"defaultFreeCredits": "100", "maintenanceBanner": "Scheduled maintenance"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["defaultFreeCredits"], "100")
        self.assertEqual(response.data["maintenanceBanner"], "Scheduled maintenance")

    def test_superuser_edits_easypaisa_details(self) -> None:
        self.client.force_authenticate(user=self.superuser)
        response = self.client.put(
            self.url,
            {"easypaisaNumber": "0300-1234567", "easypaisaName": "Admart Media"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["easypaisaNumber"], "0300-1234567")
        self.assertEqual(response.data["easypaisaName"], "Admart Media")

    def test_default_free_credits_applied_on_create(self) -> None:
        from admin_panel.models import AdminSetting

        AdminSetting.objects.update_or_create(key="default_free_credits", defaults={"value": "75"})
        self.client.force_authenticate(user=self.superuser)
        response = self.client.post(
            reverse("admin_users"), {"email": "free@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="free@example.com")
        self.assertEqual(float(user.credits_remaining), 75.0)


class SubscriptionExpiryTests(APITestCase):
    def _user(self, *, reset_in_days: int, remaining: str):
        from datetime import timedelta

        from django.utils import timezone

        user = User.objects.create_user(
            email=f"exp{reset_in_days}{remaining}@example.com",
            password="Password123!",
            plan="plus",
            credits_total=Decimal(remaining) + 5,
            credits_used=5,
            credits_remaining=Decimal(remaining),
            credits_reset_at=timezone.now() + timedelta(days=reset_in_days),
            topup_credits=min(Decimal("5"), Decimal(remaining)),
        )
        Subscription.objects.create(user=user, plan="plus", status="active")
        return user

    def _get_balance(self, user):
        from rest_framework_simplejwt.tokens import RefreshToken

        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return self.client.get("/api/credits")

    def test_lapsed_plan_downgrades_and_keeps_topup_credits(self) -> None:
        # 5 of the 40 remaining came from a top-up.
        user = self._get_balance(self._user(reset_in_days=-1, remaining="40")).wsgi_request.user
        user.refresh_from_db()
        self.assertEqual(user.plan, "free")
        self.assertEqual(user.credits_remaining, 5)
        self.assertEqual(user.credits_total, 10)
        self.assertIsNone(user.credits_reset_at)
        self.assertTrue(Subscription.objects.filter(user=user, status="expired").exists())
        adj = CreditAdjustment.objects.get(user=user, reason="plan_change")
        self.assertEqual(adj.amount, -35)

    def test_lapsed_plan_never_goes_negative(self) -> None:
        user = self._user(reset_in_days=-1, remaining="3")
        User.objects.filter(pk=user.pk).update(topup_credits=0)
        self._get_balance(user)
        user.refresh_from_db()
        self.assertEqual(user.plan, "free")
        self.assertEqual(user.credits_remaining, 0)

    def test_active_plan_untouched(self) -> None:
        user = self._user(reset_in_days=5, remaining="40")
        response = self._get_balance(user)
        self.assertEqual(response.data["plan"], "plus")
        self.assertEqual(response.data["creditsRemaining"], 40)


class RenewalAndTopupTrackingTests(APITestCase):
    def setUp(self) -> None:
        from datetime import timedelta

        from django.utils import timezone

        self.admin = User.objects.create_superuser(email="boss@example.com", password="Password123!")
        self.end = timezone.now() + timedelta(days=10)
        self.user = User.objects.create_user(
            email="renew@example.com", password="Password123!", plan="plus",
            credits_total=20, credits_remaining=20, credits_reset_at=self.end,
        )

    def _approve(self, **payment):
        from admin_panel.services import review_payment

        p = Payment.objects.create(user=self.user, amount=1, status="pending", **payment)
        review_payment(p.pk, "approve", self.admin)
        self.user.refresh_from_db()

    def test_same_plan_renewal_extends_from_current_end(self) -> None:
        from datetime import timedelta

        self._approve(plan="plus")
        self.assertEqual(self.user.credits_reset_at, self.end + timedelta(days=30))
        self.assertEqual(self.user.credits_remaining, 55)
        sub = Subscription.objects.get(user=self.user)
        self.assertEqual(sub.current_period_end, self.end + timedelta(days=30))

    def test_plan_switch_starts_new_period_now(self) -> None:
        from datetime import timedelta

        from django.utils import timezone

        self._approve(plan="pro")
        self.assertEqual(self.user.plan, "pro")
        self.assertLess(self.user.credits_reset_at - timezone.now(), timedelta(days=30, seconds=5))
        self.assertEqual(self.user.credits_remaining, 140)

    def test_topups_survive_spending_plan_credits_first(self) -> None:
        from content.credits import reserve_credits

        self._approve(payment_type="topup", pack="pack_small")  # +5 top-up -> 25
        self.assertEqual(self.user.topup_credits, 5)
        reserve_credits(self.user, "18")  # 7 left: plan credits spent first
        self.user.refresh_from_db()
        self.assertEqual(self.user.topup_credits, 5)
        reserve_credits(self.user, "4")  # 3 left: now eating top-ups
        self.user.refresh_from_db()
        self.assertEqual(self.user.topup_credits, 3)

    def test_new_payments_default_to_pending(self) -> None:
        p = Payment.objects.create(user=self.user, amount=1)
        self.assertEqual(p.status, "pending")


class SeededPlansMatchCodeTests(APITestCase):
    def test_migrated_plan_features_match_plan_tiers(self) -> None:
        from admin_panel.models import PlanDefinition
        from users.plans import PLAN_TIERS

        for plan in PlanDefinition.objects.all():
            self.assertEqual(plan.features, PLAN_TIERS[plan.plan_id]["features"], plan.plan_id)


@override_settings(PRIVATE_MEDIA_ROOT=__import__("tempfile").mkdtemp(prefix="admart-test-private-"))
class TopupPacksFromDatabaseTests(APITestCase):
    def setUp(self) -> None:
        from admin_panel.models import TopupPack

        # Packs are seeded by migration; the admin edits one and hides another.
        TopupPack.objects.filter(pack_id="pack_small").update(credits=7, price_pkr=1999, name="Starter Plus")
        TopupPack.objects.filter(pack_id="pack_large").update(is_public=False)
        self.user = User.objects.create_user(email="packs@example.com", password="Password123!")
        self.admin = User.objects.create_superuser(email="packadmin@example.com", password="Password123!")
        self.client.force_authenticate(user=self.user)

    def _submit(self, pack: str, txn: str):
        from django.core.files.uploadedfile import SimpleUploadedFile

        shot = SimpleUploadedFile("proof.png", b"\x89PNG\r\n\x1a\nfake-png-body", content_type="image/png")
        return self.client.post(
            "/api/credits/payments/submit",
            {"pack": pack, "screenshot": shot, "transactionId": txn},
            format="multipart",
        )

    def test_topups_endpoint_follows_database(self) -> None:
        items = self.client.get("/api/credits/topups").data["items"]
        self.assertEqual([p["id"] for p in items], ["pack_small", "pack_medium"])
        self.assertEqual(items[0]["name"], "Starter Plus")
        self.assertEqual(items[0]["pricePkr"], 1999)

    def test_hidden_pack_cannot_be_bought(self) -> None:
        response = self._submit("pack_large", "EP-HIDDEN")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("pack", response.data)

    def test_approval_uses_database_pack(self) -> None:
        from admin_panel.services import review_payment

        response = self._submit("pack_small", "EP-SMALL")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(float(response.data["amount"]), 1999)
        review_payment(response.data["id"], "approve", self.admin)
        self.user.refresh_from_db()
        self.assertEqual(self.user.topup_credits, 7)


class AdminPlanAndPackEditTests(APITestCase):
    def setUp(self) -> None:
        self.owner = User.objects.create_superuser(email="owner@example.com", password="Password123!")
        self.staff = User.objects.create_user(email="staffer@example.com", password="Password123!", is_staff=True)
        self.client.force_authenticate(user=self.owner)

    def test_owner_edits_pack_and_billing_follows(self) -> None:
        response = self.client.put(
            reverse("admin_pack_detail", kwargs={"pack_id": "pack_medium"}),
            {"name": "Creator Max", "credits": 18, "pricePkr": 4500, "popular": False,
             "features": ["18 credits", "  ", "Never expires"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["features"], ["18 credits", "Never expires"])
        public = {p["id"]: p for p in self.client.get("/api/credits/topups").data["items"]}
        self.assertEqual(public["pack_medium"]["name"], "Creator Max")
        self.assertEqual(public["pack_medium"]["pricePkr"], 4500)

    def test_hidden_pack_still_listed_for_admin(self) -> None:
        self.client.put(
            reverse("admin_pack_detail", kwargs={"pack_id": "pack_large"}), {"isPublic": False}, format="json"
        )
        items = {p["id"]: p for p in self.client.get(reverse("admin_packs")).data["items"]}
        self.assertFalse(items["pack_large"]["isPublic"])
        public_ids = [p["id"] for p in self.client.get("/api/credits/topups").data["items"]]
        self.assertNotIn("pack_large", public_ids)

    def test_invalid_values_are_400_not_500(self) -> None:
        for url, body in [
            (reverse("admin_pack_detail", kwargs={"pack_id": "pack_small"}), {"pricePkr": -5}),
            (reverse("admin_pack_detail", kwargs={"pack_id": "pack_small"}), {"credits": "lots"}),
            (reverse("admin_pack_detail", kwargs={"pack_id": "pack_small"}), {"isPublic": "false"}),
            (reverse("admin_plan_detail", kwargs={"plan_id": "plus"}), {"priceUsd": "abc"}),
            (reverse("admin_plan_detail", kwargs={"plan_id": "plus"}), {"limits": {"max_projects": "4"}}),
            (reverse("admin_plan_detail", kwargs={"plan_id": "plus"}), {"name": "  "}),
        ]:
            response = self.client.put(url, body, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, body)

    def test_owner_edits_plan_limits(self) -> None:
        response = self.client.put(
            reverse("admin_plan_detail", kwargs={"plan_id": "plus"}),
            {"monthlyCredits": 40, "limits": {"max_projects": 6, "has_analytics": True, "discount_percent": 12.5}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["limits"]["max_projects"], 6)
        self.assertEqual(float(response.data["monthlyCredits"]), 40)

    def test_staff_can_view_but_not_edit(self) -> None:
        self.client.force_authenticate(user=self.staff)
        self.assertEqual(self.client.get(reverse("admin_packs")).status_code, status.HTTP_200_OK)
        response = self.client.put(
            reverse("admin_pack_detail", kwargs={"pack_id": "pack_small"}), {"name": "X"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
