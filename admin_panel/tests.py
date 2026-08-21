from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
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
        self.assertEqual(float(data["revenue"]["revenueThisMonthUsd"]), 79.0)
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
        self.assertEqual(float(response.data["totalRevenueUsd"]), 79.0)
        self.assertEqual(response.data["subscriptionCounts"].get("pro"), 1)

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
        self.assertEqual(response.data["defaultFreeCredits"], "50")
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
