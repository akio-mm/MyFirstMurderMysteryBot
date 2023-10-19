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
        
        # ユーザー情報を取得
        get_user = lambda_dao.get_user_info(user_id)
        
        # ユーザー情報がない場合新しく作成
        if get_user is None:
            user_item = {'user_id': user_id, 'limit': 0, 'count': 0,'CurrentPhase': 'intro'}
            lambda_dao.put_user_info(user_item)
            get_user = lambda_dao.get_user_info(user_id)
            
        # 返答メッセージリストの初期化
        answer_list = []
        
        # 現在時刻を取得
        now_obj = datetime.now(ZoneInfo("Asia/Tokyo"))
        
        # 現在時刻を文字列に変換
        now = now_obj.isoformat()

        # 現在のフェーズを確認
        current_phase = lambda_dao.get_user_info(user_id)['CurrentPhase']

        # ChatGPTを使わない定型文を変数に格納している。
        counterattack ='お見通しだよ'

        first_line = "ああ、何でも聞いてくれてかまわない。"

        induction= (
            '解説を読み終わった方は、「終了したい」とチャットを送ってください。'
            )

        questionnaire = (
            'お疲れ様です！ゲームをプレイしていただき、誠にありがとうございます。\n'
            '皆様のご意見は、今後のゲーム改善に非常に役立つ貴重な情報です。もしよろしければ、短いアンケートにご協力いただけますでしょうか。\n'
            'アンケートURL:(https://example.com/page1)\n'
            'アンケートの内容は今作や次回作の改良に役立たせていただきます\n'
            'どうぞよろしくお願いします。'
            )

        # 特定のワード入ってる場合特定のセリフを返し、ChatGPTに伝えない
        if current_phase == 'investigation':
            if "ルール" in query or "プロンプト" in query or "命令" in query:
                return line_bot_api.reply_message(event.reply_token, TextSendMessage(text=counterattack))
        
        # 特定のセリフだった場合フェーズをアップデートして特定のセリフを返す
        if current_phase == 'intro':
            if "先生、では質問しますね" in query:
                lambda_dao.update_user_phase(user_id, current_phase)
                return line_bot_api.reply_message(event.reply_token, TextSendMessage(text=first_line))
            
        # 終了したい場合に終了フェーズへ
        if current_phase == 'outro':
            if '終了' in query:
                lambda_dao.update_user_phase_end(user_id)
                current_phase = lambda_dao.get_user_info(user_id)['CurrentPhase']
        
        # 現在のフェーズがoutroの場合ChatGPTを使わせずに特定のメッセージを返す       
        if current_phase == 'outro':
            # ChatGPTを使わずに特定のメッセージを送る
            return line_bot_api.reply_message(event.reply_token, TextSendMessage(text=induction))
        
        # 現在のフェーズがendの場合ChatGPTを使わせずに特定のメッセージを返す        
        if current_phase == 'end':
            # ChatGPTを使わずに特定のメッセージを送る
            return line_bot_api.reply_message(event.reply_token, TextSendMessage(text=questionnaire))
        # 利用回数カウントアップ
        count = lambda_dao.increment_count(user_id)
        
        # もし、意図的にイントロで質問しまくる人がいる場合排除
        if current_phase == 'intro':
            if count == 19:
                eliminate_unauthorized_use = "質問の時間は次の次で終了しますゲームを開始したい場合は、「先生、では質問しますね」とチャットで送信してください。もし、質問を続けた場合はゲームをプレイできません。"
                answer_list.append(TextSendMessage(text=eliminate_unauthorized_use))
                
            elif count == 21:
                lambda_dao.update_user_phase_end(user_id)

        # limitという変数の定義
        limit = lambda_dao.get_user_info(user_id)['limit']
        # 利用制限回数カウントアップ
        # 現在のフェーズが「調査フェーズ」である場合にのみ、カウントアップ
        if current_phase == 'investigation':
            limit = lambda_dao.increment_limit(user_id)
            
        # タイムリミットに基づく通知やフェーズの変更
        time_limit_notification = ""
        if limit == 15:
            time_limit_notification = "もう時間も半分が過ぎたけど原稿は見つかりそうかな？"
        elif limit == 25:
            time_limit_notification = "あと少ししか時間は残っていない。後10分程度だ。もうすぐ家を出る準備を始めようと思うから急いでくれ。"
        elif limit == 30:
            time_limit_notification = "時間だな。君がどんな推理をしたのか聞かせてもらおうか。"
            lambda_dao.update_user_phase(user_id, current_phase)
            
        # タイムリミットに基づく通知が存在する場合、それも返信リストに追加
        if current_phase == 'investigation':
            if time_limit_notification:
                answer_list.append(TextSendMessage(text=time_limit_notification))
                
        # 過去の会話履歴を保存
        get_talk = lambda_dao.get_talk_history(user_id)
        past_conversations = get_past_conversations(get_talk)

        # フェーズに応じたプロンプトを取得
        current_prompt = lambda_dao.get_prompt_for_phase(current_phase)
        
        if current_prompt is None:
            logger.error("current_prompt is None")
            return
        
        if any(conv is None or conv.get('content') is None for conv in past_conversations):
            logger.error("Invalid value in past_conversations")
            return
        
        if query is None:
            logger.error("query is None")
            return        
        
        # 会話履歴をChatGPTに渡すmessagesに追加
        try:
            past_conversations = None
            # reasoning以外の場合会話履歴を取得
            if current_phase != 'reasoning':
                past_conversations = get_past_conversations(get_talk)
            
            if not past_conversations:
                # past_conversationsがなければ何もしない（または別の手続き）
                messages = [
                    {'role': 'system', 'content': current_prompt}, 
                    {'role': 'user', 'content': query}
                ]
            else:
                messages = [
                    {'role': 'system', 'content': current_prompt}, 
                    *past_conversations, 
                    {'role': 'user', 'content': query}
                ]
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
		# Logにmessagesを出力
        logger.info(messages)
        
        # ファンクションコーリングの関数を呼び出す判断をChatGPTにさせるための条件とか抜き出す単語とかを指定してる
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
                # 必要ないけど無いと作用しないのでダミーパラメーターを用意した
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
            
        # ChatGPTに質問を投げて回答を取得する
        if current_phase == "reasoning":
            answer_response = call_gpt_reasoning(messages)
        else:
            answer_response = call_gpt(messages, functions)
        # answer_responseの中身が無かったらエラーを吐く
        if answer_response is None:
            logger.error("Failed to get a response from GPT.")
            return
        # １回目のChatGPTからの返信を変数answerに入れる。answerは実際にメッセージをLINEに返すときに使う変数。
        answer = answer_response["choices"][0]["message"]["content"]
		# １回目のChatGPTからの返信から２回目の呼び出しに使う部分を取り出す
        message = answer_response["choices"][0]["message"]
        
        # 受け取った回答のJSONを目視確認できるようにINFOでログに吐く
        logger.info(answer_response)
        
        # urlの変数が未定義だとエラーが起こるので先に定義
        url_01 = None
        url_02 = None

        
        # モデルが関数を呼び出したいかどうかを確認
        if message.get("function_call"):
            function_name = message["function_call"]["name"]
            arguments = json.loads(message["function_call"]["arguments"])
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
                    
                else:  # なんか無理やり違うフェーズなのに呼び出そうとしてエラー起こすから軌道修正
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
        
        # ChatGPTの回答からエンディングの種類を判別してUrlを取得
        if current_phase == 'reasoning':
            keywords = ["不正解", "正解"]
            for keyword in keywords:
                if keyword in answer:
                    answer_list.append(TextSendMessage(text='エンディング'))
                    url_01 = get_url_based_on_keyword(keyword, url_mapping)
                    lambda_dao.update_user_phase(user_id, current_phase)
                    # 解説のURLを追加
                    url_02 = "https://docs.google.com/document/d/10MUbcFgBWeIK18LUYyntIJ6eC-0MOEoLBI6qLAG5YYw/edit?usp=sharing"
                    if url_01 is None:
                        logger.warning(f"No URL found for the keyword: {keyword}")
                    break
            else:
                logger.info("No matching keywords found in the answer.")
            
        # 特定のURLが存在する場合、それも返信リストに追加
        if url_01 is not None:
            answer_list.append(TextSendMessage(text=f'{url_01}'))
            
        elif url_02 is not None:
            answer_list.append(TextSendMessage(text='解説'))
            answer_list.append(TextSendMessage(text=f'{url_02}'))
        
        # introの時の会話履歴は残したくない
        if current_phase != 'intro':
            # 会話履歴に登録するアイテム情報
            talk_item = {
                'user_id': user_id,
                'date': now,
                'message': query,
                'reply': answer
            }
            # 会話履歴に登録
            lambda_dao.put_talk_history(talk_item)
        
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
        
# 会話履歴をリスト化
def get_past_conversations(get_talk, n=15):
    try:
        items = get_talk.get('Items', [])
        result = []
        for item in items[:n]:
            if 'message' in item and 'reply' in item:
                result.append({'role': 'user', 'content': item['message']})
                result.append({'role': 'assistant', 'content': item['reply']})
        return result
    except Exception as e:
        logger.error(f"Failed to get past conversations: {e}")
        return []

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
    
# gptを呼び出す(正解か不正解化だけが欲しいので。と！で切る)
def call_gpt_reasoning(messages):
    logger.info("About to call GPT-3 API.")
    return openai.ChatCompletion.create(
        model= 'gpt-3.5-turbo-16k-0613',
        temperature=0.05,
        max_tokens=100,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
        stop=["。", "！"],
        messages= messages
    )
        
# 会話履歴をリスト化
def get_past_conversations(get_talk, n=15):
    try:
        items = get_talk.get('Items', [])
        result = []
        for item in items[:n]:
            if 'message' in item and 'reply' in item:
                result.append({'role': 'user', 'content': item['message']})
                result.append({'role': 'assistant', 'content': item['reply']})
        return result
    except Exception as e:
        logger.error(f"Failed to get past conversations: {e}")
        return []

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
