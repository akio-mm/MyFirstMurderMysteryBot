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

# 会話履歴を返す
@handle_dynamodb_exception('get_talk_history', 'user_id and count parameters')
def get_talk_history(user_id):
    return talk_history.query(
        KeyConditionExpression=Key('user_id').eq(user_id),
        # 最新ｘ件を取得
        Limit = 15
    )

# 新しい会話履歴を登録する
@handle_dynamodb_exception('put_talk_history', 'talk_history parameter')
def put_talk_history(item):
    return talk_history.put_item(Item=item)

# countをインクリメント(+1)して数値を返す
@handle_dynamodb_exception('increment_count', 'user_id, DynamoDB update operation, checking Attributes in response')
def increment_count(user_id):

    response = user_table.update_item(
        Key={'user_id': user_id},
        UpdateExpression='ADD #count :inc',
        ExpressionAttributeNames={'#count': 'count'},
        ExpressionAttributeValues={':inc': 1},
        ReturnValues="UPDATED_NEW")
    
    # 'Attributes'キーが存在し、その中に'count'キーが存在することを確認
    if 'Attributes' in response and 'count' in response['Attributes']:
        return response['Attributes']['count']
    else:
        logger.error(f"Error: Failed to update count for user_id {user_id}. Attributes or count missing in response.")
        return None

# limitをインクリメント(+1)して数値を返す
@handle_dynamodb_exception('increment_limit', 'user_id, DynamoDB update operation, checking Attributes in response')
def increment_limit(user_id):

    response = user_table.update_item(
        Key={'user_id': user_id},
        UpdateExpression='ADD #limit :inc',
        ExpressionAttributeNames={'#limit': 'limit'},
        ExpressionAttributeValues={':inc': 1},
        ReturnValues="UPDATED_NEW")
    
    # 'Attributes'キーが存在し、その中に'limit'キーが存在することを確認
    if 'Attributes' in response and 'limit' in response['Attributes']:
        return response['Attributes']['limit']
    else:
        logger.error(f"Error: Failed to update limit for user_id {user_id}. Attributes or limit missing in response.")
        return None
        
        

# フェーズに応じたプロンプトを取得
@handle_dynamodb_exception('Failed to get prompt for phase', 'Phase parameter: {phase}')
def get_prompt_for_phase(current_phase):
    # DynamoDB クライアントを初期化（この部分は環境に依存）
    table = dynamodb.Table('Prompts')
    try:
        # フェーズに対応するプロンプトを取得
        response = table.get_item(
            Key={
                'Phase': current_phase
            }
        )
        # プロンプトが存在するか確認
        if 'Item' in response and 'Prompt' in response['Item']:
            return response['Item']['Prompt']
        else:
            # 対応するプロンプトが存在しない場合の処理
            logger.error(f"No prompt found for the phase: {current_phase}")
            return None
    except Exception as e:
        logger.error(f"An error occurred while fetching prompt for phase {current_phase}: {e}")
        return None
   

phase_order = [
    "intro",
    "investigation",
    "reasoning",
    "outro"
]

# フェーズを切り替える関数
@handle_dynamodb_exception('update user phase', "user_id: {user_id}, current_phase: {current_phase}, next_phase: {next_phase}")
def update_user_phase(user_id, current_phase):
    try:
        # 現在のフェーズから次のフェーズを取得
        next_phase_index = phase_order.index(current_phase) + 1
        if next_phase_index >= len(phase_order):
            logger.error(f"Error: No next phase after {current_phase} for user_id {user_id}")
            return None
        next_phase = phase_order[next_phase_index]
    except ValueError:
        logger.error(f"Error: Invalid current_phase {current_phase} for user_id {user_id}")
        return None

    # ユーザーのCurrentPhaseを更新
    response = user_table.update_item(
        Key={'user_id': user_id},
        UpdateExpression='SET #phase = :next_phase',
        ExpressionAttributeNames={'#phase': 'CurrentPhase'},
        ExpressionAttributeValues={':next_phase': next_phase},
        ReturnValues="UPDATED_NEW"
    )
    
    if 'Attributes' in response:
        return response['Attributes']
    else:
        # このエラーメッセージはhandle_dynamodb_exceptionによってログに記録されます。
        return None

# 終了するための関数
@handle_dynamodb_exception('update user phase', "user_id: {user_id}, current_phase: {current_phase}, next_phase: {next_phase}")
def update_user_phase_end(user_id):
    next_phase = "end"

    # ユーザーのCurrentPhaseを更新
    response = user_table.update_item(
        Key={'user_id': user_id},
        UpdateExpression='SET #phase = :next_phase',
        ExpressionAttributeNames={'#phase': 'CurrentPhase'},
        ExpressionAttributeValues={':next_phase': next_phase},
        ReturnValues="UPDATED_NEW"
    )
    
    if 'Attributes' in response:
        return response['Attributes']
    else:
        # このエラーメッセージはhandle_dynamodb_exceptionによってログに記録されます。
        return None
