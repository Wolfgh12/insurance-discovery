import os
from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse, Http404
from vault import views as vault_views

def service_worker(request):
    """
    Serves sw.js directly from the root domain with root-scope permission.
    Resolves Chrome's SecurityError and allows the PWA to install with the custom shield icon.
    """
    primary_path = os.path.join(settings.BASE_DIR, 'static', 'js', 'sw.js')
    fallback_path = os.path.join(settings.STATIC_ROOT, 'js', 'sw.js') if settings.STATIC_ROOT else primary_path
    target_path = primary_path if os.path.exists(primary_path) else fallback_path

    if os.path.exists(target_path):
        with open(target_path, 'r', encoding='utf-8') as f:
            content = f.read()
        response = HttpResponse(content, content_type='application/javascript')
        response['Service-Worker-Allowed'] = '/'
        return response
    raise Http404("Service worker script not found.")

urlpatterns = [
    # Root Service Worker Route (Resolves root scope restriction)
    path('sw.js', service_worker, name='service_worker'),

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