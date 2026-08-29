from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect


def lead_admin_required(view_func):
    """
    Ensures user is an authenticated Superuser or Staff Member with Lead Admin clearance.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, "Authentication required to access the Lead Administration Portal.")
            return redirect('vault:claimant_login')

        if request.user.is_superuser or request.user.user_type == 'STAFF' or request.user.is_staff:
            return view_func(request, *args, **kwargs)

        messages.error(request, "Unauthorized. You lack Lead Administrator privileges.")
        return redirect('vault:dashboard')

    return _wrapped_view


def insurer_admin_required(view_func):
    """
    Ensures user is an authorized Insurer Desk Admin, Staff Member, or Superuser.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, "Authentication required to access the Underwriting Desk.")
            return redirect('vault:claimant_login')

        if (
            request.user.is_superuser 
            or request.user.user_type in ['INSURER_ADMIN', 'STAFF'] 
            or request.user.is_staff
        ):
            return view_func(request, *args, **kwargs)

        messages.error(request, "Unauthorized. You lack Underwriting Desk permissions.")
        return redirect('vault:dashboard')

    return _wrapped_view