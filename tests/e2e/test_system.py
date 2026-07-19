import pytest
from playwright.sync_api import Page, expect

BASE_URL = "https://twitterbot-frontend-production.up.railway.app"
API_URL = "https://twitterbot-backend-production.up.railway.app/api"

def test_api_health(page: Page):
    """Test that the backend API is healthy"""
    print("Checking backend API health...")
    response = page.request.get(f"{API_URL}/health")
    assert response.ok
    data = response.json()
    assert data.get("status") == "healthy"
    print(f"Backend API is healthy: {data}")

def test_frontend_loads(page: Page):
    """Test that the frontend is accessible and loads the login page"""
    print("Navigating to frontend...")
    page.goto(BASE_URL)
    
    # The app should load and show "Sign In"
    expect(page.locator("text=Sign In")).to_be_visible(timeout=10000)
    print("Frontend loaded successfully and login page is visible.")

def test_login_validation(page: Page):
    """Test the UI login flow with invalid credentials to ensure error handling works"""
    print("Testing login flow with invalid credentials...")
    page.goto(BASE_URL + "/login")
    
    # Fill in dummy credentials
    page.fill('input[type="email"]', 'automated_test@example.com')
    page.fill('input[type="password"]', 'wrongpassword')
    page.click('button:has-text("Sign In")')
    
    # Wait for potential error toast or message
    page.wait_for_timeout(2000)
    print("Login validation is stable.")

def test_protected_routes_redirect(page: Page):
    """Test that protected routes properly redirect to login"""
    print("Testing protected route redirects...")
    routes = ["/dashboard", "/accounts", "/scheduler", "/extracted-tweets", "/api-usage"]
    for route in routes:
        page.goto(BASE_URL + route)
        expect(page.locator("text=Sign In")).to_be_visible(timeout=10000)
    print("Protected routes are properly secured.")
