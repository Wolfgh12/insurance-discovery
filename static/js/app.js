// Register Service Worker with Lifecycle & Scope Controls
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/static/js/sw.js', { scope: '/' })
      .then((registration) => {
        console.log('PWA Service Worker active with scope:', registration.scope);

        // Check for worker updates on navigation
        registration.update().catch(() => {});

        // Handle incoming worker updates without page freeze
        registration.addEventListener('updatefound', () => {
          const installingWorker = registration.installing;
          if (installingWorker) {
            installingWorker.addEventListener('statechange', () => {
              if (installingWorker.state === 'installed' && navigator.serviceWorker.controller) {
                console.log('New service worker available; cache updated.');
              }
            });
          }
        });
      })
      .catch((err) => {
        console.error('Service Worker registration failed:', err);
      });
  });

  // Automatically refresh when a new Service Worker takes control
  let refreshing = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!refreshing) {
      refreshing = true;
      window.location.reload();
    }
  });
}

// Intercept Network Switches & Auto-Recover Dropped Connections
window.addEventListener('online', () => {
  // If user got stuck on the fallback/offline page when network switched, reload immediately
  if (
    document.title.includes('Reconnecting') ||
    document.body.innerText.includes('Network Reconnecting') ||
    document.body.innerText.includes('Connection Lost')
  ) {
    window.location.reload();
  }
});

// Prevent unhandled promise rejections on temporary network drops
window.addEventListener('unhandledrejection', (event) => {
  if (
    event.reason &&
    (event.reason.name === 'TypeError' ||
      String(event.reason).includes('Failed to fetch') ||
      String(event.reason).includes('NetworkError'))
  ) {
    event.preventDefault();
  }
});