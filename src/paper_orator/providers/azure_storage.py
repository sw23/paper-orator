# Copyright (c) 2025 Spencer Williams
# Licensed under the MIT License. See LICENSE file in the project root.

"""Azure Blob Storage provider for file uploads."""

from __future__ import annotations

import logging

from azure.storage.blob import BlobServiceClient, ContentSettings

from paper_orator.providers.base import StorageUploader

logger = logging.getLogger(__name__)


class AzureBlobUploader(StorageUploader):
    """Uploads files to Azure Blob Storage."""

    def __init__(self, config: dict):
        """Initialize with Azure Storage credentials.

        Args:
            config: Dict with keys 'connection_string' and 'container_name'.
        """
        self.connection_string = config["connection_string"]
        self.container_name = config["container_name"]

    def upload(self, file_path: str, blob_name: str) -> str | None:
        try:
            blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
            container_client = blob_service_client.get_container_client(self.container_name)

            try:
                container_client.get_container_properties()
            except Exception:
                logger.error(f"Container does not exist: {self.container_name}")
                return None

            content_settings = None
            if blob_name.endswith(".xml"):
                content_settings = ContentSettings(
                    content_type="application/rss+xml",
                    cache_control="no-cache, max-age=0",
                )
            elif blob_name.endswith(".mp3"):
                content_settings = ContentSettings(
                    content_type="audio/mpeg",
                    cache_control="public, max-age=3600",
                )

            with open(file_path, "rb") as data:
                blob_client = container_client.upload_blob(
                    name=blob_name,
                    data=data,
                    overwrite=True,
                    content_settings=content_settings,
                )

            blob_url = blob_client.url
            logger.info(f"Uploaded to Azure Storage: {blob_url}")

            blob_properties = blob_client.get_blob_properties()
            logger.info(f"Blob size: {blob_properties.size} bytes")

            return blob_url

        except Exception as e:
            logger.error(f"Failed to upload to Azure Storage: {e}")
            return None
