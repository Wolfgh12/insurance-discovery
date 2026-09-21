from django.contrib.auth import logout
from django.contrib import messages
from django.shortcuts import redirect

class AccountClearanceMiddleware:
    """
    Zero-Trust Real-Time User Enforcement:
    Evaluates account_status on every incoming HTTP request for authenticated users.
    If an administrator suspends or terminates a user via Django Admin, this middleware
    instantly terminates their active session, logs them out, and halts further traversal.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            status = getattr(request.user, 'account_status', 'ACTIVE')

            if status in ['SUSPENDED', 'TERMINATED']:
                reason = getattr(request.user, 'suspension_reason', None)
                if status == 'SUSPENDED':
                    msg = (
                        f"Your account has been temporarily suspended by Administration. "
                        f"Reason: {reason or 'Administrative review in progress.'}"
                    )
                else:
                    msg = (
                        f"Your access has been permanently terminated. "
                        f"Reason: {reason or 'Statutory clearance revocation.'}"
                    )

                # Flush session and log out
                logout(request)
                messages.error(request, msg)
                return redirect('login')

        response = self.get_response(request)
        return response 