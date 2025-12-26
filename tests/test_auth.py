"""Tests for API authentication and authorization."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from autoops_architect.api.app import create_app
from autoops_architect.api.auth import (
    Role,
    User,
    UserInDB,
    create_access_token,
    create_api_key,
    create_default_admin,
    fake_api_keys_db,
    fake_users_db,
    get_password_hash,
    has_permission,
    verify_password,
)


class TestPasswordHashing:
    """Test password hashing and verification."""

    def test_password_hashing(self) -> None:
        """Test that passwords are hashed correctly."""
        password = "secure_password123"
        hashed = get_password_hash(password)
        
        assert hashed != password
        assert len(hashed) > 20

    def test_password_verification(self) -> None:
        """Test that password verification works."""
        password = "test_password"
        hashed = get_password_hash(password)
        
        assert verify_password(password, hashed)
        assert not verify_password("wrong_password", hashed)


class TestJWTTokens:
    """Test JWT token creation and validation."""

    def test_create_access_token(self) -> None:
        """Test creating an access token."""
        token = create_access_token(
            data={"sub": "testuser", "roles": ["viewer"]},
            expires_delta=timedelta(minutes=30),
        )
        
        assert isinstance(token, str)
        assert len(token) > 20

    def test_token_contains_claims(self) -> None:
        """Test that tokens contain expected claims."""
        from autoops_architect.api.auth import decode_access_token
        
        token = create_access_token(
            data={"sub": "testuser", "roles": ["operator"]},
        )
        
        token_data = decode_access_token(token)
        assert token_data.username == "testuser"
        assert Role.OPERATOR in token_data.roles


class TestAPIKeys:
    """Test API key creation and validation."""

    def test_create_api_key(self) -> None:
        """Test creating an API key."""
        key, key_data = create_api_key(
            name="test-key",
            roles=[Role.VIEWER],
            expires_days=30,
        )
        
        assert isinstance(key, str)
        assert len(key) > 20
        assert key_data.name == "test-key"
        assert Role.VIEWER in key_data.roles

    def test_api_key_validation(self) -> None:
        """Test API key validation."""
        from autoops_architect.api.auth import validate_api_key
        
        key, _ = create_api_key("test-key", [Role.OPERATOR])
        
        validated = validate_api_key(key)
        assert validated is not None
        assert validated.name == "test-key"

    def test_invalid_api_key(self) -> None:
        """Test that invalid API keys are rejected."""
        from autoops_architect.api.auth import validate_api_key
        
        result = validate_api_key("invalid-key-12345")
        assert result is None


class TestRBAC:
    """Test role-based access control."""

    def test_viewer_permissions(self) -> None:
        """Test that viewer has read permissions."""
        user = User(username="viewer", roles=[Role.VIEWER])
        
        assert has_permission(user, "read:workflows")
        assert has_permission(user, "read:templates")
        assert has_permission(user, "read:memory")
        assert not has_permission(user, "execute:workflows")
        assert not has_permission(user, "create:workflows")

    def test_operator_permissions(self) -> None:
        """Test that operator has execute permissions."""
        user = User(username="operator", roles=[Role.OPERATOR])
        
        assert has_permission(user, "read:workflows")
        assert has_permission(user, "execute:workflows")
        assert has_permission(user, "create:workflows")

    def test_admin_permissions(self) -> None:
        """Test that admin has all permissions."""
        user = User(username="admin", roles=[Role.ADMIN])
        
        assert has_permission(user, "read:workflows")
        assert has_permission(user, "execute:workflows")
        assert has_permission(user, "create:workflows")
        assert has_permission(user, "*")  # Wildcard
        assert has_permission(user, "any_permission_at_all")

    def test_multiple_roles(self) -> None:
        """Test that users can have multiple roles."""
        user = User(username="multi", roles=[Role.VIEWER, Role.OPERATOR])
        
        assert has_permission(user, "read:workflows")
        assert has_permission(user, "execute:workflows")


class TestAuthAPI:
    """Test authentication API endpoints."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        # Clear fake databases
        fake_users_db.clear()
        fake_api_keys_db.clear()
        
        # Create test user
        self.test_user = UserInDB(
            username="testuser",
            email="test@example.com",
            hashed_password=get_password_hash("testpass"),
            roles=[Role.OPERATOR],
            disabled=False,
        )
        fake_users_db["testuser"] = self.test_user
        
        # Create admin user
        self.admin_user = create_default_admin("admin", "adminpass")

    def test_login_success(self) -> None:
        """Test successful login."""
        app = create_app()
        client = TestClient(app)
        
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "testuser", "password": "testpass"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["username"] == "testuser"

    def test_login_wrong_password(self) -> None:
        """Test login with wrong password."""
        app = create_app()
        client = TestClient(app)
        
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "testuser", "password": "wrongpass"},
        )
        
        assert response.status_code == 401

    def test_login_nonexistent_user(self) -> None:
        """Test login with non-existent user."""
        app = create_app()
        client = TestClient(app)
        
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "nobody", "password": "password"},
        )
        
        assert response.status_code == 401

    def test_get_current_user(self) -> None:
        """Test getting current user info."""
        app = create_app()
        client = TestClient(app)
        
        # Login first
        login_response = client.post(
            "/api/v1/auth/login",
            data={"username": "testuser", "password": "testpass"},
        )
        token = login_response.json()["access_token"]
        
        # Get current user
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        
        assert response.status_code == 200
        assert response.json()["username"] == "testuser"

    def test_create_api_key_as_admin(self) -> None:
        """Test creating API key as admin."""
        app = create_app()
        client = TestClient(app)
        
        # Login as admin
        login_response = client.post(
            "/api/v1/auth/login",
            data={"username": "admin", "password": "adminpass"},
        )
        token = login_response.json()["access_token"]
        
        # Create API key
        response = client.post(
            "/api/v1/auth/api-keys",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "test-api-key",
                "roles": ["operator"],
                "expires_days": 90,
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "key" in data
        assert data["name"] == "test-api-key"

    def test_create_api_key_as_non_admin_fails(self) -> None:
        """Test that non-admin cannot create API keys."""
        app = create_app()
        client = TestClient(app)
        
        # Login as regular user
        login_response = client.post(
            "/api/v1/auth/login",
            data={"username": "testuser", "password": "testpass"},
        )
        token = login_response.json()["access_token"]
        
        # Try to create API key
        response = client.post(
            "/api/v1/auth/api-keys",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "test-key",
                "roles": ["viewer"],
            },
        )
        
        assert response.status_code == 403

    def test_api_key_authentication(self) -> None:
        """Test authentication with API key."""
        app = create_app()
        client = TestClient(app)
        
        # Create an API key
        key, _ = create_api_key("test-key", [Role.OPERATOR])
        
        # Use API key to access endpoint
        response = client.get(
            "/api/v1/auth/me",
            headers={"X-API-Key": key},
        )
        
        assert response.status_code == 200
        assert response.json()["username"] == "test-key"

    def test_list_permissions(self) -> None:
        """Test listing available permissions."""
        app = create_app()
        client = TestClient(app)
        
        response = client.get("/api/v1/auth/permissions")
        
        assert response.status_code == 200
        data = response.json()
        assert "viewer" in data
        assert "operator" in data
        assert "admin" in data
        assert "read:workflows" in data["viewer"]


class TestAuthIntegration:
    """Test authentication integration with workflows."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        import os
        
        # Enable auth for these tests
        os.environ["AUTOOPS_AUTH_ENABLED"] = "true"
        
        # Clear and set up users
        fake_users_db.clear()
        self.operator = UserInDB(
            username="operator",
            hashed_password=get_password_hash("operatorpass"),
            roles=[Role.OPERATOR],
            disabled=False,
        )
        fake_users_db["operator"] = self.operator

    def teardown_method(self) -> None:
        """Clean up after tests."""
        import os
        os.environ["AUTOOPS_AUTH_ENABLED"] = "false"

    def test_create_workflow_requires_auth(self) -> None:
        """Test that creating workflows requires authentication."""
        app = create_app()
        client = TestClient(app)
        
        # Try without auth
        response = client.post(
            "/api/v1/workflows",
            json={
                "description": "Test workflow",
                "services": ["test"],
            },
        )
        
        assert response.status_code == 401

    def test_create_workflow_with_auth(self) -> None:
        """Test creating workflow with valid auth."""
        app = create_app()
        client = TestClient(app)
        
        # Login
        login_response = client.post(
            "/api/v1/auth/login",
            data={"username": "operator", "password": "operatorpass"},
        )
        token = login_response.json()["access_token"]
        
        # Create workflow
        response = client.post(
            "/api/v1/workflows",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "description": "Investigate errors",
                "services": ["test-service"],
            },
        )
        
        # Should work (status 200 or workflow created)
        assert response.status_code in [200, 201]

