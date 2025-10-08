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
from typing import Dict, Any, Optional, Tuple, Union

import bpy
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# API Constants
API_BASE_URL = "https://geodb.io/api/v1/"
API_TOKEN_URL = f"{API_BASE_URL}api-token-auth/"
API_CHECK_TOKEN_URL = f"{API_BASE_URL}check-token/"
API_LOGOUT_URL = f"{API_BASE_URL}api-logout/"

# Local development settings (can be toggled in preferences)
DEV_API_BASE_URL = "http://localhost:8000/api/v1/"
DEV_API_TOKEN_URL = f"{DEV_API_BASE_URL}api-token-auth/"
DEV_API_CHECK_TOKEN_URL = f"{DEV_API_BASE_URL}check-token/"
DEV_API_LOGOUT_URL = f"{DEV_API_BASE_URL}api-logout/"

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
        
        # Create a persistent session for connection pooling
        self.session = requests.Session()
        
        # Set the base URLs based on server choice
        if use_dev_server:
            self.base_url = DEV_API_BASE_URL
            self.token_url = DEV_API_TOKEN_URL
            self.check_token_url = DEV_API_CHECK_TOKEN_URL
            self.logout_url = DEV_API_LOGOUT_URL
        else:
            self.base_url = API_BASE_URL
            self.token_url = API_TOKEN_URL
            self.check_token_url = API_CHECK_TOKEN_URL
            self.logout_url = API_LOGOUT_URL
        
        # Try to load saved token
        self._load_token()
    
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
        os.makedirs(TOKEN_DIRECTORY, exist_ok=True)
        
        # Get or create salt
        if os.path.exists(TOKEN_SALT_FILE):
            with open(TOKEN_SALT_FILE, 'rb') as f:
                salt = f.read()
        else:
            # Generate a random salt and save it
            salt = os.urandom(16)
            with open(TOKEN_SALT_FILE, 'wb') as f:
                f.write(salt)
        
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
        if not os.path.exists(TOKEN_FILE):
            return False
        
        try:
            # Read encrypted data from file
            with open(TOKEN_FILE, 'rb') as f:
                encrypted_data = f.read()
            
            # Decrypt token data
            token_data = self._decrypt_token_data(encrypted_data, password)
            
            if not token_data:
                return False
            
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
              token_password: Optional[str] = None) -> Tuple[bool, str]:
        """Log in to the geoDB API.
        
        Args:
            username: The username to log in with.
            password: The password to log in with.
            save_token: Whether to save the token for later use.
            token_password: The password to encrypt the token with, if saving.
            
        Returns:
            A tuple of (success, message).
        """
        print(f"\n=== geoDB Login Attempt ===")
        print(f"Username: {username}")
        print(f"API URL: {self.token_url}")
        print(f"Save token: {save_token}")
        
        try:
            # Prepare login data
            login_data = {
                'username': username,
                'password': password,
            }
            
            # Send login request
            print("Sending login request...")
            response = self.session.post(
                self.token_url,
                json=login_data,
                headers={'Content-Type': 'application/json'},
                timeout=10.0,
            )
            
            print(f"Response status code: {response.status_code}")
            
            # Check if login was successful
            if response.status_code == 200:
                # Parse response data
                data = response.json()
                print(f"Response data: {data}")
                
                # Set token data
                self.token = data.get('token')
                self.user_info = data.get('user')
                self.companies = data.get('companies', [])
                
                print(f"Token received: {self.token[:20]}..." if self.token else "No token received")
                print(f"User info: {self.user_info}")
                print(f"Companies received: {len(self.companies) if self.companies else 0} companies")
                if self.companies:
                    print(f"Companies list: {[c.get('name', 'Unknown') for c in self.companies]}")
                
                # Set token expiry (5 days from now, default Knox TTL)
                self.token_expiry = datetime.datetime.now() + datetime.timedelta(days=5)
                
                # Save token if requested
                if save_token and token_password:
                    if not self._save_token(token_password):
                        print("WARNING: Failed to save token")
                        return True, "Logged in successfully, but failed to save token."
                
                print("=== Login successful ===\n")
                return True, "Logged in successfully."
            else:
                # Login failed
                print(f"Login failed with status code: {response.status_code}")
                print(f"Response text: {response.text}")
                try:
                    error_data = response.json()
                    error_msg = error_data.get('detail', error_data)
                    print(f"Error data: {error_data}")
                except:
                    error_msg = response.text or 'Unknown error'
                print(f"=== Login failed ===\n")
                return False, f"Login failed: {error_msg}"
        except requests.RequestException as e:
            # Network error
            print(f"Network error during login: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            print(f"=== Login failed (network error) ===\n")
            return False, f"Network error: {str(e)}"
        except Exception as e:
            # Other error
            print(f"Unexpected error during login: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            print(f"=== Login failed (unexpected error) ===\n")
            return False, f"Error: {str(e)}"
    
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
            )
            
            # Check if token is valid
            if response.status_code == 200:
                # Token is valid - parse response data
                data = response.json()
                print(f"check_token response data: {data}")
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
                    print(f"Updated user_info from check_token: {self.user_info}")
                else:
                    print(f"WARNING: No 'user' field in check_token response")
                # Store companies info if available
                if 'companies' in data:
                    self.companies = data['companies']
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
            print("ERROR: make_request called without token")
            return False, "Not authenticated."
        
        # Build the full URL
        url = f"{self.base_url}{endpoint.lstrip('/')}"
        print(f"\n=== API Request ===")
        print(f"Method: {method}")
        print(f"URL: {url}")
        print(f"Data: {data}")
        print(f"Params: {params}")
        
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
                timeout=10.0,  # 10 second timeout
            )
            
            elapsed_time = time.time() - start_time
            print(f"Response status code: {response.status_code}")
            print(f"API Response Time: {elapsed_time:.3f}s")
            
            # Check if the request was successful
            if response.status_code in (200, 201, 204):
                # Parse response data if there is any
                if response.status_code == 204:
                    print("Success: No content (204)")
                    return True, {}
                else:
                    response_data = response.json()
                    print(f"Success: {response_data}")
                    return True, response_data
            else:
                # Request failed
                print(f"Request failed with status {response.status_code}")
                print(f"Response text: {response.text}")
                try:
                    error_data = response.json()
                    error_msg = error_data.get('detail', str(error_data))
                    print(f"Error data: {error_data}")
                except Exception as e:
                    error_msg = f"HTTP {response.status_code}"
                    print(f"Could not parse error JSON: {e}")
                
                return False, f"API request failed: {error_msg}"
        except requests.RequestException as e:
            # Network error
            print(f"Network error: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False, f"Network error: {str(e)}"
        except Exception as e:
            # Other error
            print(f"Unexpected error: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False, f"Error: {str(e)}"