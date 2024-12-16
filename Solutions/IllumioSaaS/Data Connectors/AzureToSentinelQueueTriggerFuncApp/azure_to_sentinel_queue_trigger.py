import json
from aiobotocore.session import get_session
import logging
import azure.functions as func
import urllib.parse
import aiohttp
from ..CommonCode.sentinel_connector import AzureSentinelConnectorAsync
from ..CommonCode.azure_blob_storage import AzureBlobStorage
from ..CommonCode.constants import (
    AZURE_TENANT_ID,
    AZURE_CLIENT_ID,
    AZURE_CLIENT_SECRET,
    DCE_ENDPOINT,
    DCR_ID,
    FLOW_LOGS_CUSTOM_TABLE,
    AUDIT_LOGS_CUSTOM_TABLE,
    LOGS_TO_CONSUME,
    AWS_KEY,
    AWS_SECRET,
    AWS_REGION_NAME,
    LINE_SEPARATOR,
    ALL_TRAFFIC,
    FLOW_EVENTS,
    AUDIT_EVENTS,
)
from ..CommonCode.helper import skip_processing_file, check_if_script_runs_too_long


async def _generate_sentinel_connectors(session):
    stream_names = []
    sentinel_connectors = {}
    if LOGS_TO_CONSUME == ALL_TRAFFIC:
        stream_names.append(FLOW_LOGS_CUSTOM_TABLE)
        stream_names.append(AUDIT_LOGS_CUSTOM_TABLE)

    elif LOGS_TO_CONSUME == AUDIT_EVENTS:
        stream_names.append(AUDIT_LOGS_CUSTOM_TABLE)
    else:
        stream_names.append(FLOW_LOGS_CUSTOM_TABLE)

    for stream in stream_names:
        sentinel_connectors[stream] = AzureSentinelConnectorAsync(
            session,
            DCE_ENDPOINT,
            DCR_ID,
            stream,
            AZURE_CLIENT_ID,
            AZURE_CLIENT_SECRET,
            AZURE_TENANT_ID,
        )

    return sentinel_connectors


async def main(msg: func.QueueMessage):

    try:
        total_events = 0
        accumulated_file_size = 0
        # stores the connection objects that can be reused when uploading events to specific tables
        sentinel_connectors = {}
        # initialize sentinel_connectors
        async with aiohttp.ClientSession() as session:
            sentinel_connectors = await _generate_sentinel_connectors(session)

        result = {"id": msg.id, "body": msg.get_body()}
        # body should be a list of dicts, where each dict has link, bucket_name, sqs_message_id
        body = json.loads(result["body"].decode("ascii").replace("'", '"'))

        msgType = body["type"]
        if msgType == "Microsoft.Storage.BlobCreated":
            urlToProcess = body["data"]["url"]
            azure_client = AzureBlobStorage(urlToProcess)
            fileName = urlToProcess.split("/")[-1]
            if skip_processing_file(fileName):
                return
            events = azure_client.load(fileName)
            logging.info("Events processed in %s is  %s", fileName, len(events))

    except ValueError:
        pass
    else:
        if urlToProcess:
            sqs_ids_seen_so_far += 1
            stream_name = (
                AUDIT_LOGS_CUSTOM_TABLE
                if "auditable" in urlToProcess
                else FLOW_LOGS_CUSTOM_TABLE
            )

            # file_stats = {
            #     "Trigger": "Queue",
            #     "stream_name": stream_name,
            #     "Type": "file_stats",
            #     "link": link,
            #     "bucket": bucket,
            #     "sqs_message_id": messageId,
            #     "file_size_bytes": file_size,
            # }
            # logging.info(json.dumps(file_stats))

            async with aiohttp.ClientSession() as session:
                sentinel_connector = sentinel_connectors[stream_name]
                for event in events:
                    await sentinel_connector.send(event)

            for connector in sentinel_connectors.keys():
                await sentinel_connectors[connector].flush()

            event_stats = {
                "Trigger": "Queue",
                "Type": "event_stats",
                "total_events": total_events,
                "sqs_ids_seen_so_far": sqs_ids_seen_so_far,
                "aggregated_file_size": accumulated_file_size,
            }
            logging.info(json.dumps(event_stats))
