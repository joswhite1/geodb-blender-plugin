"""
geoDB API Client for Blender Add-on

This module handles communication with the geoDB API, including authentication,
token management, and secure credential storage.
"""

import os
import json
import base64
import hashlib
import requests
import datetime
import uuid
import platform
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Union, List, Callable

import bpy
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ..utils.logging import logger

# API Constants - v2 API with pagination support
API_BASE_URL = "https://geodb.io/api/v2/"
API_TOKEN_URL = f"{API_BASE_URL}api-token-auth/"
API_CHECK_TOKEN_URL = f"{API_BASE_URL}check-token/"
API_LOGOUT_URL = f"{API_BASE_URL}api-logout/"

# 2FA endpoints (v1 API - separate from main v2 API)
API_2FA_BASE_URL = "https://geodb.io/api/v1/"
API_VERIFY_2FA_URL = f"{API_2FA_BASE_URL}auth/verify-2fa/"
API_REQUEST_2FA_RECOVERY_URL = f"{API_2FA_BASE_URL}auth/request-2fa-recovery/"
API_VERIFY_2FA_RECOVERY_URL = f"{API_2FA_BASE_URL}auth/verify-2fa-recovery/"

# Local development settings (can be toggled in preferences)
DEV_API_BASE_URL = "http://localhost:8000/api/v2/"
DEV_API_TOKEN_URL = f"{DEV_API_BASE_URL}api-token-auth/"
DEV_API_CHECK_TOKEN_URL = f"{DEV_API_BASE_URL}check-token/"
DEV_API_LOGOUT_URL = f"{DEV_API_BASE_URL}api-logout/"

# 2FA endpoints for development
DEV_API_2FA_BASE_URL = "http://localhost:8000/api/v1/"
DEV_API_VERIFY_2FA_URL = f"{DEV_API_2FA_BASE_URL}auth/verify-2fa/"
DEV_API_REQUEST_2FA_RECOVERY_URL = f"{DEV_API_2FA_BASE_URL}auth/request-2fa-recovery/"
DEV_API_VERIFY_2FA_RECOVERY_URL = f"{DEV_API_2FA_BASE_URL}auth/verify-2fa-recovery/"

# Token storage constants
# Use MAC address + hostname for machine-specific identifier (available during registration)
BLENDER_MACHINE_ID = f"{uuid.getnode()}-{platform.node()}".encode()
TOKEN_DIRECTORY = os.path.join(bpy.utils.user_resource('CONFIG'), 'geodb_addon')
TOKEN_FILE = os.path.join(TOKEN_DIRECTORY, 'auth_data.bin')
TOKEN_SALT_FILE = os.path.join(TOKEN_DIRECTORY, 'salt.bin')

class GeoDBAPIClient:
    """Client for interacting with the geoDB API."""

    def __init__(self, use_dev_server: bool = False):
        """Initialize the API client.

        Args:
            use_dev_server: Whether to use the development server instead of production.
        """
        self.use_dev_server = use_dev_server
        self.token = None
        self.user_info = None
        self.token_expiry = None
        self.companies = None

        # 2FA session state (temporary, not persisted)
        self.pending_2fa_session = None  # Stores session_token, user_id when 2FA is required

        # Defense-in-depth: cache authorized scope
        self._authorized_company_ids = set()
        self._authorized_project_ids = set()

        # Token unlock rate limiting
        self._unlock_attempts = 0
        self._unlock_lockout_until = None

        # Create a persistent session for connection pooling
        self.session = requests.Session()

        # Set the base URLs based on server choice
        if use_dev_server:
            self.base_url = DEV_API_BASE_URL
            self.token_url = DEV_API_TOKEN_URL
            self.check_token_url = DEV_API_CHECK_TOKEN_URL
            self.logout_url = DEV_API_LOGOUT_URL
            # 2FA URLs
            self.verify_2fa_url = DEV_API_VERIFY_2FA_URL
            self.request_2fa_recovery_url = DEV_API_REQUEST_2FA_RECOVERY_URL
            self.verify_2fa_recovery_url = DEV_API_VERIFY_2FA_RECOVERY_URL
        else:
            self.base_url = API_BASE_URL
            self.token_url = API_TOKEN_URL
            self.check_token_url = API_CHECK_TOKEN_URL
            self.logout_url = API_LOGOUT_URL
            # 2FA URLs
            self.verify_2fa_url = API_VERIFY_2FA_URL
            self.request_2fa_recovery_url = API_REQUEST_2FA_RECOVERY_URL
            self.verify_2fa_recovery_url = API_VERIFY_2FA_RECOVERY_URL

        # Try to load saved token
        self._load_token()

    def _update_authorized_scope(self):
        """Cache the user's authorized company and project IDs."""
        if self.companies:
            self._authorized_company_ids = {c['id'] for c in self.companies if 'id' in c}

    def is_authorized_company(self, company_id: int) -> bool:
        return company_id in self._authorized_company_ids

    def is_authorized_project(self, project_id: int) -> bool:
        return project_id in self._authorized_project_ids

    def add_authorized_projects(self, project_ids):
        """Add project IDs to authorized scope after fetching projects."""
        self._authorized_project_ids.update(project_ids)

    def _get_headers(self) -> Dict[str, str]:
        """Get the headers for API requests."""
        headers = {
            'Content-Type': 'application/json',
        }

        if self.token:
            headers['Authorization'] = f'Token {self.token}'

        return headers

    def _generate_encryption_key(self, password: str) -> bytes:
        """Generate an encryption key from a password using PBKDF2.

        Args:
            password: The password to derive the key from.

        Returns:
            The derived encryption key.
        """
        # Create salt directory if it doesn't exist
        os.makedirs(TOKEN_DIRECTORY, mode=0o700, exist_ok=True)

        # Get or create salt
        if os.path.exists(TOKEN_SALT_FILE):
            with open(TOKEN_SALT_FILE, 'rb') as f:
                salt = f.read()
        else:
            # Generate a random salt and save it
            salt = os.urandom(16)
            with open(TOKEN_SALT_FILE, 'wb') as f:
                f.write(salt)
            if os.name != 'nt':
                os.chmod(TOKEN_SALT_FILE, 0o600)

        # Create a key derivation function
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )

        # Derive a key from the password and machine ID (for machine binding)
        # This ensures the token can only be decrypted on this machine
        combined_password = password.encode() + BLENDER_MACHINE_ID
        key = base64.urlsafe_b64encode(kdf.derive(combined_password))

        return key

    def _encrypt_token_data(self, token_data: Dict[str, Any], password: str) -> bytes:
        """Encrypt token data with the given password.

        Args:
            token_data: The token data to encrypt.
            password: The password to encrypt with.

        Returns:
            The encrypted token data.
        """
        # Generate encryption key
        key = self._generate_encryption_key(password)

        # Create a Fernet cipher
        cipher = Fernet(key)

        # Convert token data to JSON string
        token_json = json.dumps(token_data).encode()

        # Encrypt the token data
        encrypted_data = cipher.encrypt(token_json)

        return encrypted_data

    def _decrypt_token_data(self, encrypted_data: bytes, password: str) -> Optional[Dict[str, Any]]:
        """Decrypt token data with the given password.

        Args:
            encrypted_data: The encrypted token data.
            password: The password to decrypt with.

        Returns:
            The decrypted token data, or None if decryption fails.
        """
        try:
            # Generate decryption key
            key = self._generate_encryption_key(password)

            # Create a Fernet cipher
            cipher = Fernet(key)

            # Decrypt the token data
            decrypted_data = cipher.decrypt(encrypted_data)

            # Parse the JSON data
            token_data = json.loads(decrypted_data.decode())

            return token_data
        except Exception:
            # If decryption fails, return None
            return None

    def _save_token(self, password: str) -> bool:
        """Save the current token to disk, encrypted with the given password.

        Args:
            password: The password to encrypt the token with.

        Returns:
            True if the token was saved successfully, False otherwise.
        """
        if not self.token:
            return False

        # Create token directory if it doesn't exist
        os.makedirs(TOKEN_DIRECTORY, exist_ok=True)

        # Create token data
        token_data = {
            'token': self.token,
            'user_info': self.user_info,
            'companies': self.companies,
            'expiry': self.token_expiry.isoformat() if self.token_expiry else None,
        }

        # Encrypt token data
        encrypted_data = self._encrypt_token_data(token_data, password)

        # Save encrypted data to file
        try:
            with open(TOKEN_FILE, 'wb') as f:
                f.write(encrypted_data)
            if os.name != 'nt':
                os.chmod(TOKEN_FILE, 0o600)
            return True
        except Exception:
            return False

    def _load_token(self) -> bool:
        """Load the saved token from disk.

        This method doesn't actually load the token, as it requires the password.
        It just checks if a token file exists.

        Returns:
            True if a token file exists, False otherwise.
        """
        return os.path.exists(TOKEN_FILE)

    def has_saved_token(self) -> bool:
        """Check if there is a saved token.

        Returns:
            True if a token file exists, False otherwise.
        """
        return os.path.exists(TOKEN_FILE)

    def unlock_saved_token(self, password: str) -> bool:
        """Unlock the saved token with the given password.

        Args:
            password: The password to decrypt the token with.

        Returns:
            True if the token was unlocked successfully, False otherwise.
        """
        import time

        # Rate limit: max 5 attempts, then 60-second lockout
        if self._unlock_lockout_until and time.time() < self._unlock_lockout_until:
            logger.warning("Token unlock locked out for %d more seconds",
                           int(self._unlock_lockout_until - time.time()))
            return False

        if not os.path.exists(TOKEN_FILE):
            return False

        try:
            # Read encrypted data from file
            with open(TOKEN_FILE, 'rb') as f:
                encrypted_data = f.read()

            # Decrypt token data
            token_data = self._decrypt_token_data(encrypted_data, password)

            if not token_data:
                self._unlock_attempts += 1
                if self._unlock_attempts >= 5:
                    self._unlock_lockout_until = time.time() + 60
                    self._unlock_attempts = 0
                    logger.warning("Token unlock locked out after 5 failed attempts")
                return False

            # Reset attempts on success
            self._unlock_attempts = 0
            self._unlock_lockout_until = None

            # Set token data
            self.token = token_data.get('token')
            self.user_info = token_data.get('user_info')
            self.companies = token_data.get('companies', [])

            # Parse expiry date
            expiry_str = token_data.get('expiry')
            if expiry_str:
                self.token_expiry = datetime.datetime.fromisoformat(expiry_str)
            else:
                # If no expiry date, set to 5 days from now (default Knox TTL)
                self.token_expiry = datetime.datetime.now() + datetime.timedelta(days=5)

            return True
        except Exception:
            return False

    def login(self, username: str, password: str, save_token: bool = False,
              token_password: Optional[str] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Log in to the geoDB API.

        Args:
            username: The username to log in with.
            password: The password to log in with.
            save_token: Whether to save the token for later use.
            token_password: The password to encrypt the token with, if saving.

        Returns:
            A tuple of (success, message, extra_data).
            - If 2FA is required, success=False, message contains info, and extra_data
              contains {'requires_2fa': True, 'session_token': ..., 'has_recovery_email': ...}
            - Otherwise extra_data is None.
        """
        logger.debug("Login attempt")
        logger.debug("API URL: %s", self.token_url)
        logger.debug("Save token: %s", save_token)

        # Store credentials temporarily for use after 2FA verification
        self._pending_save_token = save_token
        self._pending_token_password = token_password

        try:
            # Prepare login data
            login_data = {
                'username': username,
                'password': password,
            }

            # Send login request
            logger.debug("Sending login request")
            response = self.session.post(
                self.token_url,
                json=login_data,
                headers={'Content-Type': 'application/json'},
                timeout=10.0,
                verify=not self.use_dev_server,
            )

            logger.debug("Response status: %s", response.status_code)

            # Check if login was successful
            if response.status_code == 200:
                # Parse response data
                data = response.json()

                # Check if 2FA is required
                if data.get('requires_2fa'):
                    logger.debug("2FA required")
                    # Store 2FA session data
                    self.pending_2fa_session = {
                        'session_token': data.get('session_token'),
                        'user_id': data.get('user_id'),
                        'has_recovery_email': data.get('has_recovery_email', False),
                    }
                    return False, "Two-factor authentication required.", {
                        'requires_2fa': True,
                        'session_token': data.get('session_token'),
                        'has_recovery_email': data.get('has_recovery_email', False),
                    }

                # No 2FA required - proceed with normal login
                self.token = data.get('token')
                self.user_info = data.get('user')
                self.companies = data.get('companies', [])

                logger.debug("Token received: [REDACTED]")
                logger.debug("Companies: %d", len(self.companies) if self.companies else 0)

                # Set token expiry (use server-provided or default to 30 days)
                expiry_str = data.get('expiry')
                if expiry_str:
                    try:
                        self.token_expiry = datetime.datetime.fromisoformat(
                            expiry_str.replace('Z', '+00:00')
                        )
                    except (ValueError, AttributeError):
                        self.token_expiry = datetime.datetime.now() + datetime.timedelta(days=30)
                else:
                    self.token_expiry = datetime.datetime.now() + datetime.timedelta(days=30)

                # Save token if requested
                if save_token and token_password:
                    if not self._save_token(token_password):
                        logger.warning("Failed to save token")
                        return True, "Logged in successfully, but failed to save token.", None

                # Clear pending credentials
                self._pending_save_token = False
                self._pending_token_password = None

                self._update_authorized_scope()

                logger.debug("Login successful")
                return True, "Logged in successfully.", None
            else:
                # Login failed
                logger.debug("Login failed: HTTP %s", response.status_code)
                try:
                    error_data = response.json()
                    error_msg = error_data.get('detail', error_data)
                except:
                    error_msg = response.text or 'Unknown error'
                logger.debug("Login failed")
                return False, f"Login failed: {error_msg}", None
        except requests.RequestException as e:
            # Network error
            logger.error("Network error during login: %s", type(e).__name__)
            logger.debug("Login network error details", exc_info=True)
            return False, f"Network error: {str(e)}", None
        except Exception as e:
            # Other error
            logger.error("Unexpected error during login: %s", type(e).__name__)
            logger.debug("Login unexpected error details", exc_info=True)
            return False, f"Error: {str(e)}", None

    def verify_2fa(self, code: str) -> Tuple[bool, str]:
        """Verify 2FA code and complete login.

        Args:
            code: The 6-digit TOTP code from the authenticator app.

        Returns:
            A tuple of (success, message).
        """
        if not self.pending_2fa_session:
            return False, "No pending 2FA session. Please log in again."

        session_token = self.pending_2fa_session.get('session_token')
        if not session_token:
            return False, "Invalid 2FA session. Please log in again."

        logger.debug("2FA verification")
        logger.debug("API URL: %s", self.verify_2fa_url)

        try:
            # Send 2FA verification request
            response = self.session.post(
                self.verify_2fa_url,
                json={
                    'session_token': session_token,
                    'code': code,
                },
                headers={'Content-Type': 'application/json'},
                timeout=10.0,
                verify=not self.use_dev_server,
            )

            logger.debug("Response status: %s", response.status_code)

            if response.status_code == 200:
                data = response.json()
                logger.debug("2FA verification successful")

                # Set token data
                self.token = data.get('token')
                self.companies = data.get('companies', [])

                # Set token expiry
                expiry_str = data.get('expiry')
                if expiry_str:
                    try:
                        self.token_expiry = datetime.datetime.fromisoformat(
                            expiry_str.replace('Z', '+00:00')
                        )
                    except (ValueError, AttributeError):
                        self.token_expiry = datetime.datetime.now() + datetime.timedelta(days=30)
                else:
                    self.token_expiry = datetime.datetime.now() + datetime.timedelta(days=30)

                # Clear 2FA session
                self.pending_2fa_session = None

                # Save token if originally requested
                if getattr(self, '_pending_save_token', False) and getattr(self, '_pending_token_password', None):
                    if not self._save_token(self._pending_token_password):
                        logger.warning("Failed to save token")
                        self._pending_save_token = False
                        self._pending_token_password = None
                        return True, "Logged in successfully, but failed to save token."

                # Clear pending credentials
                self._pending_save_token = False
                self._pending_token_password = None

                self._update_authorized_scope()

                logger.debug("2FA verification complete")
                return True, "Logged in successfully."
            else:
                # Verification failed
                logger.debug("2FA verification failed: HTTP %s", response.status_code)
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', error_data.get('detail', 'Invalid code'))
                except:
                    error_msg = 'Invalid code'
                logger.debug("2FA verification failed")
                return False, error_msg
        except requests.RequestException as e:
            logger.error("Network error during 2FA verification: %s", type(e).__name__)
            return False, f"Network error: {str(e)}"
        except Exception as e:
            logger.error("Error during 2FA verification: %s", type(e).__name__)
            return False, f"Error: {str(e)}"

    def request_2fa_recovery(self) -> Tuple[bool, str, Optional[str]]:
        """Request a recovery code to be sent to the user's recovery email.

        Returns:
            A tuple of (success, message, masked_email).
            masked_email is the partially masked recovery email address (e.g., j***@example.com)
        """
        if not self.pending_2fa_session:
            return False, "No pending 2FA session. Please log in again.", None

        session_token = self.pending_2fa_session.get('session_token')
        if not session_token:
            return False, "Invalid 2FA session. Please log in again.", None

        logger.debug("2FA recovery request")
        logger.debug("API URL: %s", self.request_2fa_recovery_url)

        try:
            response = self.session.post(
                self.request_2fa_recovery_url,
                json={'session_token': session_token},
                headers={'Content-Type': 'application/json'},
                timeout=10.0,
                verify=not self.use_dev_server,
            )

            logger.debug("Response status: %s", response.status_code)

            if response.status_code == 200:
                data = response.json()
                masked_email = data.get('recovery_email_masked', '')
                logger.debug("Recovery code sent successfully")
                return True, data.get('message', 'Recovery code sent'), masked_email
            else:
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', error_data.get('detail', 'Failed to send recovery code'))
                except:
                    error_msg = 'Failed to send recovery code'
                return False, error_msg, None
        except requests.RequestException as e:
            return False, f"Network error: {str(e)}", None
        except Exception as e:
            return False, f"Error: {str(e)}", None

    def verify_2fa_recovery(self, recovery_code: str) -> Tuple[bool, str]:
        """Verify recovery code and complete login.

        Args:
            recovery_code: The 6-digit recovery code sent to the user's email.

        Returns:
            A tuple of (success, message).
        """
        if not self.pending_2fa_session:
            return False, "No pending 2FA session. Please log in again."

        session_token = self.pending_2fa_session.get('session_token')
        if not session_token:
            return False, "Invalid 2FA session. Please log in again."

        logger.debug("2FA recovery verification")
        logger.debug("API URL: %s", self.verify_2fa_recovery_url)

        try:
            response = self.session.post(
                self.verify_2fa_recovery_url,
                json={
                    'session_token': session_token,
                    'recovery_code': recovery_code,
                },
                headers={'Content-Type': 'application/json'},
                timeout=10.0,
                verify=not self.use_dev_server,
            )

            logger.debug("Response status: %s", response.status_code)

            if response.status_code == 200:
                data = response.json()
                logger.debug("Recovery verification successful")

                # Set token data
                self.token = data.get('token')
                self.companies = data.get('companies', [])

                # Set token expiry
                expiry_str = data.get('expiry')
                if expiry_str:
                    try:
                        self.token_expiry = datetime.datetime.fromisoformat(
                            expiry_str.replace('Z', '+00:00')
                        )
                    except (ValueError, AttributeError):
                        self.token_expiry = datetime.datetime.now() + datetime.timedelta(days=30)
                else:
                    self.token_expiry = datetime.datetime.now() + datetime.timedelta(days=30)

                # Clear 2FA session
                self.pending_2fa_session = None

                # Save token if originally requested
                if getattr(self, '_pending_save_token', False) and getattr(self, '_pending_token_password', None):
                    if not self._save_token(self._pending_token_password):
                        logger.warning("Failed to save token")
                        self._pending_save_token = False
                        self._pending_token_password = None
                        return True, "Logged in successfully, but failed to save token."

                # Clear pending credentials
                self._pending_save_token = False
                self._pending_token_password = None

                self._update_authorized_scope()

                logger.debug("Recovery verification complete")
                return True, "Logged in successfully."
            else:
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', error_data.get('detail', 'Invalid or expired recovery code'))
                except:
                    error_msg = 'Invalid or expired recovery code'
                return False, error_msg
        except requests.RequestException as e:
            return False, f"Network error: {str(e)}"
        except Exception as e:
            return False, f"Error: {str(e)}"

    def cancel_2fa(self):
        """Cancel the pending 2FA session."""
        self.pending_2fa_session = None
        self._pending_save_token = False
        self._pending_token_password = None

    def has_pending_2fa(self) -> bool:
        """Check if there's a pending 2FA verification."""
        return self.pending_2fa_session is not None

    def check_token(self) -> Tuple[bool, str]:
        """Check if the current token is valid.

        Returns:
            A tuple of (valid, message).
        """
        if not self.token:
            return False, "No token available."

        try:
            # Send check token request
            response = self.session.post(
                self.check_token_url,
                headers=self._get_headers(),
                timeout=10.0,
                verify=not self.use_dev_server,
            )

            # Check if token is valid
            if response.status_code == 200:
                # Token is valid - parse response data
                data = response.json()
                logger.debug("check_token response status: %s", response.status_code)
                # Update token expiry time if provided
                if 'expiration_time' in data:
                    try:
                        self.token_expiry = datetime.datetime.fromisoformat(
                            data['expiration_time'].replace('Z', '+00:00')
                        )
                    except (ValueError, AttributeError):
                        pass
                # Store user info if available
                if 'user' in data:
                    self.user_info = data['user']
                    logger.debug("Updated user_info from check_token")
                else:
                    logger.warning("No 'user' field in check_token response")
                # Store companies info if available
                if 'companies' in data:
                    self.companies = data['companies']
                self._update_authorized_scope()
                return True, f"Token is valid. {data.get('remaining_time', '')}"
            else:
                return False, "Token is invalid."
        except requests.RequestException as e:
            # Network error
            return False, f"Network error: {str(e)}"
        except Exception as e:
            # Other error
            return False, f"Error: {str(e)}"

    def logout(self) -> Tuple[bool, str]:
        """Log out from the geoDB API.

        Returns:
            A tuple of (success, message).
        """
        if not self.token:
            return False, "No token available."

        try:
            # Send logout request
            response = self.session.post(
                self.logout_url,
                headers=self._get_headers(),
                timeout=10.0,
                verify=not self.use_dev_server,
            )

            # Check if logout was successful
            if response.status_code == 204:
                # Clear token data
                self.token = None
                self.user_info = None
                self.token_expiry = None

                # Delete token file if it exists
                if os.path.exists(TOKEN_FILE):
                    try:
                        os.remove(TOKEN_FILE)
                    except Exception:
                        pass

                return True, "Logged out successfully."
            else:
                # Logout failed
                error_msg = response.json().get('detail', 'Unknown error')
                return False, f"Logout failed: {error_msg}"
        except requests.RequestException as e:
            # Network error
            return False, f"Network error: {str(e)}"
        except Exception as e:
            # Other error
            return False, f"Error: {str(e)}"

    def is_authenticated(self) -> bool:
        """Check if the client is authenticated.

        Returns:
            True if the client has a token, False otherwise.
        """
        return self.token is not None

    def get_user_info(self) -> Optional[Dict[str, Any]]:
        """Get the current user's information.

        Returns:
            The user information, or None if not authenticated.
        """
        return self.user_info

    def get_token_expiry(self) -> Optional[datetime.datetime]:
        """Get the token expiry date.

        Returns:
            The token expiry date, or None if not authenticated.
        """
        return self.token_expiry

    def set_active_company(self, company_id: int) -> Tuple[bool, str]:
        """Set the user's active company in the app.

        This notifies the server that the user has selected a company,
        which updates their active company across all geoDB apps.

        Args:
            company_id: ID of the company to make active.

        Returns:
            A tuple of (success, message).
        """
        success, result = self.make_request(
            'POST',
            'me/set-active-company/',
            data={'company_id': company_id}
        )
        if success:
            return True, "Active company set successfully."
        else:
            return False, result if isinstance(result, str) else "Failed to set active company."

    def set_active_project(self, project_id: int) -> Tuple[bool, str]:
        """Set the user's active project in the app.

        This notifies the server that the user has selected a project,
        which updates their active project across all geoDB apps.
        The active company is also automatically set to the project's parent company.

        Args:
            project_id: ID of the project to make active.

        Returns:
            A tuple of (success, message).
        """
        success, result = self.make_request(
            'POST',
            'me/set-active-project/',
            data={'project_id': project_id}
        )
        if success:
            return True, "Active project set successfully."
        else:
            return False, result if isinstance(result, str) else "Failed to set active project."

    def make_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None,
                    params: Optional[Dict[str, Any]] = None) -> Tuple[bool, Union[Dict[str, Any], str]]:
        """Make a request to the geoDB API.

        Args:
            method: The HTTP method to use (GET, POST, PUT, PATCH, DELETE).
            endpoint: The API endpoint to request (without the base URL).
            data: The data to send with the request.
            params: The query parameters to include in the request.

        Returns:
            A tuple of (success, response_data_or_error_message).
        """
        if not self.token:
            logger.error("make_request called without token")
            return False, "Not authenticated."

        # Build the full URL
        url = f"{self.base_url}{endpoint.lstrip('/')}"
        logger.debug("API %s %s", method, endpoint)

        import time
        start_time = time.time()

        try:
            # Send the request with timeout using persistent session
            response = self.session.request(
                method,
                url,
                json=data,
                params=params,
                headers=self._get_headers(),
                timeout=60.0,  # 60 second timeout for large datasets
                verify=not self.use_dev_server,
            )

            elapsed_time = time.time() - start_time
            logger.debug("Response status: %s", response.status_code)
            logger.debug("API response time: %.3fs", elapsed_time)

            # Check if the request was successful
            if response.status_code in (200, 201, 204):
                # Parse response data if there is any
                if response.status_code == 204:
                    logger.debug("Request successful")
                    return True, {}
                else:
                    response_data = response.json()
                    logger.debug("Request successful")
                    return True, response_data
            else:
                # Request failed
                logger.debug("Request failed: HTTP %s", response.status_code)
                try:
                    error_data = response.json()
                    error_msg = error_data.get('detail', str(error_data))
                except Exception as e:
                    error_msg = f"HTTP {response.status_code}"
                    logger.debug("Could not parse error JSON")

                return False, f"API request failed: {error_msg}"
        except requests.RequestException as e:
            # Network error
            logger.error("Network error: %s", type(e).__name__)
            logger.debug("Network error details", exc_info=True)
            return False, f"Network error: {str(e)}"
        except Exception as e:
            # Other error
            logger.error("Unexpected error: %s", type(e).__name__)
            logger.debug("Unexpected error details", exc_info=True)
            return False, f"Error: {str(e)}"

    def get_all_paginated(self, endpoint: str, params: Optional[Dict[str, Any]] = None,
                          progress_callback: Optional[Callable[[int, int], None]] = None,
                          limit: int = 100) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Fetch ALL results from a paginated v2 API endpoint by following pagination.

        The v2 API uses LimitOffsetPagination with response format:
        {
            "count": 5000,
            "next": "https://api.geodb.io/api/v2/drill-collars/?limit=100&offset=100",
            "previous": null,
            "results": [...]
        }

        Args:
            endpoint: API endpoint (e.g., 'drill-collars/')
            params: Query parameters (e.g., {'project_id': 123})
            progress_callback: Optional callback(fetched_count, total_count) for progress updates
            limit: Number of results per page (default 100, max 1000)

        Returns:
            Tuple of (success, list_of_all_results)
        """
        if not self.token:
            logger.error("get_all_paginated called without token")
            return False, []

        all_results = []
        params = params.copy() if params else {}
        params['limit'] = min(limit, 1000)  # Respect max limit

        current_offset = 0
        total_count = None

        logger.debug("Paginated fetch: %s", endpoint)

        while True:
            params['offset'] = current_offset
            success, data = self.make_request('GET', endpoint, params=params)

            if not success:
                logger.debug("Pagination failed at offset %d", current_offset)
                return False, all_results

            # Handle paginated response (v2 API format)
            if isinstance(data, dict) and 'results' in data:
                results = data.get('results', [])
                all_results.extend(results)

                # Get total count on first request
                if total_count is None:
                    total_count = data.get('count', len(results))
                    logger.debug("Total records to fetch: %d", total_count)

                # Progress callback
                if progress_callback and total_count:
                    progress_callback(len(all_results), total_count)

                # Log progress
                logger.debug("Fetched %d/%d records", len(all_results), total_count)

                # Check if more pages exist
                if data.get('next') is None:
                    break

                current_offset += len(results)

                # Safety check to prevent infinite loops
                if len(results) == 0:
                    logger.debug("Empty page received, stopping pagination")
                    break
            else:
                # Non-paginated response (shouldn't happen with v2, but handle gracefully)
                if isinstance(data, list):
                    all_results.extend(data)
                    logger.debug("Received non-paginated list with %d items", len(data))
                break

        logger.debug("Pagination complete: %d total records fetched", len(all_results))
        return True, all_results

    def get_all_paginated_with_sync(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        limit: int = 100
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Fetch ALL results from a paginated v2 API endpoint with sync metadata.

        Similar to get_all_paginated() but also returns deleted_ids and sync_timestamp
        for deletion sync support. This enables clients to detect records that were
        soft-deleted on the server and remove them from local cache/scene.

        The v2 API response format with sync support:
        {
            "count": 5000,
            "next": "...",
            "previous": null,
            "results": [...],
            "deleted_ids": [45, 67, 89, 123],  // IDs of soft-deleted records
            "deleted_since_applied": "2026-01-10T15:30:00Z",  // Echo of filter param
            "sync_timestamp": "2026-01-12T10:00:00Z"  // Use for next sync
        }

        Args:
            endpoint: API endpoint (e.g., 'drill-collars/')
            params: Query parameters (e.g., {'project_id': 123, 'deleted_since': '...'})
            progress_callback: Optional callback(fetched_count, total_count) for progress
            limit: Number of results per page (default 100, max 1000)

        Returns:
            Tuple of (success, result_dict) where result_dict contains:
                - results: List of all active records
                - deleted_ids: List of soft-deleted record IDs (empty if not supported)
                - sync_timestamp: ISO timestamp for next sync (None if not supported)
                - count: Total active record count
        """
        if not self.token:
            logger.error("get_all_paginated_with_sync called without token")
            return False, {'results': [], 'deleted_ids': [], 'sync_timestamp': None, 'count': 0}

        all_results = []
        all_deleted_ids = set()  # Use set to handle duplicates across pages
        sync_timestamp = None
        params = params.copy() if params else {}
        params['limit'] = min(limit, 1000)

        current_offset = 0
        total_count = None

        logger.debug("Paginated fetch with sync: %s", endpoint)
        if params.get('deleted_since'):
            logger.debug("Incremental sync from: %s", params.get('deleted_since'))

        while True:
            params['offset'] = current_offset
            success, data = self.make_request('GET', endpoint, params=params)

            if not success:
                logger.debug("Pagination failed at offset %d", current_offset)
                return False, {
                    'results': all_results,
                    'deleted_ids': list(all_deleted_ids),
                    'sync_timestamp': sync_timestamp,
                    'count': len(all_results)
                }

            # Handle paginated response (v2 API format)
            if isinstance(data, dict) and 'results' in data:
                results = data.get('results', [])
                all_results.extend(results)

                # Collect sync metadata (new fields - gracefully handle if missing)
                deleted_ids_page = data.get('deleted_ids', [])
                if deleted_ids_page:
                    all_deleted_ids.update(deleted_ids_page)

                # Use the latest sync_timestamp (should be same across pages)
                page_sync_timestamp = data.get('sync_timestamp')
                if page_sync_timestamp:
                    sync_timestamp = page_sync_timestamp

                # Get total count on first request
                if total_count is None:
                    total_count = data.get('count', len(results))
                    logger.debug("Total records to fetch: %d", total_count)

                # Progress callback
                if progress_callback and total_count:
                    progress_callback(len(all_results), total_count)

                # Log progress
                logger.debug("Fetched %d/%d records, deleted_ids so far: %d",
                             len(all_results), total_count, len(all_deleted_ids))

                # Check if more pages exist
                if data.get('next') is None:
                    break

                current_offset += len(results)

                # Safety check to prevent infinite loops
                if len(results) == 0:
                    logger.debug("Empty page received, stopping pagination")
                    break
            else:
                # Non-paginated response (shouldn't happen with v2)
                if isinstance(data, list):
                    all_results.extend(data)
                break

        logger.debug("Pagination complete: %d records, %d deleted_ids",
                      len(all_results), len(all_deleted_ids))

        return True, {
            'results': all_results,
            'deleted_ids': list(all_deleted_ids),
            'sync_timestamp': sync_timestamp,
            'count': len(all_results)
        }
