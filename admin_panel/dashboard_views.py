from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render


@staff_member_required
def admin_dashboard(request):
    """Render the superadmin dashboard — styled to match the React admin panel."""
    return render(request, "admin_panel/dashboard.html")
