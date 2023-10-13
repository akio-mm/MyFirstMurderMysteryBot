import json
import logging
import openai
import os
import sys
import boto3
import lambda_dao

from datetime import datetime
from zoneinfo import ZoneInfo
from botocore.exceptions import ClientError
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# INFOレベル以上のログメッセージを拾うように設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 環境変数を読み込んで中身がなかったらエラー
def load_env_var(var_name):
    value = os.getenv(var_name)
    if value is None:
        logger.error(f'{var_name} is not defined as environmental variables.')
        return None
    return value

#環境変数からそれぞれを取得
CHANNEL_ACCESS_TOKEN = load_env_var('CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = load_env_var('CHANNEL_SECRET')
openai.api_key = load_env_var('SECRET_KEY')

# どれかが無かったら強制終了
if CHANNEL_ACCESS_TOKEN is None or CHANNEL_SECRET is None or openai.api_key is None:
    sys.exit(1)

# 取得した情報をもとにLINEの操作のためのツールを変数に代入してインスタンスにする
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
webhook_handler = WebhookHandler(CHANNEL_SECRET)

# LINE Messaging APIからのWebhookを処理する
def lambda_handler(event, context):

    # リクエストヘッダーにx-line-signatureがあることを確認
    if 'x-line-signature' in event['headers']:
        signature = event['headers']['x-line-signature']

    body = event['body']
    # 受け取ったWebhookのJSONを目視確認できるようにINFOでログに吐く
    logger.info(body)

    try:
        webhook_handler.handle(body, signature)
    except InvalidSignatureError:
        # 署名を検証した結果、飛んできたのがLINEプラットフォームからのWebhookでなければ400を返す
        return {
            'statusCode': 400,
            'body': json.dumps('Only webhooks from the LINE Platform will be accepted.')
        }
    except LineBotApiError as e:
        # 応答メッセージを送ろうとしたがLINEプラットフォームからエラーが返ってきたらエラーを吐く
        logger.error('Got exception from LINE Messaging API: %s\n' % e.message)
        for m in e.error.details:
            logger.error('  %s: %s' % (m.property, m.message))

    return {
        'statusCode': 200,
        'body': json.dumps('Hello from Lambda!')
    }
