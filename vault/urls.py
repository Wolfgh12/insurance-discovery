from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views

app_name = 'vault'

urlpatterns = [
    path('', views.home_search_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('pricing/', views.pricing_view, name='pricing'),
    path('contact/', views.contact_view, name='contact'),
    path('terms/', views.terms_view, name='terms'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),
    
    # Citizen Password Recovery & Security Questions Verification
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('reset-password/direct/', views.reset_password_direct_view, name='reset_password_direct'),
    path('reset-password/<str:uidb64>/<str:token>/', views.reset_password_confirm_view, name='reset_password_confirm'),

    # Account Activation & Mandatory Security Question Recovery Gate
    path('activate/<str:uidb64>/<str:token>/', views.activate_account_view, name='activate_account'),
    path('security-questions/', views.security_questions_setup_view, name='security_questions_setup'),
    
    # Pre-payment identity validation & forensic telemetry logging
    path('api/check-claimant-match/', views.check_claimant_match_view, name='check_claimant_match'),
    
    # Paystack payment verifications & automated webhook sync
    path('api/verify-unlock/', views.verify_unlock_view, name='verify_unlock'),
    path('api/verify-subscription/', views.verify_subscription_view, name='verify_subscription'),
    path('api/verify-registration-fee/', views.verify_registration_fee_view, name='verify_registration_fee'),
    path('api/paystack-webhook/', views.paystack_webhook_view, name='paystack_webhook'),
    
    # Claimant Dashboard & Authentication Portal
    path('claimant/dashboard/', views.claimant_dashboard_view, name='claimant_dashboard'),
    path('claimant/login/', views.claimant_login_view, name='claimant_login'),

    # Private Claimant Vault Access View
    path('claimant/vault/<str:access_token>/', views.claimant_vault_view, name='claimant_vault'),

    # Toggleable Unified Admin Login Portal (Lead Admin & Normal Admin)
    path('portal/admin/login/', views.admin_login_view, name='admin_login'),

    # Administrative Dashboards & Claim Dispatch
    path('portal/lead-admin/', views.lead_admin_dashboard_view, name='lead_admin_dashboard'),
    path('portal/admin/dashboard/', views.staff_admin_dashboard_view, name='staff_admin_dashboard'),
    path('portal/claims/<int:claim_id>/update-status/', views.update_claim_status_view, name='update_claim_status'),
    path('portal/policies/<int:policy_id>/update-status/', views.update_policy_status_view, name='update_policy_status'),
    path('portal/audit-logs/<int:log_id>/delete/', views.delete_audit_log_view, name='delete_audit_log'),
    path('portal/inquiries/<int:inquiry_id>/update-status/', views.update_inquiry_status_view, name='update_inquiry_status'),
]