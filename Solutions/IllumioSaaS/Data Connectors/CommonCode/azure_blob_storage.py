from azure.storage.blob import ContainerClient
import os
import gzip
import logging
from io import BytesIO
import json


class AzureBlobStorage:
    def __init__(self, blob_url):
        storage_account = os.environ.get("AzureWebJobsStorage")

        # determine whether url is audit event or flow summaries
        if "auditable" in blob_url:
            container = os.environ.get("StorageContainer", "auditable-pcelogs")
        else:
            container = os.environ.get("StorageContainer", "networktraffic-pcelogs")
        self.container_client = ContainerClient.from_connection_string(
            conn_str=storage_account, container_name=container
        )

    def load(self, file_name: str) -> dict:
        blob_client = self.container_client.get_blob_client(blob=file_name)
        try:
            event_data = []
            blob_data = blob_client.download_blob().readall()

            with gzip.GzipFile(fileobj=BytesIO(blob_data)) as gz:
                decompressed_data = gz.read()

                for line in decompressed_data.decode("utf-8").splitlines():
                    try:
                        if line:
                            json_obj = json.loads(line)
                            event_data.append(json_obj)
                    except json.JSONDecodeError as e:
                        print(f"Failed to parse line: {line}")
                        print(f"Error: {e}")
            logging.info("Count of events processed is %s", len(event_data))
            return event_data
        except Exception as e:
            logging.error(f"Error reading blob {file_name}: {str(e)}")
            return {}
