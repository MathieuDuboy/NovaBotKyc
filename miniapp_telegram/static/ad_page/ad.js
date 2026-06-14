// Add smooth scroll behavior
document.addEventListener('DOMContentLoaded', function() {
    // Add click event listener to the "Get Started" button
    const getStartedBtn = document.querySelector('.btn-primary');
    if (getStartedBtn) {
        getStartedBtn.addEventListener('click', function(e) {
            e.preventDefault();
            // Add a smooth animation when clicking the button
            this.style.transform = 'scale(0.95)';
            setTimeout(() => {
                this.style.transform = 'scale(1)';
                // Redirect to the main page
                window.location.href = '/';
            }, 150);
        });
    }

    // Add hover effects to feature items
    const featureItems = document.querySelectorAll('.feature-item');
    featureItems.forEach(item => {
        item.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-2px)';
            this.style.transition = 'transform 0.2s ease';
        });
        item.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0)';
        });
    });

    // User ID logic: from Telegram or config.json
    let userId = null;
    let ENV = 'prod';
    fetch('/config.json')
        .then(res => res.json())
        .then(config => {
            ENV = config.ENV;
            // if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initDataUnsafe && window.Telegram.WebApp.initDataUnsafe.user) {
            userId = window.Telegram.WebApp.initDataUnsafe.user.id;
            // } else {
            //     userId = config.USER_ID;
            // }
            document.getElementById('user-info').textContent = userId;
        });

    // Language setup (default to English)
    // (Add more if you want to support language switching)
    // ...

    // No transaction logic needed for ad page, but you can add if you want to show demo transactions
});
