from .models import PlatformConfiguration

def platform_settings(request):
    return {
        'platform_config': PlatformConfiguration.get_solo()
    }