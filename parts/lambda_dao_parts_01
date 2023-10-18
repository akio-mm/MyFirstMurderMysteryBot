import json
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

# dynamodb
dynamodb = boto3.resource('dynamodb')
talk_history = dynamodb.Table('talk_history')
user_table = dynamodb.Table('user_info')

def handle_dynamodb_exception(action, parameters):
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ClientError as e:
                logger.error(f"An error occurred while trying to {action} in DynamoDB.")
                logger.error(f"Error message: {e.response['Error']['Message']}")
                logger.error(f"Error code: {e.response['Error']['Code']}")
                logger.error(f"Parameters: {parameters}")
                return None
            except Exception as e:
                logger.error(f"An unknown error occurred while trying to {action} in DynamoDB.")
                logger.error(f"Error: {e}")
                logger.error(f"Parameters: {parameters}")
                return None
        return wrapper
    return decorator

# user情報を返す、なければNone
@handle_dynamodb_exception('get_user_info', 'user_id parameter')
def get_user_info(user_id):
    response =  user_table.get_item(Key={'user_id': user_id})
     # 'Item'キーがない場合、Noneを返す
    return response.get('Item', None)

# 新しいユーザーを登録する
@handle_dynamodb_exception('put_user_info', 'user_item parameter should be a dictionary containing user_id, limit, count, and CurrentPhase keys.')
def put_user_info(item):
    return user_table.put_item(Item=item)
