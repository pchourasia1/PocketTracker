// main.js — small progressive enhancements; the app works without it

// Ask before submitting any form marked with data-confirm (e.g. delete buttons)
document.addEventListener("submit", function (event) {
    var message = event.target.dataset.confirm;
    if (message && !window.confirm(message)) {
        event.preventDefault();
    }
});
