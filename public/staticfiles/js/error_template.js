document.addEventListener("DOMContentLoaded", function () {
    const status = parseInt("{{ status }}", 10);
    console.log("Error status:", status);
    // Redirect to home page after 5 seconds for 4xx errors
    if (status >= 400 && status < 500) {
        setTimeout(function () {
            window.location.href = "{% url 'core:index' %}";
        }, 5000);
    }
});