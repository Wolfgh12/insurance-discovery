from .models import PlatformConfiguration

def platform_settings(request):
    """
    Injects singleton PlatformConfiguration into all templates site-wide.
    Provides global access to security anti-inspect toggles, DOM poisoning switches,
    dynamic statutory fees, and module readiness flags.
    """
    config = PlatformConfiguration.get_solo()
    return {
        'platform_config': config,
        'config': config,  # Short alias for clean template usage (e.g. {{ config.unlock_fee }})
    } 