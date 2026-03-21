import os
import uuid
import hmac
import hashlib
import time
from typing import Dict, Any
from app.core.config import settings

class StorageService:
    def __init__(self, upload_dir: str = "uploads"):
        self.upload_dir = upload_dir
        if not os.path.exists(self.upload_dir):
            os.makedirs(self.upload_dir)

    def generate_signed_params(self, folder: str = "general", expires_in: int = 3600) -> Dict[str, Any]:
        """
        Generates signed parameters for a Cloudinary-style upload.
        """
        timestamp = int(time.time())
        
        # Message to sign: folder and timestamp (alphabetical order usually)
        message = f"folder={folder}&timestamp={timestamp}"
        
        signature = hmac.new(
            settings.SECRET_KEY.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return {
            "signature": signature,
            "timestamp": timestamp,
            "folder": folder,
            "api_key": "mock-api-key-123" # Simulating a public API key
        }

    def verify_signature(self, folder: str, timestamp: int, signature: str, max_age: int = 3600) -> bool:
        """
        Verifies the signature against the provided parameters.
        """
        # Check if timestamp is too old
        if time.time() - timestamp > max_age:
            return False
            
        message = f"folder={folder}&timestamp={timestamp}"
        expected_signature = hmac.new(
            settings.SECRET_KEY.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)

    def save_file(self, folder: str, filename: str, content: bytes) -> str:
        # Create folder if it doesn't exist
        target_dir = os.path.join(self.upload_dir, folder)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        # Generate generic name
        ext = os.path.splitext(filename)[1]
        unique_name = f"{uuid.uuid4()}{ext}"
        
        file_path = os.path.join(target_dir, unique_name)
        with open(file_path, "wb") as f:
            f.write(content)
            
        return f"{folder}/{unique_name}"

storage_service = StorageService()
