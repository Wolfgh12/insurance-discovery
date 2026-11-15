// Register Service Worker Silently (Never Force-Reload Active Tabs)
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js', { scope: '/' })
      .then((registration) => {
        registration.update().catch(() => {});
      })
      .catch((err) => {
        console.error('Service Worker registration failed:', err);
      });
  });
}

// Intercept Network Switches & Auto-Recover Dropped Connections
window.addEventListener('online', () => {
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
