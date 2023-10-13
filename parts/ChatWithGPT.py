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

#環境変数を読み込んで中身がなかったらエラー
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

#どれかが無かったら強制終了
if CHANNEL_ACCESS_TOKEN is None or CHANNEL_SECRET is None or openai.api_key is None:
    sys.exit(1)

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
webhook_handler = WebhookHandler(CHANNEL_SECRET)

# ユーザーからのメッセージを処理する
@webhook_handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        # eventからsourceを取得
        source = event.source
        
        # sourceからuserIdを取得
        user_id = source.user_id
        
        # ユーザーからのメッセージ
        query = event.message.text
               
        if query is None:
            logger.error("query is None")
            return        
        
        #会話をChatGPTに渡すmessagesに追加
        messages = [
            {'role': 'system', 'content': current_prompt}, 
            {'role': 'user', 'content': query}
        ]

        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
				# Logにmessagesを出力
        logger.info(messages)
        
        #ファンクションコーリングの関数を呼び出す判断をChatGPTにさせるための条件とか抜き出す単語とかを指定してる
        functions=[
            {
                "name": "want_survey_location",
                "description": "ユーザーが特定の場所を調査したい場合は、場所の名前を保存する。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location_name": {
                            "type": "string",
                            'description': 'ユーザーが調査したい場所の名前。例えば、"リビング"、"テーブル"、"テーブルの影"、"仕事机"、"服のポケット"など。'
                        },
                    }
                },
                "required": ["location_name"]
            },
            {
                "name": "update_user_phase_investigation",
                "description": "ユーザーが推理を宣言してもいいか許可を得てきたときに呼ぶ関数",
                #必要ないけど無いと作用しないのでダミーパラメーターを用意した
                "parameters": {
                  "type": "object",
                  "properties": {
                    "dummy": {
                      "type": "string",
                      "description": "This is a dummy parameter."
                    }
                  },
                  "required": []
                }
            }
        ]

        answer_response = call_gpt(messages, functions)

        # 受け取った回答のJSONを目視確認できるようにINFOでログに吐く
        logger.info(answer_response)

        # answer_responseの中身が無かったらエラーを吐く
        if answer_response is None:
            logger.error("Failed to get a response from GPT.")
            return
        # １回目のChatGPTからの返信を変数answerに入れる。answerは実際にメッセージをLINEに返すときに使う変数。
        answer = answer_response["choices"][0]["message"]["content"]
	# １回目のChatGPTからの返信から２回目の呼び出しに使う部分を取り出す
        message = answer_response["choices"][0]["message"]
               
        # モデルがfunction-callingで関数を呼び出したいかどうかを条件分岐で確認
        if message.get("function_call"):
            function_name = message["function_call"]["name"]
	# ユーザーが推理を宣言してもいいか許可を得てきたときに呼ぶ関数
            if function_name == "update_user_phase_investigation":
                # ユーザーの現在のフェーズを取得
                current_phase = lambda_dao.get_user_info(user_id)['CurrentPhase']
                # 条件に合致するか確認
                if current_phase == 'investigation':
                    # フェーズを次の段階に移行
                    lambda_dao.update_user_phase(user_id, current_phase)
                    second_response = call_second_gpt(messages)
                    answer = second_response["choices"][0]["message"]["content"]
                    
                else:  #なんか無理やり違うフェーズなのに呼び出そうとしてエラー起こすから軌道修正
                    second_response = call_second_gpt(messages)
                    answer = second_response["choices"][0]["message"]["content"]
									
            # ユーザーが特定の場所を調査したい場合呼ぶ関数
            elif function_name == "want_survey_location":
                # ユーザーの現在のフェーズを取得
                current_phase = lambda_dao.get_user_info(user_id)['CurrentPhase']
                # 条件に合致するか確認
                if current_phase == 'investigation':
                    # 場所の名前を取得
                    location_name = arguments["location_name"]
                    url_01 = get_url_based_on_keyword_place(location_name, url_mapping)
                    second_response = call_second_gpt(messages)
                    answer = second_response["choices"][0]["message"]["content"]
                
        # 受け取った回答のJSONを目視確認できるようにINFOでログに吐く
        logger.info(answer)
        
        # GPTからのレスポンス（answer変数）を返信リストに追加
        answer_list.append(TextSendMessage(text=answer))
        
        #answer_listをstrに変換
        answer_str = ', '.join(map(str, answer_list))
        
        # LINE APIを使用して返信リストを送信
        try:
            line_bot_api.reply_message(event.reply_token, answer_list)
        except LineBotApiError as e:
            logger.error(f"LINE API Error: {e}")
            
    except LineBotApiError as e:
    # LINE API特有のエラー
        logger.error(f"LINE API Error: {e}")
        
    except Exception as e:
        # その他の未知のエラー
        logger.error(f"An unexpected error occurred in handle_message: {e.args}")

# gptを呼び出す
def call_gpt(messages, functions):
    return openai.ChatCompletion.create(
        model= 'gpt-3.5-turbo-16k-0613',
        temperature=0.05,
        max_tokens=100,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
        messages= messages,
        functions= functions,
        function_call="auto"
    )

# gptを呼び出す(２回目)
def call_second_gpt(messages):
    return openai.ChatCompletion.create(
        model= 'gpt-3.5-turbo-16k-0613',
        temperature=0.05,
        max_tokens=100,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
        stop=["\n"],
        messages= messages
    )
    

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
