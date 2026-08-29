from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views

app_name = 'vault'

urlpatterns = [
    path('', views.home_search_view, name='home'),
    path('signup/', views.signup_view, name='signup'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),
    
    # Pre-payment identity validation & forensic telemetry logging
    path('api/check-claimant-match/', views.check_claimant_match_view, name='check_claimant_match'),
    
    # Paystack payment verification & claimant credential generation
    path('api/verify-unlock/', views.verify_unlock_view, name='verify_unlock'),
    
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
]