import os
import boto3
import json
from typing import Optional, AsyncIterator
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

class DynamoDBSaver(BaseCheckpointSaver):
    def __init__(
        self, 
        table_name: str, 
        region_name: Optional[str] = None,
        serde: Optional[SerializerProtocol] = None
    ):
        super().__init__(serde=serde or JsonPlusSerializer())
        endpoint_url = os.environ.get("DYNAMODB_ENDPOINT_URL") or os.environ.get(
            "AWS_ENDPOINT_URL_DYNAMODB"
        )
        resource_kwargs = {}
        if region_name is not None:
            resource_kwargs["region_name"] = region_name
        if endpoint_url:
            resource_kwargs["endpoint_url"] = endpoint_url
        self.dynamodb = boto3.resource("dynamodb", **resource_kwargs)
        self.table = self.dynamodb.Table(table_name)

    def get_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id", "latest")

        if checkpoint_id == "latest":
            # Filter to ensure we only get actual checkpoints, not writes
            response = self.table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key('thread_id').eq(thread_id),
                FilterExpression=boto3.dynamodb.conditions.Attr('type').eq('checkpoint'),
                ScanIndexForward=False,
                Limit=1
            )
            items = response.get('Items')
            if not items:
                # Try fallback for older records without 'type' field
                response = self.table.query(
                    KeyConditionExpression=boto3.dynamodb.conditions.Key('thread_id').eq(thread_id),
                    ScanIndexForward=False
                )
                for itm in response.get('Items', []):
                    if 'checkpoint' in itm:
                        item = itm
                        break
                else:
                    return None
            else:
                item = items[0]
        else:
            response = self.table.get_item(
                Key={'thread_id': thread_id, 'checkpoint_id': checkpoint_id}
            )
            item = response.get('Item')
            if not item or 'checkpoint' not in item:
                return None

        # Helper to handle DynamoDB Binary objects
        def _to_bytes(data):
            if hasattr(data, "value"):
                return data.value
            return data

        # The new loads_typed requires (content_type, data)
        checkpoint_data = _to_bytes(item['checkpoint'])
        checkpoint_type = item.get('checkpoint_type', 'json')
        metadata_data = _to_bytes(item['metadata'])
        metadata_type = item.get('metadata_type', 'json')

        checkpoint = self.serde.loads_typed((checkpoint_type, checkpoint_data))
        metadata = self.serde.loads_typed((metadata_type, metadata_data))
        parent_id = item.get('parent_id')

        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config={"configurable": {"thread_id": thread_id, "checkpoint_id": parent_id}} if parent_id else None
        )

    def list(self, config: dict, *, filter: Optional[dict] = None, before: Optional[dict] = None, limit: Optional[int] = None) -> AsyncIterator[CheckpointTuple]:
        # Implementation for listing checkpoints - must be an async generator if we want it to be AsyncIterator
        # or we keep it sync and use it via alist
        thread_id = config["configurable"]["thread_id"]
        response = self.table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('thread_id').eq(thread_id),
            FilterExpression=boto3.dynamodb.conditions.Attr('type').eq('checkpoint'),
            ScanIndexForward=False,
            Limit=limit or 10
        )
        
        def _to_bytes(data):
            if hasattr(data, "value"):
                return data.value
            return data

        for item in response.get('Items', []):
            checkpoint_type = item.get('checkpoint_type', 'json')
            metadata_type = item.get('metadata_type', 'json')
            
            yield CheckpointTuple(
                config={"configurable": {"thread_id": thread_id, "checkpoint_id": item['checkpoint_id']}},
                checkpoint=self.serde.loads_typed((checkpoint_type, _to_bytes(item['checkpoint']))),
                metadata=self.serde.loads_typed((metadata_type, _to_bytes(item['metadata']))),
                parent_config={"configurable": {"thread_id": thread_id, "checkpoint_id": item.get('parent_id')}} if item.get('parent_id') else None
            )

    async def aget_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        import asyncio
        return await asyncio.to_thread(self.get_tuple, config)

    async def alist(self, config: dict, *, filter: Optional[dict] = None, before: Optional[dict] = None, limit: Optional[int] = None) -> AsyncIterator[CheckpointTuple]:
        import asyncio
        # We wrap the sync generator to make it an async iterator
        sync_gen = self.list(config, filter=filter, before=before, limit=limit)
        while True:
            def _get_next():
                try:
                    return next(sync_gen)
                except StopIteration:
                    return StopIteration
            
            item = await asyncio.to_thread(_get_next)
            if item is StopIteration:
                break
            yield item

    async def aput(self, config: dict, checkpoint: Checkpoint, metadata: CheckpointMetadata, new_versions: dict) -> dict:
        import asyncio
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config: dict, writes: list, task_id: str) -> None:
        import asyncio
        return await asyncio.to_thread(self.put_writes, config, writes, task_id)

    def put(self, config: dict, checkpoint: Checkpoint, metadata: CheckpointMetadata, new_versions: dict) -> dict:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = checkpoint["id"]
        
        # Get parent_id from config if it exists
        parent_id = config["configurable"].get("checkpoint_id")

        # dumps_typed returns (type_string, bytes_data)
        checkpoint_type, checkpoint_bytes = self.serde.dumps_typed(checkpoint)
        metadata_type, metadata_bytes = self.serde.dumps_typed(metadata)

        self.table.put_item(
            Item={
                'thread_id': thread_id,
                'checkpoint_id': checkpoint_id,
                'checkpoint': checkpoint_bytes,
                'checkpoint_type': checkpoint_type,
                'metadata': metadata_bytes,
                'metadata_type': metadata_type,
                'parent_id': parent_id,
                'timestamp': checkpoint.get('ts'),
                'type': 'checkpoint'
            }
        )
        return {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}

    def put_writes(self, config: dict, writes: list, task_id: str) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"]["checkpoint_id"]
        
        # We store writes with a special prefix in the checkpoint_id to keep the same table
        # Format: writes#{task_id}
        for idx, (channel, value) in enumerate(writes):
            write_type, write_bytes = self.serde.dumps_typed(value)
            self.table.put_item(
                Item={
                    'thread_id': thread_id,
                    'checkpoint_id': f"write#{checkpoint_id}#{task_id}#{idx}",
                    'channel': channel,
                    'value': write_bytes,
                    'type': write_type,
                    'item_type': 'write'
                }
            )


# --- Token Limit Tracking ---
_LOCAL_USER_TOKENS = {}

def get_user_tokens(user_id: str) -> int:
    table_name = os.getenv("DYNAMODB_TABLE", "AI_Chat_Sessions")
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME") or os.getenv("USE_DYNAMODB"):
        import boto3
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)
        try:
            res = table.get_item(Key={"thread_id": f"user_tokens#{user_id}", "checkpoint_id": "tokens"})
            if "Item" in res:
                return int(res["Item"].get("tokens_used", 0))
        except Exception as e:
            print(f"DynamoDB get_user_tokens error: {e}")
            pass
    return _LOCAL_USER_TOKENS.get(user_id, 0)

def add_user_tokens(user_id: str, tokens: int) -> int:
    table_name = os.getenv("DYNAMODB_TABLE", "AI_Chat_Sessions")
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME") or os.getenv("USE_DYNAMODB"):
        import boto3
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)
        try:
            res = table.update_item(
                Key={"thread_id": f"user_tokens#{user_id}", "checkpoint_id": "tokens"},
                UpdateExpression="ADD tokens_used :t",
                ExpressionAttributeValues={":t": tokens},
                ReturnValues="UPDATED_NEW"
            )
            return int(res["Attributes"]["tokens_used"])
        except Exception as e:
            print(f"DynamoDB add_user_tokens error: {e}")
            pass
    
    _LOCAL_USER_TOKENS[user_id] = _LOCAL_USER_TOKENS.get(user_id, 0) + tokens
    return _LOCAL_USER_TOKENS[user_id]
