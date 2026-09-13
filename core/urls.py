from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from vault import views as vault_views

urlpatterns = [
    # Intercept Django admin logout and redirect directly to admin login
    path('admin/logout/', LogoutView.as_view(next_page='/admin/login/'), name='admin_logout'),
    path('admin/', admin.site.urls),
    
    # Custom 2-step verification & unactivated account interception
    path('login/', vault_views.login_view, name='login'),
    path('accounts/login/', vault_views.login_view),
    
    path('accounts/', include('django.contrib.auth.urls')),  # Handles password reset and recovery routes
    path('', include('vault.urls', namespace='vault')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)